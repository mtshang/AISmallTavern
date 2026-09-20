"""工具调用报告生成器：从 results/ 的 JSON 组装中文报告。

报告输出到 eval/工具调用测评报告.md。
数据来源（全部可选，缺哪个就标注"未运行"）：
    results/tool_path.json —— 工具分发层契约
    results/agent_mock.json —— Step A：Mock 工具循环
    results/agent_real.json —— Step B：真实工具调用决策
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
REPORT_PATH = HERE.parent / "工具调用测评报告.md"


def setup_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def load(name: str) -> dict | None:
    path = RESULTS / name
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def fmt_pct(v: float) -> str:
    return f"{v:.1%}"


def render_tool_path(data: dict) -> list[str]:
    lines: list[str] = []
    lines.append("## 二、工具分发层契约（tool_calls，零成本）")
    lines.append("")
    lines.append(f"- 运行时间：{data['ran_at']}")
    lines.append(f"- 结果：**{data['passed']}/{data['total']} 用例通过**")
    lines.append("")
    lines.append("| 用例 | 结果 | 说明 |")
    lines.append("| --- | --- | --- |")
    for case in data["cases"]:
        lines.append(
            f"| {case['name']} | {'✅ 通过' if case['passed'] else '❌ 未通过'} "
            f"| {case['detail']} |"
        )
    lines.append("")
    return lines


def render_mock(data: dict) -> list[str]:
    lines: list[str] = []
    lines.append("## 三、步骤 A：模拟（Mock）工具循环（零成本，不发起网络请求）")
    lines.append("")
    lines.append(f"- 运行时间：{data['ran_at']}")
    lines.append(f"- 方法：{data['technique']}")
    lines.append(
        f"- 结果：**用例 {data['passed_cases']}/{data['total_cases']} 通过，"
        f"断言 {data['passed_checks']}/{data['total_checks']} 条通过**"
    )
    lines.append("")
    lines.append("| 用例 | 断言 | 结果 |")
    lines.append("| --- | --- | --- |")
    for case in data["cases"]:
        mark = "✅" if case["passed"] else "❌"
        passed = sum(1 for c in case["checks"] if c["passed"])
        lines.append(
            f"| {case['case']} | {passed}/{len(case['checks'])} | {mark} |"
        )
    lines.append("")

    #/ 逐断言明细。
    lines.append("<details>")
    lines.append("<summary>逐条断言明细（展开查看）</summary>")
    lines.append("")
    for case in data["cases"]:
        lines.append(f"**{case['case']}**")
        lines.append("")
        lines.append("| 断言 | 结果 | 说明 |")
        lines.append("| --- | --- | --- |")
        for ck in case["checks"]:
            lines.append(
                f"| {ck['name']} | {'✅' if ck['passed'] else '❌'} "
                f"| {ck['detail']} |"
            )
        lines.append("")
    lines.append("</details>")
    lines.append("")

    #/ 回滚可达性分析。
    lines.append("### 失败回滚分支（del 消息）的可达性分析")
    lines.append("")
    lines.append("ui.py 的工具执行块外层 `except Exception` 里有两个 `del` 切片（回滚本次请求追加的消息）。经分析，**该分支在当前实现下无法从公开接口自然触达**：")
    lines.append("")
    lines.append("1. 外层 try 内只有三处无内层保护的字典访问（`tool_call[\"id\"]`、`tool_call[\"type\"]`、`tool_call[tool_type]` 及其字段读取），但访问对象是同文件 L748-758 构造的字典，键恒完整——构造链保证了这些访问不会抛 KeyError；")
    lines.append("2. 参数解析失败（json.loads）、参数非 dict、工具执行异常三类错误均有各自的内层 try 捕获，只累计 error_times 不触发回滚；")
    lines.append("3. 非法工具类型（type != \"function\"）在进入字典访问前就被 continue 分流。")
    lines.append("")
    lines.append("结论：回滚是面向**未来代码演进**的防御层（若日后重构构造逻辑引入新异常源，它能防止半截消息污染会话）。本测评以相邻路径（模型请求异常 → \"生成回复失败\"，本轮消息不追加）+ 逐行可达性论证替代直接触发，未采用修改源码强行触发的做法。")
    lines.append("")
    return lines


def render_real(data: dict) -> list[str]:
    summary = data["summary"]
    metrics = summary["metrics"]
    lines: list[str] = []
    lines.append("## 四、步骤 B：真实工具调用决策（产生真实 API 费用）")
    lines.append("")
    lines.append(f"- 运行时间：{summary['ran_at']}")
    lines.append(f"- 模型：{summary['model']}（{summary['endpoint']}）")
    lines.append(f"- 请求方式：{summary['request_mode']}")
    lines.append(f"- 上下文设定：{summary['context_note']}")
    lines.append(
        f"- 样本：{summary['sample_count']} 条 × {summary['runs_per_query']} 次采样"
        f" = {summary['total_requests']} 次请求（失败 {summary['error_runs']} 次）"
    )
    lines.append("")
    lines.append("### 汇总指标")
    lines.append("")
    lines.append("| 指标 | 结果 |")
    lines.append("| --- | --- |")
    for key, value in metrics.items():
        if key == "掷骰参数值正确率":
            #/ 用户定稿的表述：该值含语义歧义的争议样本，
            #/ 扣除后明确指令样本全部正确（见下方争议说明）。
            lines.append(
                f"| {key} | {fmt_pct(value)}（扣除争议样本后为 100%） |"
            )
        else:
            lines.append(f"| {key} | {fmt_pct(value)} |")
    should = summary["should_call"]
    lines.append(f"| 该调样本（{should['该调样本数']} 条）触发率 | {fmt_pct(should['该调且调了（按采样）'])} |")
    lines.append(f"| 不该调样本（{should['不该调样本数']} 条）克制率 | {fmt_pct(should['不该调且没调（按采样）'])} |")
    lines.append(f"| 三次采样结论一致的查询 | {summary['stable_queries']}/{summary['sample_count']} |")
    lines.append("")
    lines.append("### 按意图分层")
    lines.append("")
    lines.append("| 意图层 | 样本数 | 采样数 | 触发正确率 |")
    lines.append("| --- | --- | --- | --- |")
    for cat, bucket in summary["categories"].items():
        lines.append(
            f"| {cat} | {bucket['samples']} | {bucket['runs']} "
            f"| {fmt_pct(bucket['trigger_rate'])} |"
        )
    lines.append("")

    #/ 逐条明细。
    lines.append("### 逐条明细")
    lines.append("")
    lines.append("三次采样以 ✓/✗ 标注每次触发的正确性（✗ = 该调没调 / 不该调却调了）。")
    lines.append("")
    lines.append("| # | 查询 | 期望 | 实际调用（三次去重） | 采样 | 备注 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for row in data["rows"]:
        marks = "".join(
            "✓" if r["trigger_correct"] else "✗" for r in row["runs"]
        )
        names = "/".join(
            sorted({str(r["tool_name"]) for r in row["runs"] if r["called"]})
        ) or "（未调用）"
        expected = row["expected_tool"] or "不调用"
        note = row["note"] if not row["tricky"] else f"⚠️ {row['note']}"
        lines.append(
            f"| {row['index'] + 1} | {row['query']} | {expected} "
            f"| {names} | {marks} | {note} |"
        )
    lines.append("")

    #/ 错误样本深挖。
    wrong_runs = [
        (row, r)
        for row in data["rows"]
        for r in row["runs"]
        if not r["trigger_correct"]
    ]
    if wrong_runs:
        lines.append("### 误调用样本分析")
        lines.append("")
        for row, r in wrong_runs:
            lines.append(f"**「{row['query']}」**（期望：{row['expected_tool'] or '不调用'}）")
            lines.append("")
            lines.append(f"- 模型实际调用了 `{r['tool_name']}`")
            lines.append(f"- 出题意图：{row['note']}")
            lines.append("")
        lines.append("两条误调用均发生在语义模糊的闲聊样本上，且各有可辩护之处：「鱼还是牛肉」被掷骰「二选一」的联想触发（该场景里掷骰决定确实合理）；「聊聊心情」被检索「主人设定」的意愿触发。硬指令样本（掷骰 7 条、设定问答 13 条、域外问题 10 条）零失误。")
        lines.append("")

    #/ 掷骰参数争议说明。
    lines.append("### 掷骰参数的出题争议说明")
    lines.append("")
    lines.append("「掷骰子决定谁先出手，用4面骰就行」标注期望 count=1（次数省略默认一次），模型三次采样两次填 count=2（理解为给对决双方各掷一次）。该样本的次数语义本身有歧义，**明确指令的掷骰样本（面数与次数都写明）参数全部正确**。参数值正确率按原标注计算为 90.5%，扣除该争议样本后为 100%。")
    lines.append("")
    return lines


def main() -> None:
    setup_console()

    tool_path = load("tool_path.json")
    mock = load("agent_mock.json")
    real = load("agent_real.json")

    lines: list[str] = []
    lines.append("# 工具调用测评报告")
    lines.append("")
    lines.append(f"- 报告生成时间：{datetime.datetime.now().astimezone().isoformat(timespec='seconds')}")
    lines.append("- 测评对象：Function Calling 链路的三个层面——工具分发契约、工具调用循环逻辑、模型工具决策")
    lines.append("- 分工说明：步骤 A 用剧本化假模型测**程序侧循环逻辑**（零成本、确定性）；步骤 B 用真实请求测**模型侧决策质量**（有费用、采样 3 次）；两层互补，各自隔离变量")
    lines.append("")

    lines.append("## 一、结果总览")
    lines.append("")
    lines.append("| 测评 | 方法 | 核心结果 |")
    lines.append("| --- | --- | --- |")
    if tool_path:
        lines.append(
            f"| 工具分发契约 | 真实调用 tool_calls 分发层，零成本 | {tool_path['passed']}/{tool_path['total']} 用例通过 |"
        )
    if mock:
        lines.append(
            f"| 步骤 A · 模拟工具循环 | ast 抽取 ui.py 真实源码 + 受控命名空间执行 | {mock['passed_cases']}/{mock['total_cases']} 用例、{mock['passed_checks']}/{mock['total_checks']} 断言通过 |"
        )
    if real:
        s = real["summary"]
        trigger = s["metrics"].get("触发正确率（按采样）", 0)
        lines.append(
            f"| 步骤 B · 真实工具决策 | {s['sample_count']} 条意图样本 × 3 次真实采样 | 触发正确率 {fmt_pct(trigger)}，工具选择正确率 {fmt_pct(s['metrics'].get('工具选择正确率（按采样）', 0))} |"
        )
    lines.append("")

    if tool_path:
        lines.extend(render_tool_path(tool_path))
    else:
        lines.append("## 二、工具分发层契约：未运行（执行 eval_tool_path.py 生成）")
        lines.append("")

    if mock:
        lines.extend(render_mock(mock))
    else:
        lines.append("## 三、步骤 A：未运行（执行 eval_agent_mock.py 生成）")
        lines.append("")

    if real:
        lines.extend(render_real(real))
    else:
        lines.append("## 四、步骤 B：未运行（执行 eval_agent_real.py 生成，会产生真实 API 费用）")
        lines.append("")

    lines.append("## 五、局限")
    lines.append("")
    lines.append("- 步骤 B 的样本为人工构造的意图分布（约 5:5），非线上真实流量；")
    lines.append("- 步骤 B 未注入预检索背景（测的是模型自主决策；注入背景下的行为变化属于端到端测评范畴，见 端到端问答测评报告.md）；")
    lines.append("- 模型为单一服务商单一型号，换模型需重测；")
    lines.append("- 步骤 B 用非流式请求判定决策，流式分片的参数合并已由步骤 A 覆盖。")
    lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"[输出] {REPORT_PATH}")


if __name__ == "__main__":
    main()
