"""Step A：Mock 工具循环测评（零成本，不发起任何网络请求）。

测什么：
    ui.py 中 stream_ai_reply() 的工具调用循环逻辑——生产代码里
    "模型流式响应 → 分片参数合并 → 工具执行 → 结果回填 → 循环/终止"
    的完整控制流。

怎么测（不改任何程序文件、不启动 TUI）：
    stream_ai_reply 是嵌套在 tavern_loop 里的函数，外部无法直接调用。
    本脚本在运行时用 ast 从 ui.py 真实源码中抽取该函数的定义片段，
    exec 到一个受控命名空间里：
        - append_output / app 换成假的（捕获输出文本，不碰终端）；
        - model_connect.chat_with_model 换成剧本化的假模型
          （按调用次序返回预设的流式分片，并捕获每次请求的消息快照）；
        - assets_tools_calls.tool_calls 换成假路由（避免加载嵌入模型）；
        - AppContext / session / UIState / 各标准库全部使用真实对象。
    因为函数体是从磁盘上的 ui.py 现场抽取的，测评对象与生产代码
    零漂移；ui.py 一旦改动，下次运行自动跟随。

断言目标（对应循环的四类行为）：
    1. 流式分片参数合并：跨分片的 arguments 拼接、多工具按 index 归并；
    2. 错误重试上限 4：参数解析连续失败 4 次后停止；
    3. 请求上限 11：工具循环最多发起 11 次模型请求；
    4. 失败回滚（del 消息）：见报告中的可达性分析——该分支为
       防御性代码，当前实现下无法从公开接口自然触发，本测评
       验证其相邻路径（模型异常时消息不追加）作为替代。

运行：在项目根目录执行
    .venv\\Scripts\\python.exe eval\\agent\\eval_agent_mock.py
"""

from __future__ import annotations

import ast
import asyncio
import copy
import datetime
import json
import textwrap
from pathlib import Path
from typing import Any, Callable

import agent_common as common  # noqa: E402  (同目录模块，先由下方 sys.path 生效)

#/ ---- 项目模块导入（agent_common 已把项目根加入 sys.path）----
import model_connect  # noqa: E402
import assets_tools_calls  # noqa: E402
import rag  # noqa: E402
import file_operate  # noqa: E402
from app_context import AppContext, get_current_time_iso  # noqa: E402
from ui import UIState  # noqa: E402


# ==================================================================
#/ 一、从 ui.py 真实源码抽取 stream_ai_reply
# ==================================================================

def extract_stream_ai_reply_source() -> str:
    """用 ast 定位 ui.py 中 stream_ai_reply 的定义，返回去缩进后的源码。"""
    ui_path = common.PROJECT_ROOT / "ui.py"
    source = ui_path.read_text(encoding="utf-8")

    tree = ast.parse(source)

    tavern_loop = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "tavern_loop"
    )

    fn_node = next(
        node
        for node in tavern_loop.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "stream_ai_reply"
    )

    segment = ast.get_source_segment(source, fn_node)
    if segment is None:
        raise RuntimeError("无法从 ui.py 抽取 stream_ai_reply 源码段。")

    return textwrap.dedent(segment)


# ==================================================================
#/ 二、假对象：流式分片、剧本模型、假工具路由、假 Application
# ==================================================================

class FakeFunction:
    """模拟 SDK 流式增量里的 function 对象。"""

    def __init__(self, name: str | None, arguments: str | None):
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    """模拟 SDK 流式增量里的 tool_call 对象（单个分片）。"""

    def __init__(
        self,
        index: int,
        call_id: str,
        name: str | None = None,
        arguments: str | None = None,
        call_type: str = "function",
    ):
        self.index = index
        self.id = call_id
        self.type = call_type
        self.function = FakeFunction(name, arguments)


def chunk(
    content: str | None = None,
    tool_calls: list | None = None,
) -> tuple[str | None, list | None]:
    """构造 model_connect.chat_with_model 单次 yield 的 (content, tool_calls)。"""
    return content, tool_calls


