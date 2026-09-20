"""检索质量报告生成器：从 results/ 的 JSON 组装中文报告。

报告输出到 eval/检索质量测评报告.md（eval 根目录）。
数据来源：
    results/retrieval.json —— 检索质量与阈值（含逐条明细）
    results/latency.json   —— 延迟基准

可以单独重跑本脚本重新生成报告（不重跑测评）。
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
REPORT_PATH = HERE.parent / "检索质量测评报告.md"


def setup_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def load(name: str) -> dict:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def fmt_pct(v: float) -> str:
    return f"{v:.1%}"


def main() -> None:
    setup_console()

    retrieval = load("retrieval.json")
    latency = load("latency.json")

    summary = retrieval["summary"]
    constants = summary["constants"]
    metrics = summary["metrics"]
    dists = summary["distributions"]

    lines: list[str] = []
    lines.append("# 检索质量测评报告")
    lines.append("")
    lines.append(f"- 生成时间：{summary['ran_at']}（报告重生成时间：{datetime.datetime.now().astimezone().isoformat(timespec='seconds')}）")
    lines.append(f"- 语料：世界观.md（{summary['chunk_count']} 个分块，512 维，IndexFlatIP 余弦检索）")
    lines.append("- 嵌入模型：granite-embedding-311m-multilingual-r2（local-v1，CPU 推理）")
    lines.append(f"- 检索常量：MIN_SCORE={constants['MIN_SCORE']}，SCORE_GAP={constants['SCORE_GAP']}，MAX_CHUNKS={constants['MAX_CHUNKS']}")
    lines.append("- 运行方式：`.venv\\Scripts\\python.exe eval\\retrieval\\run_retrieval.py`（延迟测评先跑，冷加载才准）")
    lines.append("- 脚本只通过导入复用 rag 模块并加载与生产同一份索引缓存，不修改程序代码；CPU 推理与精确检索在同环境下可复现")
    lines.append("")

    #/ ============ 表 1：总览 ============
    lines.append("## 一、结果总览")
    lines.append("")
    lines.append("| 指标 | 结果 |")
    lines.append("| --- | --- |")
    lines.append(f"| 有答案查询 top1 分数分布 | {dists['正样本 top1 分数']['min']} ~ {dists['正样本 top1 分数']['max']}（均值 {dists['正样本 top1 分数']['mean']}） |")
    lines.append(f"| 普通负样本 top1 分数分布 | {dists['普通负样本 top1 分数']['min']} ~ {dists['普通负样本 top1 分数']['max']}（均值 {dists['普通负样本 top1 分数']['mean']}） |")
    lines.append(f"| 有答案查询阈值通过率 | {fmt_pct(metrics['正样本阈值通过率'])}（{summary['counts']['positive']} 条全过 {constants['MIN_SCORE']}） |")
    lines.append(f"| 普通负样本拦截率 | {fmt_pct(metrics['普通负样本拦截率'])}（{summary['counts']['negative']} 条全拦） |")
    lines.append(f"| top1 命中预期章节 | {fmt_pct(metrics['正样本 top1 命中率'])} |")
    lines.append(f"| 注入集合覆盖预期章节 | {fmt_pct(metrics['正样本注入覆盖率'])} |")
    lines.append(f"| 边界负样本拦截率 | {fmt_pct(metrics['边界负样本拦截率'])}（{summary['counts']['hard_negative']} 条中 3 条穿透） |")
    lines.append(f"| 热检索延迟 P50 / P90 | {latency['warm_full_ms']['p50']} / {latency['warm_full_ms']['p90']} ms |")
    lines.append(f"| 进程首次加载嵌入模型 | {latency['cold_load_s']} s（启动预加载一次性承担） |")
    lines.append("")
    lines.append("样本构成：14 条有答案正样本（覆盖世界观 8 个章节、逐条人工标注预期命中章节）+ 12 条普通负样本 + 4 条边界负样本（词汇与设定重叠的对抗样本，如「在家养猫需要注意什么」）。")
    lines.append("")
    lines.append("> 术语说明：**top1** 指单次检索里相似度最高的分块；**P50 / P90** 为百分位数（50% / 90% 的样本不超过该值）；min / max 为最小 / 最大值。")
    lines.append("")

    #/ ============ 表 2：阈值扫描 ============
    scan = retrieval["threshold_scan"]
    thresholds = [s["threshold"] for s in scan]
    lines.append("## 二、阈值扫描（MIN_SCORE 候选值对比）")
    lines.append("")
    header = "| 指标 | " + " | ".join(
        f"**{t:.2f}**" if t == constants["MIN_SCORE"] else f"{t:.2f}"
        for t in thresholds
    ) + " |"
    lines.append(header)
    lines.append("| --- | " + " | ".join(["---"] * len(thresholds)) + " |")
    lines.append("| 正样本通过率 | " + " | ".join(fmt_pct(s["pos_pass_rate"]) for s in scan) + " |")
    lines.append("| 普通负样本拦截率 | " + " | ".join(fmt_pct(s["neg_block_rate"]) for s in scan) + " |")
    lines.append("| 边界负样本拦截率 | " + " | ".join(fmt_pct(s["hard_block_rate"]) for s in scan) + " |")
    lines.append("| 总体准确率 | " + " | ".join(fmt_pct(s["accuracy"]) for s in scan) + " |")
    lines.append("")
    pos_min = dists["正样本 top1 分数"]["min"]
    neg_max = dists["普通负样本 top1 分数"]["max"]
    lines.append(f"**0.85 的依据**：正样本最低分 {pos_min} 与普通负样本最高分 {neg_max} 之间仅有 {round(pos_min - neg_max, 4)} 的间隔，0.85 恰好落在正负样本全分隔的最低交界上。样本内 0.86 总体准确率更高（93.3%），但差距仅由 1 条边界样本翻转决定（无统计意义），且对正样本最低分的余量只剩 0.0045——上一次语料修订使该间隔从 0.054 收窄到 0.021，阈值余量应预留语料漂移空间，故仍取 0.85。")
    lines.append("")

    #/ ============ 表 3：SCORE_GAP 扫描 ============
    gap_scan = retrieval["score_gap_scan"]
    gaps = [g["gap"] for g in gap_scan]
    lines.append("## 三、SCORE_GAP 扫描（近邻扩展窗口，MAX_CHUNKS=6 截断下）")
    lines.append("")
    header = "| 指标 | " + " | ".join(
        f"**{g:.2f}**" if g == constants["SCORE_GAP"] else f"{g:.2f}"
        for g in gaps
    ) + " |"
    lines.append(header)
    lines.append("| --- | " + " | ".join(["---"] * len(gaps)) + " |")
    lines.append("| 注入覆盖率 | " + " | ".join(fmt_pct(g["coverage"]) for g in gap_scan) + " |")
    lines.append("| 注入标题数（均值） | " + " | ".join(f"{g['avg_titles']:.2f}" for g in gap_scan) + " |")
    lines.append("| 注入标题数（P90 / 最大） | " + " | ".join(f"{g['p90_titles']:.1f} / {g['max_titles']}" for g in gap_scan) + " |")
    lines.append("")
    lines.append("**0.03 的依据**：覆盖率在 0.02 处饱和（top1 命中率 78.6% 的 3 条查询，其预期章节与 top1 的分差恰好落在 (0.01, 0.02]），继续扩大只线性增加注入量；0.02 是临界观测值、零容错，0.03 = 临界值 + 0.01 余量，均值注入 2.57 个标题；≥0.05 后 P90 顶满 MAX_CHUNKS=6，纯属浪费。误注入代价随窗口变宽上升：穿透阈值的边界负样本在 SCORE_GAP=0.03 下各注入 6、6、1 个标题。")
    lines.append("")

    #/ ============ 表 4：延迟 ============
    w = latency["warm_full_ms"]
    e = latency["encode_ms"]
    s = latency["search_ms"]
    o = latency["other_overhead_ms"]
    lines.append("## 四、检索延迟（热状态，30 条查询）")
    lines.append("")
    lines.append("| 指标 | P50 | P90 | 最大值 |")
    lines.append("| --- | --- | --- | --- |")
    lines.append(f"| `search_worldview` 全程 | {w['p50']} ms | {w['p90']} ms | {w['max']} ms |")
    lines.append(f"| 其中：查询编码 | {e['p50']} ms | {e['p90']} ms | {e['max']} ms |")
    lines.append(f"| 其中：FAISS 检索 | {s['p50']} ms | {s['p90']} ms | {s['max']} ms |")
    lines.append(f"| 其中：文件读写 / 哈希校验 / 拼装 | {o['p50']} ms | {o['p90']} ms | {o['max']} ms |")
    lines.append("")
    lines.append(f"延迟大头是查询编码（约 2/3）；FAISS 在 {summary['chunk_count']} 块规模下不足 0.1 ms——该架构的检索瓶颈永远在嵌入模型而非索引，扩语料的优化方向是换小模型或批量编码。进程首次加载嵌入模型实测 {latency['cold_load_s']} s（含 transformers / torch 懒加载链），由启动阶段预加载一次性承担，不进对话路径。")
    lines.append("")

    #/ ============ 表 5：正样本明细 ============
    lines.append("## 五、有答案查询逐条明细（正样本）")
    lines.append("")
    lines.append("| # | 查询 | top1 分数 | top1 命中章节 | top1 命中 | top3 命中 | 预期在注入集 | 达标块数 | 注入标题数 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for i, r in enumerate(retrieval["positives"], 1):
        lines.append(
            f"| {i} | {r['query']} | {r['top1_score']:.4f} "
            f"| {r['top1_title']} | {'✓' if r['hit_top1'] else '✗'} "
            f"| {'✓' if r['hit_top3'] else '✗'} "
            f"| {'✓' if r['hit_injected'] else '✗'} "
            f"| {r['gap_chunk_count']} | {r['injected_title_count']} |"
        )
    lines.append("")
    lines.append("top1 未命中的 3 条（出生地 / 妈妈 / 武器）top1 均落在角色档案的相邻小节，其预期章节全部通过 SCORE_GAP 近邻扩展进入实际注入集合——这是近邻扩展机制价值的直接量化：单点精度不足由召回扩展兜底。")
    lines.append("")

    #/ ============ 表 6：负样本明细 ============
    lines.append("## 六、无答案查询逐条明细（负样本 / 边界样本）")
    lines.append("")
    lines.append("| 查询 | 类型 | top1 分数 | 最相似块 | 是否拦截 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for r in retrieval["negatives"] + retrieval["hard_negatives"]:
        kind = "普通" if r["kind"] == "negative" else "边界"
        lines.append(
            f"| {r['query']} | {kind} | {r['top1_score']:.4f} "
            f"| {r['top1_title']} | {'✓ 拦截' if r['blocked'] else '✗ 穿透'} |"
        )
    lines.append("")
    lines.append("穿透的 3 条边界样本 top1 全部落在语义近邻块（灵猫族毛色分支 / 月相段落 / 《养猫十诫》），是嵌入模型对「词汇重叠但语义不同」的天然局限。单阈值在对抗样本下不存在完美解（0.90 可全拦但正样本通过率跌到 57.1%），当前取舍偏向保召回：角色扮演场景下误注入的代价是多几段相关背景的输入长度，漏注入的代价是模型编造设定。")
    lines.append("")

    #/ ============ 局限 ============
    lines.append("## 七、局限与适用范围")
    lines.append("")
    lines.append("- 样本量 30 条、单角色语料，正负样本分布为人工构造而非线上流量；")
    lines.append("- 阈值与间隔绑定「这份语料 + 这个嵌入模型」的组合，任一变更都需重跑校准（上一次语料修订使正负间隔从 0.054 收窄至 0.021）；")
    lines.append("- 边界对抗样本下存在已知穿透（3/4），属于阈值取舍的既定代价而非未知缺陷。")
    lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"[输出] {REPORT_PATH}")


if __name__ == "__main__":
    main()
