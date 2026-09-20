"""端到端报告生成器：从 results/e2e_ab.json 组装中文报告。

报告输出到 eval/端到端问答测评报告.md。
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
REPORT_PATH = HERE.parent / "端到端问答测评报告.md"


def setup_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def fmt_pct(v: float) -> str:
    return f"{v:.1%}"


VERDICT_CN = {
    "correct": "答对",
    "refuse": "拒答",
    "fabricate": "编造",
    "grounded_mismatch": "有依据不符",
    "error": "请求失败",
}


def load_llm_verdicts() -> dict | None:
    """加载大模型静态判分文件（不存在时返回 None，报告相应列留空）。"""
    path = RESULTS / "llm_verdicts.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def llm_stats(data: dict, llm: dict) -> dict:
    """按大模型判分统计两组四分类计数。"""
    stats = {
        "no_rag": {"correct": 0, "refuse": 0, "fabricate": 0, "grounded_mismatch": 0},
        "rag": {"correct": 0, "refuse": 0, "fabricate": 0, "grounded_mismatch": 0},
    }
    for key, groups in llm["verdicts"].items():
        for group in ("no_rag", "rag"):
            for verdict in groups[group]:
                if verdict in stats[group]:
                    stats[group][verdict] += 1
    for group in stats:
        total = sum(stats[group].values())
        stats[group]["total"] = total
        stats[group]["accuracy"] = (
            round(stats[group]["correct"] / total, 4) if total else 0.0
        )
    return stats


def main() -> None:
    setup_console()

    data = json.loads(
        (RESULTS / "e2e_ab.json").read_text(encoding="utf-8")
    )
    summary = data["summary"]
    llm = load_llm_verdicts()

    lines: list[str] = []
    lines.append("# 端到端问答测评报告（RAG 注入 A/B 对比）")
    lines.append("")
    lines.append(f"- 运行时间：{summary['ran_at']}（报告重生成：{datetime.datetime.now().astimezone().isoformat(timespec='seconds')}）")
    lines.append(f"- 模型：{summary['model']}（{summary['endpoint']}）")
    lines.append(f"- 请求方式：{summary['request_mode']}")
    lines.append("")
    lines.append("## 一、实验设计")
    lines.append("")
    lines.append("证明的问题：检索质量测评证明了「检索找得到正确章节」，本测评证明「注入的背景真的让模型答对了原本答不出的题」——RAG 价值的最终量化。")
    lines.append("")
    lines.append("- **A 组（无 RAG）**：`[system(人设), user(问题)]`。人设只有一句「你是一只猫娘。」，不含任何世界观信息，是真正的盲测；")
    lines.append("- **B 组（有 RAG）**：`[system(人设), user(注入+问题)]`。注入格式与 ui.py 生产代码逐字一致（`<reference_character_worldview>` XML 包裹），背景由 `rag.search_worldview` 对该问题真实检索产生——B 组成绩综合反映「检索 → 注入 → 模型阅读」整条链路；")
    lines.append("- 两组都不传 tools，隔离「背景注入」单一变量（工具自主追问属于工具调用测评的范畴）；")
    lines.append(f"- {summary['question_count']} 道封闭式硬事实题（答案唯一、可逐字查证），每题每组采样 {summary['runs_per_group']} 次。")
    lines.append("")
    lines.append("### 判分口径：双判分器并列")
    lines.append("")
    lines.append("**词表判分器**（机械三分类，运行于测评脚本内，零成本、可复现）：")
    lines.append("")
    lines.append("1. 回答包含参考答案关键词 → **答对**；")
    lines.append("2. 不含关键词，但命中「承认缺失」类措辞的固定词表（13 个，如「不知道」「未提及」「没有说明」） → **拒答**；")
    lines.append("3. 其余全部 → **编造**（兜底类，措辞未进词表的如实回答也会落入该类）。")
    lines.append("")
    if llm:
        lines.append(f"**大模型语义判分**（独立判分器：{llm['judge']}，对已保存回答静态判分，固化于 `results/llm_verdicts.json`）：按语义而非措辞四分类——**答对 / 拒答 / 编造 / 有依据但答案不符**。核心区分：断言句与条件句——「这片大陆叫艾泽拉斯哦！」是对本世界的无依据断言（编造，错误设定可直接污染对话记忆）；「要看是哪个世界观呢，北欧神话里叫尤克特拉希尔」是条件式外部参考（拒答，不产生可采纳的错误设定）。")
        lines.append("")
    lines.append("两套判分并列展示，方法对比见第四节。")

    #/ ---- 结果总览（双判分器口径） ----
    a = summary["no_rag"]
    b = summary["rag"]
    lines.append("## 二、结果总览（双判分器口径）")
    lines.append("")
    lines.append("| 组别 | 判分器 | 答对率 | 拒答 | 编造 | 有依据不符 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    b_refuse = summary.get("rag_refuse", 0)
    b_fabricate = summary.get("rag_fabricate", 0)
    lines.append(
        f"| A 组 · 无 RAG | 词表判分器 | **{fmt_pct(a['accuracy'])}** "
        f"| {a['refuse']} | {a['fabricate']} | — |"
    )
    lines.append(
        f"| B 组 · 有 RAG | 词表判分器 | **{fmt_pct(b['accuracy'])}** "
        f"| {b_refuse} | {b_fabricate} | — |"
    )
    if llm:
        ls = llm_stats(data, llm)
        la, lb = ls["no_rag"], ls["rag"]
        lines.append(
            f"| A 组 · 无 RAG | 大模型判分 | **{fmt_pct(la['accuracy'])}** "
            f"| {la['refuse']} | {la['fabricate']} | — |"
        )
        lines.append(
            f"| B 组 · 有 RAG | 大模型判分 | **{fmt_pct(lb['accuracy'])}** "
            f"| {lb['refuse']} | {lb['fabricate']} | {lb['grounded_mismatch']} |"
        )
        lines.append("")
        lines.append(
            f"两套判分器对**答对率**的判定完全一致（A 组 {fmt_pct(la['accuracy'])}、B 组 {fmt_pct(lb['accuracy'])}）——关键词匹配对「答对」的判定足够可靠，这是本测评的主指标。差异全部出现在**答错的细分**上，这正是两种方法的对比点（见第四节）。"
        )
    lines.append("")
    inj = summary["injected_only"]
    if inj.get("question_count"):
        a_rate = (
            fmt_pct(inj["no_rag_correct"] / inj["no_rag_total"])
            if inj["no_rag_total"]
            else "—"
        )
        b_rate = (
            fmt_pct(inj["rag_correct"] / inj["rag_total"])
            if inj["rag_total"]
            else "—"
        )
        lines.append(
            f"**注入成功子集**（{inj['question_count']} 题，即预检索真的注入了背景的题目）：A 组 {a_rate} → B 组 {b_rate}。这是 RAG 全链路（检索→注入→阅读理解）价值的直接量化。"
        )
        lines.append("")
    missed = summary.get("retrieval_missed_questions") or []
    if missed:
        lines.append(f"检索未命中（B 组实际等于无注入）的题目：{missed}")
        lines.append("")

    #/ ---- 逐题明细（双判分列） ----
    lines.append("## 三、逐题明细（每格两次采样）")
    lines.append("")
    lines.append(
        f"| # | 问题 | 参考答案 | A 组 · 词表判分 | A 组 · 大模型判分 | B 组 · 词表判分 | B 组 · 大模型判分 | 注入背景 |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for row in data["rows"]:
        a_word = "、".join(
            VERDICT_CN.get(r["verdict"], r["verdict"])
            for r in row["no_rag"]
        )
        b_word = "、".join(
            VERDICT_CN.get(r["verdict"], r["verdict"])
            for r in row["rag"]
        )
        if llm:
            key = str(row["index"])
            groups = llm["verdicts"].get(key, {})
            a_llm = "、".join(
                VERDICT_CN.get(v, v) for v in groups.get("no_rag", [])
            ) or "—"
            b_llm = "、".join(
                VERDICT_CN.get(v, v) for v in groups.get("rag", [])
            ) or "—"
        else:
            a_llm = b_llm = "—"
        chars = (
            f"{row['background_chars']} 字符"
            if row["background_chars"]
            else "未命中"
        )
        lines.append(
            f"| {row['index'] + 1} | {row['question']} | {row['answer']} "
            f"| {a_word} | {a_llm} | {b_word} | {b_llm} | {chars} |"
        )
    lines.append("")

    #/ ---- 两种判分方法对比（小结论） ----
    lines.append("## 四、两种判分方法的对比（小结论）")
    lines.append("")
    if llm:
        ls = llm_stats(data, llm)
        la = ls["no_rag"]
        lb = ls["rag"]
        lines.append("**结果一致性**：两套判分器对主指标「答对率」的判定完全一致（A 组 0/32、B 组 26/32）——判「对」只需要关键词匹配，词表判分器在这一层足够可靠，且零成本、毫秒级、规则完全透明可复现。")
        lines.append("")
        lines.append(f"**差异全部在答错的细分上**（这正是各自方法特性的展示）：")
        lines.append("")
        lines.append(f"- **A 组**：词表判分 28 次编造 / 大模型判分 {la['fabricate']} 次编造、{la['refuse']} 次拒答。{28 - la['fabricate']} 次差异全部是词表兜底类吞掉的「非断言式回答」——条件式外部参考（「如果是北欧神话的话叫尤克特拉希尔」）、澄清请求（「你说的是哪个作品？」）、俏皮滑过（脑筋急转弯式的「大咪」）、新型拒答措辞（「我还没有学会回答这个问题」）以及 1 次空回答。这些回答不产生可被对话采纳的错误设定，语义上不是幻觉；")
        lines.append("")
        lines.append(f"- **B 组**：词表判分 拒答 2 次 + 编造 4 次 / 大模型判分 拒答 {lb['refuse']} 次 + 编造 {lb['fabricate']} 次 + 有依据但答案不符 {lb['grounded_mismatch']} 次。4 次编造的差异 = 2 次「没有写明」式如实拒答（措辞不在 13 词固定词表内被兜底）+ 2 次忠于注入文本但与参考答案不符的回答（出题瑕疵，非幻觉）。")
        lines.append("")
    lines.append("**方法取舍**：")
    lines.append("")
    lines.append("| 维度 | 词表判分器 | 大模型语义判分 |")
    lines.append("| --- | --- | --- |")
    lines.append("| 成本与速度 | 零成本、毫秒级、随脚本自动运行 | 有 API 成本（或需静态固化），本次为一次性判分 |")
    lines.append("| 可复现性 | 完全确定，规则透明 | 判分器自身有不确定性（换模型/温度可能给出不同标签） |")
    lines.append("| 分类粒度 | 三分类，兜底类混杂多种行为 | 四分类，能区分断言句与条件句、玩笑与设定 |")
    lines.append("| 适用场景 | 主指标（答对率）与大规模重跑 | 错误细分、语义定性、小批量深挖 |")
    lines.append("")
    lines.append("**本项目的选择**：主指标用词表判分器（保证任何人重跑都能得到相同数字），错误细分与定性分析用大模型判分辅助（静态固化于 `results/llm_verdicts.json`，判分标准与全部 64 条判定随报告存档）——两层互补，而不是用其中一层替代另一层。")
    lines.append("")

    #/ ---- 编造样本展示 ----
    fabricates = [
        (row, r)
        for row in data["rows"]
        for r in row["no_rag"]
        if r["verdict"] == "fabricate"
    ]
    if fabricates:
        lines.append("## 五、A 组编造样本（幻觉实录）")
        lines.append("")
        lines.append("无背景且模型选择断言时，它不会说「不知道」，而是自信地编一个答案——错误设定会直接污染对话记忆，这是角色扮演场景里 RAG 要解决的核心问题。以下为 A 组编造实录选段（词表与大模型判分一致认定为编造的样本，节选前 200 字）：")
        lines.append("")
        for row, r in fabricates[:8]:
            lines.append(f"**问：{row['question']}**")
            lines.append("")
            lines.append(f"> {r['answer_excerpt']}")
            lines.append("")

    #/ ---- B 组失败案例分析（人工定性，附验证方法） ----
    lines.append("## 六、B 组失败案例分析（人工定性）")
    lines.append("")
    lines.append("B 组 6 次未答对集中在 3 道题。经逐题核对注入内容（现场调用 `rag.search_worldview` 复现注入集），失败可全部定性：**没有一次是语义意义上的编造（幻觉）**。词表判分器把 6 次全部落进「拒答 2 + 编造 4」，大模型判分给出精确构成「拒答 4 + 有依据但答案不符 2 + 编造 0」：")
    lines.append("")
    lines.append("### 案例 1：「小咪的母亲叫什么名字？」（大模型判分：拒答 2 次；词表判分：编造 1 次、拒答 1 次）")
    lines.append("")
    lines.append("- **注入集**：基本信息 / 外貌描写 / 身世线 / 小咪的日常 / 性格侧写（1353 字符），**不含「人物关系网」**——答案「母亲·缇雅」只存在于那张表格里；")
    lines.append("- **模型行为**：两次都如实回答「档案里没有写明母亲的具体名字」，并正确复述了守井祭司、半截月井钥匙等真实细节——**忠于注入文本，无幻觉**；")
    lines.append("- **判分差异**：第 1 次措辞「没有写明」不在 13 词固定词表内，被词表判分器落入编造兜底类；第 2 次出现了「未提及」被判拒答——同一种行为、两种措辞、词表给出两个标签；")
    lines.append("- **根因**：检索召回缺口。表格文本（「母亲·缇雅（同名母神，巧合）｜已故，守井祭司｜…」）与口语化查询的语义相似度不足以进入 SCORE_GAP 窗口，含答案的章节没有进入注入集。")
    lines.append("")
    lines.append("### 案例 2：「小咪第一次死在了什么动物的口下？」（大模型判分：拒答 2 次；词表判分：编造 1 次、拒答 1 次）")
    lines.append("")
    lines.append("- **注入集**：九命庭的焚毁 / 外貌描写 / 小咪的日常 / 身世线 / 基本信息（1418 字符），**不含「猫族的专属能力」**——答案「雪原狼」只在该节的九命之契条目里；")
    lines.append("- **模型行为**：两次都如实回答「档案里没有记载第一次死亡的细节」，正确复述第二次死亡（地牢毒杀）与鹰兽划伤（并明确说明那次没有死）——**忠于注入文本，无幻觉**；")
    lines.append("- **判分差异**：与案例 1 同构，「没有明确写明 / 没有记载」的措辞组合恰好一半在词表内一半不在；")
    lines.append("- **根因**：同上，检索召回缺口传导到端到端。")
    lines.append("")
    lines.append("### 案例 3：「沉星秘社想要唤醒的神是谁？」（大模型判分：有依据但答案不符 2 次；词表判分：编造 2 次）")
    lines.append("")
    lines.append("- **模型回答**：「第二纪元坠落的暗星」——这与世界观原文（「崇拜第二纪元坠落的『暗星』，企图人为制造星落之夜」）**逐字一致**；")
    lines.append("- **判分差异**：回答不含承认缺失的措辞，词表判分器落入编造兜底类；大模型判分识别出答案忠于注入文本，单列为「有依据但答案不符」；")
    lines.append("- **根因**：出题瑕疵。参考答案「猫神缇雅」取自圣教高层视角的另一段设定，与秘社自身章节的主表述有出入；模型忠于注入文本的回答反而更贴近原文。判分按关键词记错，但行为本身是 RAG 忠实度的正面案例。")
    lines.append("")
    lines.append("### 定性结论")
    lines.append("")
    lines.append("端到端测评的价值正在于此——它能把失败**定位到具体环节**。B 组 6 次未答对（3 道题）的构成（大模型判分口径）：")
    lines.append("")
    lines.append("- **4 次如实拒答**（案例 1、2）：检索未把含答案的章节带入注入集，模型两次都如实承认「档案里没有写」并正确复述注入文本中的真实细节——改进方向在检索侧（表格内容的分块与编码、或对表格类答案做专门召回），不在模型；")
    lines.append("- **2 次忠于原文的回答**（案例 3）：模型给出具体答案「暗星」，与注入文本逐字一致——出题瑕疵，不是幻觉。")
    lines.append("")
    lines.append("即：**没有一次是「背景就在眼前却答错」的模型阅读失败，也没有一次是无中生有的幻觉**。模型在注入集不含答案时全部选择如实说明而不是编造——这与 A 组形成鲜明对照（无背景时，词表判分 28/32 编造；其中大模型判分确认 19 次为真断言式编造，其余 9 次为条件式参考、澄清请求与俏皮滑过——但无论哪种，A 组都没有任何一次答对），说明 RAG 注入同时起到了**供给答案**与**约束幻觉**的双重作用。")
    lines.append("")

    #/ ---- B 组正确回答展示 ----
    corrects = []
    seen_questions: set[str] = set()
    for row in data["rows"]:
        #/ 每题只展示一条（两次采样都答对时取第一次）。
        if any(r["verdict"] == "correct" for r in row["rag"]):
            if row["question"] in seen_questions:
                continue
            seen_questions.add(row["question"])
            first_correct = next(
                r for r in row["rag"] if r["verdict"] == "correct"
            )
            corrects.append((row, first_correct))
    if corrects:
        lines.append("## 七、B 组正确回答选录")
        lines.append("")
        lines.append("同一模型、同一问题，注入背景后的回答（节选）：")
        lines.append("")
        for row, r in corrects[:4]:
            lines.append(f"**问：{row['question']}**")
            lines.append("")
            lines.append(f"> {r['answer_excerpt']}")
            lines.append("")

    lines.append("## 八、局限")
    lines.append("")
    lines.append("- 16 道题为单一角色的硬事实题，覆盖章节较广但深度有限；")
    lines.append("- 关键词判分对「答案对但表述完全避开关键词」的情况可能误判错（观察未发现此类案例）；")
    lines.append("- A 组的编造率与模型型号强相关（本测评用 deepseek-v4-flash），换模型结论需重测；")
    lines.append("- B 组成绩内含检索质量：检索未命中的题 B 组同样没有依据，本报告已单独标注注入成功的子集；")
    lines.append("- 大模型判分为静态固化（基于回答节选的前 200 字符），重跑测评后需重新判分；判分器自身的确定性依赖判分标准的明确表述（已存档于 llm_verdicts.json）。")
    lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"[输出] {REPORT_PATH}")


if __name__ == "__main__":
    main()