class ScriptedModel:
    """剧本化假模型：替换 model_connect.chat_with_model。

    responder(调用序号) 返回本次请求要吐出的分片列表；
    每次调用都会深拷贝当时的 messages 作为快照，供事后断言。
    responder 也可以直接抛异常，模拟模型请求失败。
    """

    def __init__(self, responder: Callable[[int], list]):
        self.responder = responder
        self.calls: list[dict] = []

    async def chat_with_model(
        self,
        appcontext: AppContext,
        messages: list[dict],
        tools: list[dict] | None = None,
    ):
        call_index = len(self.calls)
        #/ 深拷贝快照：生产代码会在原列表上继续 append / del，
        #/ 不拷贝的话所有快照都会指向同一个变化中的对象。
        self.calls.append(
            {
                "messages": copy.deepcopy(messages),
                "tools": copy.deepcopy(tools),
            }
        )

        pieces = self.responder(call_index)
        for content, tool_calls in pieces:
            yield content, tool_calls


class FakeToolRouter:
    """假工具路由：替换 assets_tools_calls.tool_calls。

    不加载嵌入模型，直接返回固定文本；同时记录每次收到的
    工具名和参数，供断言"参数 JSON 被正确解析后传给工具"。
    """

    def __init__(self, search_result: str = "（模拟）世界观检索结果：测试文本。"):
        self.search_result = search_result
        self.calls: list[dict] = []

    def tool_calls(self, appcontext: AppContext, name: str, **kwargs):
        self.calls.append({"name": name, "kwargs": dict(kwargs)})

        if name == "search_worldview":
            return self.search_result
        if name == "roll_dice":
            return "6面骰第1次投掷，点数为：3。"
        raise ValueError(f"未知工具：{name}")


class FakeApp:
    """只提供 invalidate() 的假 Application，供 finally 分支调用。"""

    def invalidate(self) -> None:
        pass


# ==================================================================
#/ 三、受控执行：exec 抽取的源码并运行一轮对话
# ==================================================================

def build_appcontext(session_messages: list[dict]) -> AppContext:
    """构造与生产等价的 AppContext（session_path=None 跳过写盘）。"""
    return AppContext(
        base_dir=common.PROJECT_ROOT,
        llm_api_key=None,
        llm_base_url=None,
        llm_model="mock-model",
        config={"session_id": "eval_mock_session.json"},
        config_env_error=None,
        embedding_model_dir=common.MODEL_DIR,
        character_path=common.CHARACTER_DIR / "人设.md",
        character_prompt="你是一只猫娘。",
        session={
            "title": "与mock的对话",
            "character_id": "默认猫娘default_cat",
            "created_at": "2026-01-01T00:00:00+08:00",
            "character_prompt": "你是一只猫娘。",
            "messages": session_messages,
        },
        session_character_dir=None,
        session_path=None,
        assets_tools=common.load_assets_tools(),
        llm_client=None,
    )


