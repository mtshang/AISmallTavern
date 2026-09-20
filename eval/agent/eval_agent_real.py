"""Step B：真实小批量工具调用测评（会产生真实 API 费用）。

测什么：
    模型面对 40 条意图样本时的工具决策质量——
    该不该调、调哪个、参数对不对。

怎么测：
    1. 从 .env 读取模型配置（编程式读取，不打印凭证）；
    2. 每条样本构造 [system(人设), user(查询)] + 生产同款 tools 定义；
       注意：不注入预检索背景——本测评测的是模型"自主决策"，
       背景注入后的行为属于端到端测评的范畴；
    3. 非流式请求（tool_choice=auto，不设 temperature，对齐生产参数），
       每条采样 3 次，观察决策稳定性；
    4. 判分维度：
       触发正确：该调且调了 / 不该调且没调；
       工具正确：调用的工具名与期望一致；
       参数合法：arguments 是合法 JSON 且结构符合 schema；
       参数正确：掷骰用例的 sides/count 与期望一致。

费用预估：40 条 × 3 次 = 120 次请求。
运行：
    .venv\\Scripts\\python.exe eval\\agent\\eval_agent_real.py --smoke   # 5 条 × 1 次
    .venv\\Scripts\\python.exe eval\\agent\\eval_agent_real.py           # 全量 40 × 3
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import time

import agent_common as common  # noqa: E402
import agent_dataset  # noqa: E402


def judge_one(sample: dict, message: dict | None) -> dict:
    """对单次响应判分。

    message：非流式响应里的 choices[0].message（dict 形式），
             请求异常时为 None。
    """
    expected = sample["expected_tool"]
    result: dict = {
        "called": False,
        "tool_name": None,
        "args_raw": None,
        "args_parsed": None,
        "trigger_correct": False,
        "tool_correct": False,
        "args_valid": False,
        "args_values_correct": None,
        "reply_excerpt": None,
    }

    if message is None:
        #/ 请求异常：所有维度记 False，单独由 error 字段说明。
        return result

    tool_calls = message.get("tool_calls") or []
    result["called"] = bool(tool_calls)

    if tool_calls:
        first = tool_calls[0]
        function = first.get("function", {})
        result["tool_name"] = function.get("name")
        result["args_raw"] = function.get("arguments")

        #/ 触发正确性：期望不调 → 不能调；期望调 → 要调。
        if expected is None:
            result["trigger_correct"] = False
        else:
            result["trigger_correct"] = True

        #/ 工具正确性：调用的工具名 == 期望工具（看所有调用里是否有匹配的）。
        names = [
            tc.get("function", {}).get("name") for tc in tool_calls
        ]
        result["tool_correct"] = expected in names

        #/ 参数合法性：匹配期望工具的那个调用，arguments 须为合法 JSON dict。
        target = next(
            (
                tc
                for tc in tool_calls
                if tc.get("function", {}).get("name") == expected
            ),
            None,
        )
        if target is not None:
            raw = target.get("function", {}).get("arguments")
            try:
                parsed = json.loads(raw) if raw else None
                if isinstance(parsed, dict):
                    result["args_valid"] = True
                    result["args_parsed"] = parsed

                    #/ 参数值正确性（仅掷骰用例标注了期望值）。
                    expected_args = sample.get("expected_args")
                    if expected_args:
                        result["args_values_correct"] = (
                            parsed.get("sides") == expected_args["sides"]
                            and parsed.get("count") == expected_args["count"]
                        )
                    elif expected == "search_worldview":
                        #/ 检索用例：query_string 非空字符串即可。
                        query = parsed.get("query_string")
                        result["args_values_correct"] = (
                            isinstance(query, str)
                            and bool(query.strip())
                        )
            except (json.JSONDecodeError, TypeError):
                pass
    else:
        #/ 未调用任何工具。
        result["trigger_correct"] = expected is None
        result["tool_correct"] = expected is None
        result["args_valid"] = expected is None

        content = message.get("content") or ""
        result["reply_excerpt"] = content[:120]

    return result


async def run_once(
    client,
    model: str,
    system_prompt: str,
    query: str,
    tools: list[dict],
) -> tuple[dict | None, str | None, float]:
    """单次请求。返回 (message_dict, error_text, latency_ms)。"""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query},
    ]

    t0 = time.perf_counter()
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            stream=False,
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0

        message = response.choices[0].message.model_dump(mode="json")
        return message, None, latency_ms
    except Exception as error:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return None, f"{type(error).__name__}: {error}", latency_ms


async def main(smoke: bool) -> None:
    common.setup_console()

    print("=" * 62)
    print("测评五（Step B）：真实工具调用决策（产生真实 API 费用）")
    print("=" * 62)

    api_key, base_url, model = common.load_llm_env()
    print(f"[配置] 模型：{model}，接口：{common.safe_endpoint(base_url)}")

    tools = common.load_assets_tools()
    system_prompt = common.load_character_prompt()
    print(f"[工具] {len(tools)} 个：{[t['function']['name'] for t in tools]}")
    print(f"[人设] system 长度 {len(system_prompt)} 字符")

    samples = agent_dataset.SAMPLES
    if smoke:
        #/ 冒烟集：每类各挑几条，验证链路。
        picks = [0, 13, 27, 32, 39]
        samples = [samples[i] for i in picks]
        runs_per_query = 1
    else:
        runs_per_query = 3

    total_requests = len(samples) * runs_per_query
    print(
        f"[样本] {len(samples)} 条 × {runs_per_query} 次采样"
        f" = {total_requests} 次请求"
    )

    client = common.make_client(api_key, base_url)

    rows: list[dict] = []
    error_streak = 0

    try:
        for idx, sample in enumerate(samples, 1):
            runs: list[dict] = []
            for run_no in range(runs_per_query):
                message, error, latency_ms = await run_once(
                    client, model, system_prompt, sample["query"], tools
                )
                if error:
                    error_streak += 1
                    if error_streak >= 5:
                        raise RuntimeError(
                            f"连续 5 次请求失败，中止测评以避免浪费额度。"
                            f"最后一次错误：{error}"
                        )
                else:
                    error_streak = 0

                judged = judge_one(sample, message)
                judged["error"] = error
                judged["latency_ms"] = round(latency_ms, 1)
                judged["finish_reason"] = (
                    message.get("finish_reason") if message else None
                )
                runs.append(judged)

                #/ 请求间隔，降低限流风险。
                await asyncio.sleep(0.2)

            row = {
                "index": idx - 1,
                "query": sample["query"],
                "category": sample["category"],
                "expected_tool": sample["expected_tool"],
                "note": sample["note"],
                "tricky": bool(sample.get("tricky")),
                "expected_args": sample.get("expected_args"),
                "runs": runs,
                "stable": (
                    len({r["trigger_correct"] for r in runs}) == 1
                    if runs
                    else False
                ),
                "majority_trigger_correct": (
                    sum(
                        1 for r in runs if r["trigger_correct"]
                    )
                    > len(runs) / 2
                ),
            }
            rows.append(row)

            marks = "".join(
                "✓" if r["trigger_correct"] else "✗" for r in runs
            )
            called_names = "/".join(
                sorted({str(r["tool_name"]) for r in runs if r["called"]})
            ) or "（未调用）"
            print(
                f"  [{idx:>2}/{len(samples)}] {marks} "
                f"期望={sample['expected_tool'] or '不调用':<16} "
                f"实际={called_names:<32} {sample['query'][:18]}"
            )
    finally:
        await client.close()

    #/ ---- 汇总统计 ----
    all_runs = [r for row in rows for r in row["runs"]]
    valid_runs = [r for r in all_runs if r.get("error") is None]

    def rate(sub: list[dict], key: str) -> float:
        return (
            round(sum(1 for r in sub if r[key]) / len(sub), 4)
            if sub
            else 0.0
        )

    #/ 按期望分层的采样（row 维度分组，每条 run 归属明确）。
    should_call_runs = [
        r
        for row in rows
        if row["expected_tool"]
        for r in row["runs"]
        if r.get("error") is None
    ]
    no_call_runs = [
        r
        for row in rows
        if not row["expected_tool"]
        for r in row["runs"]
        if r.get("error") is None
    ]

    summary = {
        "ran_at": datetime.datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "model": model,
        "endpoint": common.safe_endpoint(base_url),
        "request_mode": (
            "非流式 chat.completions，tool_choice=auto，"
            "不设 temperature（对齐生产参数）"
        ),
        "context_note": (
            "消息仅含 system(人设) + user(查询)，不注入预检索背景；"
            "测的是模型的自主工具决策"
        ),
        "sample_count": len(rows),
        "runs_per_query": runs_per_query,
        "total_requests": total_requests,
        "error_runs": sum(1 for r in all_runs if r.get("error")),
        "metrics": {
            "触发正确率（按采样）": rate(valid_runs, "trigger_correct"),
            "工具选择正确率（按采样）": rate(valid_runs, "tool_correct"),
            "参数 JSON 合法率（按采样）": rate(valid_runs, "args_valid"),
        },
        "should_call": {
            "该调样本数": len(
                [row for row in rows if row["expected_tool"]]
            ),
            "不该调样本数": len(
                [row for row in rows if not row["expected_tool"]]
            ),
            "该调且调了（按采样）": rate(
                should_call_runs, "trigger_correct"
            ),
            "不该调且没调（按采样）": rate(
                no_call_runs, "trigger_correct"
            ),
        },
        "stable_queries": sum(1 for row in rows if row["stable"]),
    }

    #/ 按意图分层统计（每个 category 的触发正确率）。
    categories: dict[str, dict] = {}
    for row in rows:
        cat = row["category"]
        bucket = categories.setdefault(
            cat, {"samples": 0, "runs": 0, "correct_runs": 0}
        )
        bucket["samples"] += 1
        for r in row["runs"]:
            if r.get("error") is None:
                bucket["runs"] += 1
                bucket["correct_runs"] += int(r["trigger_correct"])
    for bucket in categories.values():
        bucket["trigger_rate"] = (
            round(bucket["correct_runs"] / bucket["runs"], 4)
            if bucket["runs"]
            else 0.0
        )
    summary["categories"] = categories

    #/ 参数值正确率（掷骰 + 检索分开统计）。
    dice_runs = [
        r
        for row in rows
        if row["expected_tool"] == "roll_dice"
        for r in row["runs"]
        if r.get("error") is None and r.get("called")
    ]
    search_runs = [
        r
        for row in rows
        if row["expected_tool"] == "search_worldview"
        for r in row["runs"]
        if r.get("error") is None and r.get("called")
    ]
    if dice_runs:
        summary["metrics"]["掷骰参数值正确率"] = rate(
            [r for r in dice_runs if r["args_values_correct"] is not None],
            "args_values_correct",
        )
    if search_runs:
        summary["metrics"]["检索参数可用率"] = rate(
            [r for r in search_runs if r["args_values_correct"] is not None],
            "args_values_correct",
        )

    print()
    print("[指标]", json.dumps(summary["metrics"], ensure_ascii=False))
    print(
        f"[稳定性] {summary['stable_queries']}/{len(rows)} 条查询"
        "三次采样结论一致"
    )
    print(f"[异常] {summary['error_runs']} 次请求失败")

    payload = {"summary": summary, "rows": rows}
    json_path = common.save_json("agent_real.json", payload)
    print(f"[输出] {json_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="冒烟模式：5 条样本 × 1 次采样，验证链路",
    )
    args = parser.parse_args()
    asyncio.run(main(smoke=args.smoke))
