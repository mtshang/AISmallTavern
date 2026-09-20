"""核心测评：有答案 / 无答案检索质量与阈值验证。

回答四个问题：
    1. 有答案查询的 top1 分数分布，以及 top1 是否命中预期章节（检索精度）；
    2. 无答案查询（含边界对抗样本）的 top1 分数分布与拦截率（阈值有效性）；
    3. 以 MIN_SCORE=0.85 为界，正负样本的混淆矩阵；换用其他阈值的对比（阈值扫描）；
    4. SCORE_GAP / MAX_CHUNKS 的实际行为：每次检索取几个块、注入几个标题。

只读缓存与索引，不修改任何程序文件。
运行：在项目根目录执行
    .venv\\Scripts\\python.exe eval\\eval_retrieval.py
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402  (先入 path 再取公共设施)
import dataset  # noqa: E402

#/ rag 的三个检索常量与生产代码同源，改动 rag.py 后测评自动跟随。
import rag  # noqa: E402

import numpy as np  # noqa: E402


def evaluate_positives(kb: dict) -> list[dict]:
    """逐条测评正样本：分数、命中正确性、SCORE_GAP / MAX_CHUNKS 行为。"""
    rows: list[dict] = []

    for item in dataset.POSITIVE_QUERIES:
        query = item["query"]
        expect = item["expect"]

        result = common.score_query(kb, query)
        scores = result["scores"]
        indices = result["indices"]
        chunks = kb["chunks"]

        top1_score = float(scores[0])

        #/ 与 rag.search_worldview 相同的比较方式（float32），
        #/ 数出相对间隔 SCORE_GAP 内的达标块数。
        cutoff = np.float32(top1_score - rag.SCORE_GAP)
        gap_count = sum(
            1 for s in scores if np.float32(s) >= cutoff
        )

        #/ 生产逻辑：达标块先截断到 MAX_CHUNKS，再去重标题路径。
        selected = indices[: min(gap_count, rag.MAX_CHUNKS)]
        selected_titles: list[str] = []
        for idx in selected:
            title = chunks[int(idx)]["title_path"]
            if title not in selected_titles:
                selected_titles.append(title)

        #/ top1 / top3 是否命中人工标注的预期章节。
        top1_title = chunks[int(indices[0])]["title_path"]
        top3_titles = [
            chunks[int(i)]["title_path"] for i in indices[:3]
        ]

        hit_top1 = any(s in top1_title for s in expect)
        hit_top3 = any(
            any(s in t for s in expect) for t in top3_titles
        )

        #/ 注入覆盖：预期章节是否出现在实际注入的标题集合里。
        #/ 这是"预检索能否把正确背景给到模型"的直接指标——
        #/ top1 没命中时，SCORE_GAP 的近邻扩展可能仍把正确章节带上。
        hit_injected = any(
            any(s in t for s in expect) for t in selected_titles
        )

        rows.append({
            "query": query,
            "expect": expect,
            "top1_score": round(top1_score, 4),
            "top1_title": common.short_title(top1_title),
            "hit_top1": hit_top1,
            "hit_top3": hit_top3,
            "hit_injected": hit_injected,
            "pass_threshold": top1_score >= rag.MIN_SCORE,
            "gap_chunk_count": gap_count,
            "selected_chunk_count": len(selected),
            "injected_title_count": len(selected_titles),
            "injected_titles": [
                common.short_title(t) for t in selected_titles
            ],
            "encode_ms": round(result["encode_ms"], 1),
            "search_ms": round(result["search_ms"], 1),
        })

    return rows


def evaluate_negatives(kb: dict, queries: list[str], kind: str) -> list[dict]:
    """逐条测评负样本：top1 分数、最像的块（误报来源）、是否被阈值拦截。"""
    rows: list[dict] = []
    chunks = kb["chunks"]

    for query in queries:
        result = common.score_query(kb, query)
        top1_score = float(result["scores"][0])
        top1_title = chunks[int(result["indices"][0])]["title_path"]

        rows.append({
            "kind": kind,
            "query": query,
            "top1_score": round(top1_score, 4),
            "top1_title": common.short_title(top1_title),
            #/ 拦截 = top1 低于阈值，即生产路径会返回空结果。
            "blocked": top1_score < rag.MIN_SCORE,
        })

    return rows


def threshold_scan(
    positive_rows: list[dict],
    negative_rows: list[dict],
    hard_rows: list[dict],
) -> list[dict]:
    """对一组候选阈值计算各项比率，验证 0.85 的交界选择。"""
    candidates = [0.78, 0.80, 0.82, 0.83, 0.84, 0.85, 0.86, 0.88, 0.90]

    pos_scores = [r["top1_score"] for r in positive_rows]
    neg_scores = [r["top1_score"] for r in negative_rows]
    hard_scores = [r["top1_score"] for r in hard_rows]

    total = len(pos_scores) + len(neg_scores) + len(hard_scores)

    scan: list[dict] = []
    for t in candidates:
        pos_pass = sum(1 for s in pos_scores if s >= t)
        neg_block = sum(1 for s in neg_scores if s < t)
        hard_block = sum(1 for s in hard_scores if s < t)

        scan.append({
            "threshold": t,
            #/ 正样本通过率（类似召回率）：有答案的查询能注入背景的比例。
            "pos_pass_rate": round(pos_pass / len(pos_scores), 4),
            #/ 普通负样本拦截率（类似特异度）。
            "neg_block_rate": round(neg_block / len(neg_scores), 4),
            #/ 边界负样本拦截率：抗近似话题穿透的能力。
            "hard_block_rate": round(hard_block / len(hard_scores), 4),
            #/ 总体准确率：(通过的正 + 拦截的负) / 全体。
            "accuracy": round(
                (pos_pass + neg_block + hard_block) / total, 4
            ),
        })

    return scan


def score_gap_scan(kb: dict) -> list[dict]:
    """SCORE_GAP 候选值扫描：注入覆盖率与注入量的权衡。

    SCORE_GAP 的作用是把"分数落在 top1-GAP 窗口内"的块一起
    纳入注入集合，因此它的两个效应方向相反：
        GAP 越大 → 注入覆盖率越高（召回），但注入量越大
        （prompt 成本与噪声），且被 MAX_CHUNKS 截断得越狠。

    对每个候选 GAP 值，用与生产完全相同的选择逻辑
    （窗口筛选 → MAX_CHUNKS 截断 → 标题去重）计算：
        - 正样本注入覆盖率（预期章节是否进入注入集合）；
        - 注入标题数（均值 / P90 / 最大，代表注入成本）；
        - 穿透阈值的边界负样本的注入量（误报的真实代价）。
    """
    gaps = [0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.08, 0.10]
    chunks = kb["chunks"]

    #/ 先把全部查询编码一遍，之后所有 GAP 值只做内存计算，不重复推理。
    pos_results = [
        (item, common.score_query(kb, item["query"]))
        for item in dataset.POSITIVE_QUERIES
    ]
    hard_results = [
        common.score_query(kb, q)
        for q in dataset.HARD_NEGATIVE_QUERIES
    ]

    def inject_titles(scores: list[float], indices: list[int], gap: float) -> list[str]:
        """复刻 rag.search_worldview 的选择逻辑：窗口、截断、去重。"""
        scores_f32 = np.asarray(scores, dtype=np.float32)
        top1 = float(scores_f32[0])
        cutoff = np.float32(top1 - gap)
        high = [
            int(i)
            for i, s in zip(indices, scores_f32)
            if s >= cutoff
        ][: rag.MAX_CHUNKS]

        titles: list[str] = []
        for idx in high:
            title = chunks[idx]["title_path"]
            if title not in titles:
                titles.append(title)
        return titles

    rows: list[dict] = []
    for gap in gaps:
        covered = 0
        title_counts: list[int] = []

        for item, result in pos_results:
            titles = inject_titles(
                result["scores"], result["indices"], gap
            )
            title_counts.append(len(titles))
            if any(
                any(s in t for s in item["expect"]) for t in titles
            ):
                covered += 1

        #/ 穿透阈值（top1 >= MIN_SCORE）的边界负样本：注入了多少个标题。
        hard_counts: list[int] = []
        for result in hard_results:
            if float(result["scores"][0]) >= rag.MIN_SCORE:
                titles = inject_titles(
                    result["scores"], result["indices"], gap
                )
                hard_counts.append(len(titles))

        rows.append({
            "gap": gap,
            "coverage": round(covered / len(pos_results), 4),
            "avg_titles": round(
                sum(title_counts) / len(title_counts), 2
            ),
            "p90_titles": round(
                common.percentile(
                    [float(v) for v in title_counts], 90
                ),
                1,
            ),
            "max_titles": max(title_counts),
            #/ 每条穿透边界负样本的注入标题数（空列表 = 该 GAP 下无穿透）。
            "hard_injected_titles": hard_counts,
        })

    return rows


def build_report(
    kb: dict,
    positive_rows: list[dict],
    negative_rows: list[dict],
    hard_rows: list[dict],
    scan: list[dict],
    gap_scan: list[dict],
    summary: dict,
) -> str:
    """生成人读的 Markdown 明细报告。"""
    enc = kb["encoding"]
    lines: list[str] = []

    lines.append("# RAG 检索测评明细报告")
    lines.append("")
    lines.append(f"- 生成时间：{summary['ran_at']}")
    lines.append(f"- 语料：世界观.md（{summary['chunk_count']} 个分块，"
                 f"{enc['dimension']} 维，{enc['index_type']} 余弦检索）")
    lines.append(f"- 嵌入模型：{Path(enc['model_dir']).name}"
                 f"（{enc['model_version']}）")
    lines.append(f"- 检索常量：MIN_SCORE={rag.MIN_SCORE}，"
                 f"SCORE_GAP={rag.SCORE_GAP}，MAX_CHUNKS={rag.MAX_CHUNKS}")
    lines.append(f"- 索引缓存：{'本次发生重建' if kb['rebuilt'] else '命中已有缓存（未重建）'}")
    lines.append("")

    #/ ---- 表 1：正样本明细 ----
    lines.append("## 一、有答案查询（正样本）")
    lines.append("")
    lines.append("| # | 查询 | top1 分数 | top1 命中章节 | top1 命中 | top3 命中 | 预期在注入集 | 达标块数 | 注入标题数 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for i, r in enumerate(positive_rows, 1):
        lines.append(
            f"| {i} | {r['query']} | {r['top1_score']:.4f} "
            f"| {r['top1_title']} | {'✓' if r['hit_top1'] else '✗'} "
            f"| {'✓' if r['hit_top3'] else '✗'} "
            f"| {'✓' if r['hit_injected'] else '✗'} "
            f"| {r['gap_chunk_count']} | {r['injected_title_count']} |"
        )
    lines.append("")

    #/ ---- 表 2：负样本明细 ----
    lines.append("## 二、无答案查询（负样本 / 边界样本）")
    lines.append("")
    lines.append("| 查询 | 类型 | top1 分数 | 最相似块 | 是否拦截 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for r in negative_rows + hard_rows:
        kind = "普通" if r["kind"] == "negative" else "边界"
        lines.append(
            f"| {r['query']} | {kind} | {r['top1_score']:.4f} "
            f"| {r['top1_title']} | {'✓ 拦截' if r['blocked'] else '✗ 穿透'} |"
        )
    lines.append("")

    #/ ---- 表 3：阈值扫描 ----
    lines.append("## 三、阈值扫描（MIN_SCORE 候选值对比）")
    lines.append("")
    lines.append("| 阈值 | 正样本通过率 | 普通负样本拦截率 | 边界负样本拦截率 | 总体准确率 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for s in scan:
        lines.append(
            f"| {s['threshold']:.2f} | {s['pos_pass_rate']:.1%} "
            f"| {s['neg_block_rate']:.1%} | {s['hard_block_rate']:.1%} "
            f"| {s['accuracy']:.1%} |"
        )
    lines.append("")

    #/ ---- 表 4：SCORE_GAP 扫描 ----
    lines.append("## 四、SCORE_GAP 候选值扫描（MAX_CHUNKS=6 截断下的权衡）")
    lines.append("")
    lines.append("| SCORE_GAP | 注入覆盖率 | 注入标题数（均值） | P90 | 最大 | 穿透边界负样本的注入量 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for g in gap_scan:
        hard = g["hard_injected_titles"]
        hard_text = (
            "、".join(str(v) for v in hard) if hard else "—"
        )
        lines.append(
            f"| {g['gap']:.2f} | {g['coverage']:.1%} "
            f"| {g['avg_titles']:.2f} | {g['p90_titles']:.1f} "
            f"| {g['max_titles']} | {hard_text} |"
        )
    lines.append("")

    #/ ---- 表 5：SCORE_GAP 实测行为 ----
    lines.append("## 五、SCORE_GAP / MAX_CHUNKS 行为（正样本，SCORE_GAP=0.03）")
    lines.append("")
    lines.append("| 指标 | 最小 | 均值 | P90 | 最大 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for key, label in (
        ("gap_chunk_count", "达标块数（top1−0.03 内）"),
        ("injected_title_count", "实际注入标题数"),
    ):
        values = [r[key] for r in positive_rows]
        block = common.stats_block(values)
        lines.append(
            f"| {label} | {block['min']} | {block['mean']} "
            f"| {block['p90']} | {block['max']} |"
        )
    lines.append("")

    lines.append("## 六、统计汇总")
    lines.append("")
    for key, value in summary["distributions"].items():
        lines.append(
            f"- **{key}**：min={value['min']}，mean={value['mean']}，"
            f"p90={value['p90']}，max={value['max']}"
        )
    lines.append("")
    for key, value in summary["metrics"].items():
        lines.append(f"- **{key}**：{value:.1%}")
    lines.append("")

    return "\n".join(lines)


def run() -> dict:
    """执行完整检索测评，返回汇总字典（供 run_all 聚合）。"""
    common.setup_console()

    print("=" * 62)
    print("测评一：RAG 检索质量与阈值验证")
    print("=" * 62)

    kb = common.load_knowledge_base()
    print(
        f"[环境] 分块数={len(kb['chunks'])}，维度="
        f"{kb['encoding']['dimension']}，"
        f"缓存{'重建' if kb['rebuilt'] else '命中（未重建）'}"
    )

    positive_rows = evaluate_positives(kb)
    negative_rows = evaluate_negatives(
        kb, dataset.NEGATIVE_QUERIES, "negative"
    )
    hard_rows = evaluate_negatives(
        kb, dataset.HARD_NEGATIVE_QUERIES, "hard_negative"
    )
    scan = threshold_scan(positive_rows, negative_rows, hard_rows)
    gap_scan = score_gap_scan(kb)

    #/ ---- 汇总统计 ----
    pos_scores = [r["top1_score"] for r in positive_rows]
    neg_scores = [r["top1_score"] for r in negative_rows]
    hard_scores = [r["top1_score"] for r in hard_rows]

    hit_top1 = sum(1 for r in positive_rows if r["hit_top1"])
    hit_top3 = sum(1 for r in positive_rows if r["hit_top3"])
    hit_injected = sum(1 for r in positive_rows if r["hit_injected"])
    pos_pass = sum(1 for r in positive_rows if r["pass_threshold"])
    neg_block = sum(1 for r in negative_rows if r["blocked"])
    hard_block = sum(1 for r in hard_rows if r["blocked"])

    summary = {
        "ran_at": datetime.datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "chunk_count": len(kb["chunks"]),
        "constants": {
            "MIN_SCORE": rag.MIN_SCORE,
            "SCORE_GAP": rag.SCORE_GAP,
            "MAX_CHUNKS": rag.MAX_CHUNKS,
        },
        "index_rebuilt": kb["rebuilt"],
        "counts": {
            "positive": len(positive_rows),
            "negative": len(negative_rows),
            "hard_negative": len(hard_rows),
        },
        "distributions": {
            "正样本 top1 分数": common.stats_block(pos_scores),
            "普通负样本 top1 分数": common.stats_block(neg_scores),
            "边界负样本 top1 分数": common.stats_block(hard_scores),
        },
        "metrics": {
            "正样本 top1 命中率": round(hit_top1 / len(positive_rows), 4),
            "正样本 top3 命中率": round(hit_top3 / len(positive_rows), 4),
            "正样本注入覆盖率": round(
                hit_injected / len(positive_rows), 4
            ),
            "正样本阈值通过率": round(pos_pass / len(positive_rows), 4),
            "普通负样本拦截率": round(neg_block / len(negative_rows), 4),
            "边界负样本拦截率": round(hard_block / len(hard_rows), 4),
        },
    }

    #/ ---- 控制台摘要 ----
    print()
    print("[正样本 top1 分数] ", summary["distributions"]["正样本 top1 分数"])
    print("[普通负样本 top1]  ", summary["distributions"]["普通负样本 top1 分数"])
    print("[边界负样本 top1]  ", summary["distributions"]["边界负样本 top1 分数"])
    print()
    print("[指标]", json_dumps_compat(summary["metrics"]))
    print()
    print("[阈值扫描]")
    print(f"  {'阈值':>5} | {'正通过':>6} | {'负拦截':>6} | {'边界拦截':>6} | {'准确率':>6}")
    for s in scan:
        print(
            f"  {s['threshold']:>5.2f} | {s['pos_pass_rate']:>6.1%} "
            f"| {s['neg_block_rate']:>6.1%} | {s['hard_block_rate']:>6.1%} "
            f"| {s['accuracy']:>6.1%}"
        )

    print()
    print("[SCORE_GAP 扫描]")
    print(
        f"  {'GAP':>5} | {'注入覆盖率':>8} | {'平均注入标题':>8} "
        f"| {'P90':>4} | {'最大':>4} | 穿透边界负样本注入量"
    )
    for g in gap_scan:
        hard = "、".join(str(v) for v in g["hard_injected_titles"]) or "—"
        print(
            f"  {g['gap']:>5.2f} | {g['coverage']:>8.1%} "
            f"| {g['avg_titles']:>8.2f} | {g['p90_titles']:>4.1f} "
            f"| {g['max_titles']:>4} | {hard}"
        )

    #/ ---- 持久化结果 ----
    payload = {
        "summary": summary,
        "positives": positive_rows,
        "negatives": negative_rows,
        "hard_negatives": hard_rows,
        "threshold_scan": scan,
        "score_gap_scan": gap_scan,
    }
    json_path = common.save_json("retrieval.json", payload)

    report_path = common.RESULTS_DIR / "retrieval_detail.md"
    report_path.write_text(
        build_report(
            kb,
            positive_rows,
            negative_rows,
            hard_rows,
            scan,
            gap_scan,
            summary,
        ),
        encoding="utf-8",
    )

    print()
    print(f"[输出] 明细 JSON：{json_path}")
    print(f"[输出] 原始明细：{report_path}")
    print()

    return summary


def json_dumps_compat(data: dict) -> str:
    """把指标字典压成一行中文摘要，方便控制台查看。"""
    import json

    return json.dumps(data, ensure_ascii=False)


if __name__ == "__main__":
    run()