def run_stream_ai_reply(
    model: ScriptedModel,
    router: FakeToolRouter,
    user_text: str,
    function_source: str,
) -> dict:
    """在受控命名空间里执行真实 stream_ai_reply，返回观察结果。

    返回：{
        outputs:       append_output 捕获的全部文本（按序拼接），
        session_messages: 会话消息最终状态（深拷贝），
        model_calls:   假模型捕获的每次请求消息快照,
        tool_calls:    假路由收到的每次工具调用,
    }
    """
    appcontext = build_appcontext(
        [
            {
                "role": "system",
                "content": "你是一只猫娘。",
                "created_at": "2026-01-01T00:00:00+08:00",
            }
        ]
    )

    outputs: list[str] = []

    def append_output(text: str) -> None:
        outputs.append(text)

    namespace: dict[str, Any] = {
        "__name__": "ui_stream_ai_reply_under_test",
        #/ ---- 闭包变量的替身 ----
        "appcontext": appcontext,
        "append_output": append_output,
        "state": UIState(),
        "app": FakeApp(),
        #/ ---- 模块级依赖（chat_with_model / tool_calls 已被替换）----
        "model_connect": model_connect,
        "assets_tools_calls": assets_tools_calls,
        "rag": rag,
        "file_operate": file_operate,
        #/ ---- 标准库与工具函数 ----
        "asyncio": asyncio,
        "json": json,
        "get_current_time_iso": get_current_time_iso,
        "random": __import__("random"),
        "Path": Path,
    }

    original_chat = model_connect.chat_with_model
    original_tool = assets_tools_calls.tool_calls
    model_connect.chat_with_model = model.chat_with_model
    assets_tools_calls.tool_calls = router.tool_calls

    try:
        exec(
            compile(
                function_source,
                "<ui.py::stream_ai_reply>",
                "exec",
            ),
            namespace,
        )
        stream_ai_reply = namespace["stream_ai_reply"]
        asyncio.run(stream_ai_reply(user_text))
    finally:
        model_connect.chat_with_model = original_chat
        assets_tools_calls.tool_calls = original_tool

    return {
        "outputs": "".join(outputs),
        "session_messages": copy.deepcopy(
            appcontext.session["messages"]
        ),
        "model_calls": model.calls,
        "tool_calls": router.calls,
    }


# ==================================================================
#/ 四、测评用例
# ==================================================================

def check(name: str, passed: bool, detail: str) -> dict:
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name} —— {detail}")
    return {"name": name, "passed": passed, "detail": detail}


def case_happy_path(src: str) -> dict:
    """单工具调用全流程：分片合并 → 工具执行 → 回填 → 第二轮文本收尾。"""
    model = ScriptedModel(
        lambda i: (
            [
                #/ 第一轮：先吐一点正文，再分 3 片吐工具参数，
                #/ 最后再吐一点正文（模拟真实流的交错）。
                chunk("我查一下设定……"),
                chunk(
                    tool_calls=[
                        FakeToolCall(
                            0, "call_1",
                            name="search_worldview",
                            arguments='{"query_string":',
                        )
                    ]
                ),
                chunk(
                    tool_calls=[
                        FakeToolCall(
                            0, "call_1",
                            arguments=' "小咪是哪里出生的？"}',
                        )
                    ]
                ),
            ]
            if i == 0
            else [chunk("根据设定，小咪出生在九命庭。")]
        )
    )
    router = FakeToolRouter()

    result = run_stream_ai_reply(
        model, router, "小咪是哪里出生的？", src
    )

    checks = []
    calls = result["model_calls"]

    checks.append(check(
        "模型恰好请求 2 次（工具轮 + 收尾轮）",
        len(calls) == 2,
        f"实际 {len(calls)} 次",
    ))

    if len(calls) == 2:
        second = calls[1]["messages"]
        roles = [m["role"] for m in second]
        checks.append(check(
            "第二次请求的消息序列正确",
            roles == ["system", "user", "assistant", "tool"],
            " → ".join(roles),
        ))

        if "assistant" in roles:
            assistant = second[2]
            merged = assistant.get("tool_calls", [{}])[0].get(
                "function", {}
            )
            checks.append(check(
                "分片参数合并为完整 JSON",
                merged.get("arguments")
                == '{"query_string": "小咪是哪里出生的？"}',
                f"合并结果：{merged.get('arguments')!r}",
            ))
            checks.append(check(
                "工具名从首片正确保留",
                merged.get("name") == "search_worldview",
                f"工具名：{merged.get('name')}",
            ))

        if "tool" in roles:
            tool_msg = second[3]
            checks.append(check(
                "工具结果以 role=tool 回填",
                tool_msg.get("content") == router.search_result
                and tool_msg.get("tool_call_id") == "call_1",
                f"content 前 20 字：{str(tool_msg.get('content'))[:20]}",
            ))

    checks.append(check(
        "工具收到解析后的参数",
        result["tool_calls"] == [
            {
                "name": "search_worldview",
                "kwargs": {"query_string": "小咪是哪里出生的？"},
            }
        ],
        f"路由记录：{result['tool_calls']}",
    ))

    session_roles = [m["role"] for m in result["session_messages"]]
    checks.append(check(
        "会话最终为 system+user+assistant(工具)+tool+assistant(回答)",
        session_roles
        == ["system", "user", "assistant", "tool", "assistant"],
        " → ".join(session_roles),
    ))

    checks.append(check(
        "最终回答渲染到输出区",
        "根据设定，小咪出生在九命庭。" in result["outputs"],
        f"输出区长度 {len(result['outputs'])} 字符",
    ))

    return {
        "case": "happy_path（单工具全流程）",
        "checks": checks,
        "passed": all(c["passed"] for c in checks),
    }


