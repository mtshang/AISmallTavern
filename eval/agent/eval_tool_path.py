"""工具分发层接口契约测评。

对象是 assets_tools_calls.tool_calls()——模型工具调用在本地的落地入口。
测评不发起任何真实 LLM 请求，只验证分发层的四种行为契约：
    1. 正常查询：返回检索正文（非提示语）；
    2. 无结果查询：返回固定的"未找到"提示语；
    3. 知识库目录缺失（session_character_dir=None）：返回固定提示语；
    4. 未知工具名：抛 ValueError；
另附两个一致性检查：
    5. 与 rag.search_worldview 的透传一致性（同查询同结果）；
    6. roll_dice 参数透传（返回可读的投掷结果）。

运行：在项目根目录执行
    .venv\\Scripts\\python.exe eval\\agent\\eval_tool_path.py
"""

from __future__ import annotations

import dataclasses
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_common as common  # noqa: E402  (同目录公共设施)

#/ app_context 顶部 import 了 openai（AsyncOpenAI 类型注解用），
#/ .venv 中已安装，这里只承担 import 成本，不会发起网络请求。
from app_context import AppContext  # noqa: E402
from assets_tools_calls import tool_calls  # noqa: E402

import rag  # noqa: E402

#/ 用例取材（与检索样本集同款，硬编码避免跨目录依赖）：
#/ 正样本：世界观内问题；负样本：与设定无关的问题。
POSITIVE_QUERY = "小咪是哪里出生的？"
NEGATIVE_QUERY = "Python 的列表和元组有什么区别？"


def make_context(session_character_dir: Path | None) -> AppContext:
    """构造一个最小可用的 AppContext，只填工具分发层用到的字段。"""
    return AppContext(
        base_dir=common.PROJECT_ROOT,
        llm_api_key=None,
        llm_base_url=None,
        llm_model=None,
        config={},
        config_env_error=None,
        embedding_model_dir=common.MODEL_DIR,
        character_path=common.CHARACTER_DIR / "人设.md",
        character_prompt="(测评用占位人设)",
        session_character_dir=session_character_dir,
    )


def check(name: str, passed: bool, detail: str) -> dict:
    """打印一行用例结果并返回记录。"""
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name} —— {detail}")
    return {"name": name, "passed": passed, "detail": detail}


def run() -> dict:
    """执行工具分发层契约测评，返回汇总字典（供 run_all 聚合）。"""
    common.setup_console()

    print("=" * 62)
    print("测评三：工具分发层接口契约（tool_calls）")
    print("=" * 62)

    ctx = make_context(common.CHARACTER_DIR)
    ctx_without_kb = dataclasses.replace(
        ctx, session_character_dir=None
    )

    results: list[dict] = []

    #/ 用例 1：正样本查询应返回检索正文，而不是提示语。
    positive_query = POSITIVE_QUERY
    hit = tool_calls(
        ctx, "search_worldview", query_string=positive_query
    )
    results.append(check(
        "正样本返回检索正文",
        len(hit) > 100 and "未在知识库" not in hit,
        f"返回 {len(hit)} 字符",
    ))

    #/ 用例 2：离题最远的负样本应返回固定"未找到"提示语。
    negative_query = NEGATIVE_QUERY
    miss = tool_calls(
        ctx, "search_worldview", query_string=negative_query
    )
    results.append(check(
        "无结果返回固定提示语",
        miss == "未在知识库中找到与该问题相关的设定。",
        f"返回内容：{miss}",
    ))

    #/ 用例 3：知识库目录缺失时返回固定提示语，不抛异常。
    no_kb = tool_calls(
        ctx_without_kb, "search_worldview", query_string=positive_query
    )
    results.append(check(
        "目录缺失返回固定提示语",
        no_kb == "知识库目录未找到，无法检索世界观设定。",
        f"返回内容：{no_kb}",
    ))

    #/ 用例 4：未知工具名应抛 ValueError。
    try:
        tool_calls(ctx, "不存在的工具")
        unknown_error = False
        error_detail = "未抛出异常"
    except ValueError as error:
        unknown_error = True
        error_detail = str(error)
    results.append(check(
        "未知工具名抛 ValueError",
        unknown_error,
        error_detail,
    ))

    #/ 用例 5：与 rag.search_worldview 的透传一致性。
    direct = rag.search_worldview(
        common.MODEL_DIR, common.CHARACTER_DIR, positive_query
    )
    results.append(check(
        "与 rag.search_worldview 结果一致",
        hit == direct,
        f"透传结果与直接调用{'一致' if hit == direct else '不一致'}",
    ))

    #/ 用例 6：roll_dice 参数透传（2 次 6 面骰应输出两行结果）。
    dice = tool_calls(ctx, "roll_dice", sides=6, count=2)
    results.append(check(
        "roll_dice 参数透传",
        ("第1次" in dice) and ("第2次" in dice) and ("点数" in dice),
        dice.replace("\n", " / "),
    ))

    passed_count = sum(1 for r in results if r["passed"])
    summary = {
        "ran_at": datetime.datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "total": len(results),
        "passed": passed_count,
        "all_passed": passed_count == len(results),
        "cases": results,
    }

    print()
    print(f"[汇总] {passed_count}/{len(results)} 通过")

    json_path = common.save_json("tool_path.json", summary)
    print(f"[输出] {json_path}")
    print()

    return summary


if __name__ == "__main__":
    run()
