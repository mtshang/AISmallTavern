"""端到端问答测评：无 RAG 注入 vs 有 RAG 注入的 A/B 对比。

证明的问题：
    检索质量测评只证明了"检索找得到正确章节"，本测评证明
    "注入的背景真的让模型答对了原本答不出的题"——RAG 价值
    的最终量化。

实验设计：
    A 组（无 RAG）：messages = [system(人设), user(问题)]
    B 组（有 RAG）：messages = [system(人设), user(注入+问题)]，
        注入格式与 ui.py 生产代码逐字一致：
        <reference_character_worldview>
        {检索结果}
        </reference_character_worldview>

        <user_question>
        {问题}
        </user_question>
    背景由 rag.search_worldview 真实检索产生（不是手工挑选），
    因此 B 组成绩综合反映了"检索 + 注入 + 模型阅读"整条链路。

    两组都不传 tools——隔离"背景注入"这一单一变量，
    工具自主追问属于另一个测评的范畴。

判分：
    封闭式硬事实题，答案关键词匹配，全自动；
    A 组答错再分类：如实拒答 vs 编造（幻觉）。

费用预估：16 题 × 2 组 × 2 次采样 = 64 次请求。
运行：
    .venv\\Scripts\\python.exe eval\\e2e\\eval_e2e_ab.py --smoke   # 3 题 × 1 次
    .venv\\Scripts\\python.exe eval\\e2e\\eval_e2e_ab.py           # 全量 16 × 2 × 2
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import time
from pathlib import Path

import sys

#/ 本目录入 path（找 e2e_dataset 与 agent_common）。
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "agent"))

import agent_common as common  # noqa: E402
import e2e_dataset  # noqa: E402

import rag  # noqa: E402  (agent_common 已把项目根加入 sys.path)

#/ e2e 自己的结果目录（agent_common.save_json 写的是 agent/results/）。
E2E_RESULTS_DIR: Path = _HERE / "results"


def save_json(name: str, data: dict) -> Path:
    """把结果 JSON 写入 e2e/results/。"""
    E2E_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = E2E_RESULTS_DIR / name
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def judge(answer: str, keywords: list[str]) -> str:
    """判分：correct / refuse / fabricate。"""
    text = (answer or "").casefold()

    if any(k.casefold() in text for k in keywords):
        return "correct"

    if any(m in text for m in e2e_dataset.REFUSE_MARKERS):
        return "refuse"

    return "fabricate"


def build_rag_user_message(background: str, question: str) -> str:
    """复刻 ui.py 预检索注入的消息格式（逐字一致）。"""
    return (
        "<reference_character_worldview>\n"
        f"{background.strip()}\n"
        "</reference_character_worldview>\n\n"
        "<user_question>\n"
        f"{question.strip()}\n"
        "</user_question>"
    )


async def ask(
    client,
    model: str,
    system_prompt: str,
    user_content: str,
) -> tuple[str | None, str | None]:
    """单次问答，返回 (回答文本, 错误信息)。"""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            stream=False,
        )
        content = response.choices[0].message.content or ""
        return content, None
    except Exception as error:
        return None, f"{type(error).__name__}: {error}"


async def main(smoke: bool) -> None:
    common.setup_console()

    print("=" * 62)
    print("测评六：端到端问答 A/B（无 RAG vs 有 RAG）")
    print("=" * 62)

    api_key, base_url, model = common.load_llm_env()
    print(f"[配置] 模型：{model}，接口：{common.safe_endpoint(base_url)}")

    system_prompt = common.load_character_prompt()

    questions = e2e_dataset.QUESTIONS
    if smoke:
        questions = [questions[i] for i in (0, 2, 9)]
        runs = 1
    else:
        runs = 2

    #/ ---- 先做真实预检索，为每题准备 B 组背景 ----
    print("[检索] 正在为每题执行真实预检索……")
    backgrounds: list[str] = []
    for q in questions:
        background = rag.search_worldview(
            common.MODEL_DIR,
            common.CHARACTER_DIR,
            q["question"],
        )
        backgrounds.append(background)
        status = f"注入 {len(background)} 字符" if background else "（检索无结果）"
        print(f"  {q['question'][:24]:<26} {status}")

    total_requests = len(questions) * 2 * runs
    print(f"[样本] {len(questions)} 题 × 2 组 × {runs} 次采样 = {total_requests} 次请求")

    client = common.make_client(api_key, base_url)

    rows: list[dict] = []
    error_streak = 0

    try:
        for idx, (q, background) in enumerate(
            zip(questions, backgrounds), 1
        ):
            row = {
                "index": idx - 1,
                "question": q["question"],
                "answer": q["answer"],
                "chapter": q["chapter"],
                "keywords": q["keywords"],
                "background_chars": len(background),
                "no_rag": [],
                "rag": [],
            }

            for group_key, user_content in (
                ("no_rag", q["question"]),
                ("rag", build_rag_user_message(background, q["question"])),
            ):
                for _ in range(runs):
                    t0 = time.perf_counter()
                    answer, error = await ask(
                        client, model, system_prompt, user_content
                    )
                    latency_ms = round(
                        (time.perf_counter() - t0) * 1000.0, 1
                    )

                    if error:
                        error_streak += 1
                        if error_streak >= 5:
                            raise RuntimeError(
                                f"连续 5 次请求失败，中止测评。最后错误：{error}"
                            )
                    else:
                        error_streak = 0

                    verdict = (
                        judge(answer, q["keywords"])
                        if answer is not None
                        else "error"
                    )
                    row[group_key].append(
                        {
                            "verdict": verdict,
                            "answer_excerpt": (answer or "")[:200],
                            "error": error,
                            "latency_ms": latency_ms,
                        }
                    )
                    await asyncio.sleep(0.2)

            rows.append(row)

            a_verdicts = [r["verdict"] for r in row["no_rag"]]
            b_verdicts = [r["verdict"] for r in row["rag"]]
            print(
                f"  [{idx:>2}/{len(questions)}] "
                f"A(无RAG)={'/'.join(a_verdicts):<22} "
                f"B(有RAG)={'/'.join(b_verdicts):<22} "
                f"{q['question'][:20]}"
            )
    finally:
        await client.close()

    #/ ---- 汇总 ----
    def group_rate(group: str, verdict: str) -> tuple[int, int]:
        total = [
            r
            for row in rows
            for r in row[group]
            if r["verdict"] != "error"
        ]
        hit = [r for r in total if r["verdict"] == verdict]
        return len(hit), len(total)

    a_correct, a_total = group_rate("no_rag", "correct")
    b_correct, b_total = group_rate("rag", "correct")
    a_refuse, _ = group_rate("no_rag", "refuse")
    a_fabricate, _ = group_rate("no_rag", "fabricate")

    #/ 检索注入是否成功也影响 B 组：分开统计注入成功/未命中的题。
    injected_rows = [row for row in rows if row["background_chars"] > 0]
    missed_rows = [row for row in rows if row["background_chars"] == 0]

    def rows_rate(row_list: list[dict], group: str) -> tuple[int, int]:
        total = [
            r
            for row in row_list
            for r in row[group]
            if r["verdict"] != "error"
        ]
        hit = [r for r in total if r["verdict"] == "correct"]
        return len(hit), len(total)

    inj_b_correct, inj_b_total = rows_rate(injected_rows, "rag")
    inj_a_correct, inj_a_total = rows_rate(injected_rows, "no_rag")

    summary = {
        "ran_at": datetime.datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "model": model,
        "endpoint": common.safe_endpoint(base_url),
        "request_mode": (
            "非流式 chat.completions，不设 temperature（对齐生产参数），"
            "两组均不传 tools（隔离背景注入单一变量）"
        ),
        "question_count": len(rows),
        "runs_per_group": runs,
        "total_requests": total_requests,
        "no_rag": {
            "correct": a_correct,
            "total": a_total,
            "accuracy": round(a_correct / a_total, 4) if a_total else 0.0,
            "refuse": a_refuse,
            "fabricate": a_fabricate,
        },
        "rag": {
            "correct": b_correct,
            "total": b_total,
            "accuracy": round(b_correct / b_total, 4) if b_total else 0.0,
        },
        "injected_only": {
            "note": "只统计预检索成功注入背景的题目",
            "question_count": len(injected_rows),
            "no_rag_correct": inj_a_correct,
            "no_rag_total": inj_a_total,
            "rag_correct": inj_b_correct,
            "rag_total": inj_b_total,
        },
        "retrieval_missed_questions": [
            row["question"] for row in missed_rows
        ],
    }

    print()
    print(
        f"[A 组·无 RAG] 答对 {a_correct}/{a_total}"
        f"（{summary['no_rag']['accuracy']:.1%}），"
        f"其中拒答 {a_refuse}、编造 {a_fabricate}"
    )
    print(
        f"[B 组·有 RAG] 答对 {b_correct}/{b_total}"
        f"（{summary['rag']['accuracy']:.1%}）"
    )
    if injected_rows:
        print(
            f"[注入成功子集] {len(injected_rows)} 题："
            f"A 组 {inj_a_correct}/{inj_a_total} → "
            f"B 组 {inj_b_correct}/{inj_b_total}"
        )
    if missed_rows:
        print(
            f"[检索未命中] {[row['question'] for row in missed_rows]}"
        )

    payload = {"summary": summary, "rows": rows}
    json_path = save_json("e2e_ab.json", payload)
    print(f"[输出] {json_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="冒烟模式：3 题 × 1 次采样",
    )
    args = parser.parse_args()
    asyncio.run(main(smoke=args.smoke))