def case_multi_tool_merge(src: str) -> dict:
    """同一请求内两个工具调用的分片按 index 正确归并。"""
    model = ScriptedModel(
        lambda i: (
            [
                chunk(
                    tool_calls=[
                        FakeToolCall(
                            0, "call_a",
                            name="search_worldview",
                            #/ 分片在字符串内部切开（真实流的行为），
                            #/ 拼接后才是合法 JSON。
                            arguments='{"query_string": "小咪的武',
                        )
                    ]
                ),
                chunk(
                    tool_calls=[
                        FakeToolCall(
                            1, "call_b",
                            name="roll_dice",
                            arguments='{"sides": 20,',
                        )
                    ]
                ),
                chunk(
                    tool_calls=[
                        FakeToolCall(
                            0, "call_a",
                            arguments='器是什么？"}',
                        )
                    ]
                ),
                chunk(
                    tool_calls=[
                        FakeToolCall(
                            1, "call_b",
                            arguments=' "count": 1}',
                        )
                    ]
                ),
            ]
            if i == 0
            else [chunk("两个结果都拿到了。")]
        )
    )
    router = FakeToolRouter()

    result = run_stream_ai_reply(
        model, router, "小咪的武器是什么？顺便掷个骰", src
    )

    checks = []
    calls = result["model_calls"]

    if len(calls) >= 2:
        assistant = calls[1]["messages"][2]
        tool_calls = assistant.get("tool_calls", [])

        args_by_index = {
            tc["id"]: tc["function"]["arguments"]
            for tc in tool_calls
        }
        checks.append(check(
            "两个工具调用都进入 assistant 消息",
            len(tool_calls) == 2,
            f"数量：{len(tool_calls)}",
        ))
        checks.append(check(
            "index 0 的参数跨分片合并正确",
            args_by_index.get("call_a")
            == '{"query_string": "小咪的武器是什么？"}',
            f"合并结果：{args_by_index.get('call_a')!r}",
        ))
        checks.append(check(
            "index 1 的参数跨分片合并正确",
            args_by_index.get("call_b") == '{"sides": 20, "count": 1}',
            f"合并结果：{args_by_index.get('call_b')!r}",
        ))

    tool_names = [c["name"] for c in result["tool_calls"]]
    checks.append(check(
        "两个工具都被执行且参数正确",
        tool_names == ["search_worldview", "roll_dice"]
        and result["tool_calls"][1]["kwargs"]
        == {"sides": 20, "count": 1},
        f"执行顺序：{tool_names}",
    ))

    if len(calls) >= 2:
        tool_messages = [
            m for m in calls[1]["messages"] if m["role"] == "tool"
        ]
        checks.append(check(
            "两条工具结果按序回填",
            len(tool_messages) == 2
            and tool_messages[0]["tool_call_id"] == "call_a"
            and tool_messages[1]["tool_call_id"] == "call_b",
            f"回填 {len(tool_messages)} 条",
        ))

    return {
        "case": "multi_tool_merge（多工具分片归并）",
        "checks": checks,
        "passed": all(c["passed"] for c in checks),
    }


def case_content_stream_merge(src: str) -> dict:
    """纯文本流式分片合并（不涉及工具）。"""
    model = ScriptedModel(
        lambda i: [
            chunk("喵，"),
            chunk("今天"),
            chunk("想聊点什么？"),
        ]
    )
    router = FakeToolRouter()

    result = run_stream_ai_reply(model, router, "你好", src)

    session = result["session_messages"]
    checks = [
        check(
            "文本分片合并为完整回复",
            len(session) == 3
            and session[2].get("content") == "喵，今天想聊点什么？",
            f"合并结果：{session[-1].get('content') if len(session) >= 3 else '（无 assistant）'}",
        ),
        check(
            "只请求 1 次模型",
            len(result["model_calls"]) == 1,
            f"实际 {len(result['model_calls'])} 次",
        ),
    ]

    return {
        "case": "content_stream_merge（文本分片合并）",
        "checks": checks,
        "passed": all(c["passed"] for c in checks),
    }


def case_error_limit_4(src: str) -> dict:
    """参数 JSON 连续解析失败：错误计数到 4 后停止。"""
    model = ScriptedModel(
        lambda i: [
            chunk(
                tool_calls=[
                    FakeToolCall(
                        0, f"call_bad_{i}",
                        name="search_worldview",
                        arguments='{"query_string": "小咪',  #/ 永远不完整
                    )
                ]
            )
        ]
    )
    router = FakeToolRouter()

    result = run_stream_ai_reply(
        model, router, "小咪的出生地是？", src
    )

    checks = [
        check(
            "模型请求恰好 4 次（错误上限）",
            len(result["model_calls"]) == 4,
            f"实际 {len(result['model_calls'])} 次",
        ),
        check(
            "输出包含停止提示",
            "上限" in result["outputs"],
            "已停止继续调用工具" if "上限" in result["outputs"]
            else "未出现提示",
        ),
        check(
            "工具从未被真正执行",
            result["tool_calls"] == [],
            f"执行记录：{result['tool_calls']}",
        ),
    ]

    #/ 会话里应保留 4 轮 assistant(带坏 tool_calls) + tool(失败消息)。
    session_roles = [m["role"] for m in result["session_messages"]]
    checks.append(check(
        "会话保留 4 轮失败记录（system+user+4×2）",
        session_roles.count("assistant") == 4
        and session_roles.count("tool") == 4,
        f"assistant×{session_roles.count('assistant')}，"
        f"tool×{session_roles.count('tool')}",
    ))

    return {
        "case": "error_limit_4（错误重试上限）",
        "checks": checks,
        "passed": all(c["passed"] for c in checks),
    }


def case_request_limit_11(src: str) -> dict:
    """工具持续成功时：模型请求达到 11 次上限后停止。"""
    model = ScriptedModel(
        lambda i: [
            chunk(
                tool_calls=[
                    FakeToolCall(
                        0, f"call_ok_{i}",
                        name="search_worldview",
                        arguments='{"query_string": "还有什么设定？"}',
                    )
                ]
            )
        ]
    )
    router = FakeToolRouter()

    result = run_stream_ai_reply(
        model, router, "把所有设定都查一遍", src
    )

    checks = [
        check(
            "模型请求恰好 11 次（请求上限）",
            len(result["model_calls"]) == 11,
            f"实际 {len(result['model_calls'])} 次",
        ),
        check(
            "输出包含停止提示",
            "上限" in result["outputs"],
            "已停止继续调用工具" if "上限" in result["outputs"]
            else "未出现提示",
        ),
        check(
            "工具执行 11 次（全部成功）",
            len(result["tool_calls"]) == 11,
            f"实际 {len(result['tool_calls'])} 次",
        ),
    ]

    session_roles = [m["role"] for m in result["session_messages"]]
    checks.append(check(
        "会话保留 11 轮完整记录",
        session_roles.count("assistant") == 11
        and session_roles.count("tool") == 11,
        f"assistant×{session_roles.count('assistant')}，"
        f"tool×{session_roles.count('tool')}",
    ))

    return {
        "case": "request_limit_11（请求次数上限）",
        "checks": checks,
        "passed": all(c["passed"] for c in checks),
    }


def case_empty_response(src: str) -> dict:
    """模型一轮什么都不返回：提示用户且不追加 assistant 消息。"""
    model = ScriptedModel(lambda i: [])
    router = FakeToolRouter()

    result = run_stream_ai_reply(model, router, "你好", src)

    session_roles = [m["role"] for m in result["session_messages"]]
    checks = [
        check(
            "输出包含『模型未返回有效回复』提示",
            "模型未返回有效回复" in result["outputs"],
            "已提示" if "模型未返回有效回复" in result["outputs"]
            else "未提示",
        ),
        check(
            "会话只有 system + user，无 assistant",
            session_roles == ["system", "user"],
            " → ".join(session_roles),
        ),
        check(
            "用户消息保留（可重新发起）",
            result["session_messages"][1]["content"] == "你好",
            "已保留",
        ),
    ]

    return {
        "case": "empty_response（空响应处理）",
        "checks": checks,
        "passed": all(c["passed"] for c in checks),
    }


def case_model_exception(src: str) -> dict:
    """模型请求本身抛异常：兜底提示且不追加本轮消息。"""
    def responder(i: int):
        raise RuntimeError("模拟网络故障")

    model = ScriptedModel(responder)
    router = FakeToolRouter()

    result = run_stream_ai_reply(model, router, "你好", src)

    session_roles = [m["role"] for m in result["session_messages"]]
    checks = [
        check(
            "输出包含『生成回复失败』兜底提示",
            "生成回复失败" in result["outputs"],
            "已提示" if "生成回复失败" in result["outputs"]
            else "未提示",
        ),
        check(
            "异常不追加半截消息（system + user）",
            session_roles == ["system", "user"],
            " → ".join(session_roles),
        ),
        check(
            "工具从未执行",
            result["tool_calls"] == [],
            "未执行",
        ),
    ]

    return {
        "case": "model_exception（模型异常兜底）",
        "checks": checks,
        "passed": all(c["passed"] for c in checks),
    }


# ==================================================================
#/ 五、入口
# ==================================================================

def run() -> dict:
    common.setup_console()

    print("=" * 62)
    print("测评四（Step A）：Mock 工具循环（ui.py stream_ai_reply）")
    print("=" * 62)

    source = extract_stream_ai_reply_source()
    print(f"[抽取] stream_ai_reply 源码 {len(source)} 字符（来自 ui.py 实时源码）")

    cases = [
        case_happy_path(source),
        case_multi_tool_merge(source),
        case_content_stream_merge(source),
        case_error_limit_4(source),
        case_request_limit_11(source),
        case_empty_response(source),
        case_model_exception(source),
    ]

    total_checks = sum(len(c["checks"]) for c in cases)
    passed_checks = sum(
        1 for c in cases for ck in c["checks"] if ck["passed"]
    )
    passed_cases = sum(1 for c in cases if c["passed"])

    print()
    print(
        f"[汇总] 用例 {passed_cases}/{len(cases)} 通过，"
        f"断言 {passed_checks}/{total_checks} 条通过"
    )

    summary = {
        "ran_at": datetime.datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "technique": (
            "ast 抽取 ui.py 中 stream_ai_reply 真实源码，"
            "exec 到受控命名空间（假模型/假路由/假输出），"
            "不修改程序文件、不启动终端界面（TUI）、零网络请求"
        ),
        "cases": [
            {
                "case": c["case"],
                "passed": c["passed"],
                "checks": c["checks"],
            }
            for c in cases
        ],
        "total_cases": len(cases),
        "passed_cases": passed_cases,
        "total_checks": total_checks,
        "passed_checks": passed_checks,
    }

    json_path = common.save_json("agent_mock.json", summary)
    print(f"[输出] {json_path}")
    print()

    return summary


if __name__ == "__main__":
    run()
