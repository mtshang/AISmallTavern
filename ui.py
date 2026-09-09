from __future__ import annotations

from typing import Any
import asyncio
import random
from dataclasses import dataclass
from pathlib import Path

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, ScrollOffsets, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.margins import ScrollbarMargin
from prompt_toolkit.styles import Style

import model_connect
import file_operate
from app_context import AppContext
from app_context import get_current_time_iso


@dataclass
class UIState:
    """
    保存一次终端全屏交互运行所需的状态数据。
    
    属性说明：
    - busy: 标记 AI 协程是否正在向 output_buffer 追加流式数据，用于阻断用户重复提交并修改状态栏。
    - notice: 存储一次性警告或系统临时提示，用户按键输入时会自动清空。
    - follow_output: 视口滚动锁定开关。
        * True: 输出区域自动滚动并追踪追加文本的最底部（自动吸附）。
        * False: 用户正在使用 PageUp/Down 查阅历史记录，禁止自动拉扯游标到底部。
    - exit_message: 退出全屏 TUI 模式后，向标准输出 stdout 打印的最终进程总结文本。
    """
    busy: bool = False
    notice: str = ""
    follow_output: bool = True
    exit_message: str = "你离开了 AI 小酒馆。"


async def tavern_loop(appcontext: AppContext) -> str:
    """
    AI 酒馆的主终端交互异步事件循环。
    
    返回：
        str: 退出应用时拟输出到标准输出终态的 exit_message。
    """
    state = UIState()

    credential_status = f"已配置（***{appcontext.llm_api_key[-3:]}）" if appcontext.llm_api_key else "未配置"
    endpoint_status = f"已配置（***{appcontext.llm_base_url.split('://')[-1]}）" if appcontext.llm_base_url else "未配置"

    welcome_text = (
        "欢迎使用 AI Small Tavern 。\n"
        f"模型：{appcontext.llm_model}\n"
        f"API 凭证：{credential_status}\n"
        f"API 地址：{endpoint_status}\n"
        "\n"
        "输入消息后按 Enter 提交。\n"
        "使用 PageUp / PageDown 浏览记录，Ctrl+Home / Ctrl+End 跳转。\n"
        "输入 /=exit ，或按 Ctrl+D 离开。\n"
    )
    initial_screen_text: str
    if appcontext.config_env_error is not None:
        initial_screen_text = welcome_text + (
            "\n"
            "环境变量配置出现错误："
            f"{appcontext.config_env_error}\n"
            "请修改项目根目录中的 .env，然后重新启动程序。\n"
        )
    else:
        history_display = ""
        if appcontext.session and "messages" in appcontext.session:
            for msg in appcontext.session["messages"]:
                role = msg.get("role")
                content = msg.get("content", "")
                if role == "user":
                    history_display += f"\n你：{content}\n"
                elif role == "assistant":
                    history_display += f"{appcontext.llm_model}：{content}\n"
            if history_display:
                history_display += "\n\n\n"
        initial_screen_text = history_display + welcome_text

    output_buffer = Buffer(
        document=Document(
            text=initial_screen_text,
            cursor_position=len(initial_screen_text),  
        ),
        read_only=True,
    )

    def clear_notice_when_editing(_: Buffer) -> None:
        """
        Buffer 文本变化事件回调（Event Handler）。
        
        参数说明：
            参数名 `_` 只是 Python 社区惯例，表示“协议要求接收，但函数体不使用”。
            `_` 仍然是完全正常的变量名，解释器不会赋予它特殊的忽略语义。
        """
        state.notice = ""

    input_buffer = Buffer(
        multiline=False,
        on_text_changed=clear_notice_when_editing,
    )

    output_control = BufferControl(
        buffer=output_buffer,
        focusable=False,
    )

    input_control = BufferControl(
        buffer=input_buffer,
    )

    output_window = Window(
        content=output_control,
        height=Dimension(min=1, weight=1),
        wrap_lines=True,
        always_hide_cursor=True,
        scroll_offsets=ScrollOffsets(top=1, bottom=1),
        right_margins=[
            ScrollbarMargin(display_arrows=True),
        ],
        style="class:output",
    )

    def get_header_text() -> list[tuple[str, str]]:
        """
        动态拉取当前配置的模型名称，并在顶部标题栏显示。
        
        这里每次读取的是已经加载到模块变量中的 LLM_MODEL；
        它不会在每一帧自动重新读取磁盘上的 `.env`。要重新加载配置，需要显式再次调用加载逻辑。
        """
        return [
            (
                "class:header",
                f" AI Small Tavern | 当前模型：{appcontext.llm_model} ",
            )
        ]

    def get_status_text() -> list[tuple[str, str]]:
        """
        根据 state 的当前状态生成状态栏文本的返回值列表
        按照 [state.notice -> state.busy -> else] 的优先级梯度降级判断展示文本。
        """
        if state.notice:
            return [
                (
                    "class:status.warning",
                    f" [提示] {state.notice} ",
                )
            ]

        if state.busy:
            return [
                (
                    "class:status.busy",
                    " AI 正在输出 | 可以继续输入草稿，回答结束后再按 Enter ",
                )
            ]

        return [
            (
                "class:status.ready",
                " AI 空闲中 | Enter 提交 | PageUp/PageDown 滚动 | Ctrl+D 退出 ",
            )
        ]

    root_container = HSplit(
        [
            Window(
                content=FormattedTextControl(
                    text=get_header_text,
                ),
                height=1,
                style="class:header",
            ),
            output_window,
            Window(
                height=1,
                char="-",  
                style="class:separator",
            ),
            Window(
                content=FormattedTextControl(
                    text=get_status_text,
                ),
                height=1,
            ),
            VSplit(
                [
                    Window(
                        content=FormattedTextControl(
                            text=[
                                (
                                    "class:prompt",
                                    " 你 > ",
                                )
                            ]
                        ),
                        width=6,
                        height=1,
                        dont_extend_width=True,
                    ),
                    Window(
                        content=input_control,
                        height=1,
                        dont_extend_height=True,
                        style="class:input",
                    ),
                ],
                height=1,
                style="class:input",
            ),
        ]
    )

    layout = Layout(
        container=root_container,
        focused_element=input_control,
    )

    kb = KeyBindings()
    app: Application

    def append_output(text: str) -> None:
        """
        在 Application 所在事件循环中，向只读输出缓冲区追加文本。
        
        参数说明：
            text (str): 待追加的增量文本碎片。
        """
        old_cursor_position = output_buffer.cursor_position
        new_text = output_buffer.text + text

        if state.follow_output:
            new_cursor_position = len(new_text)
        else:
            new_cursor_position = min(
                old_cursor_position,
                len(new_text),
            )

        output_buffer.set_document(
            Document(
                text=new_text,
                cursor_position=new_cursor_position,
            ),
            bypass_readonly=True,
        )

        app.invalidate()

    def get_page_size() -> int:
        """
        参考 Window 上一帧的物理高度，计算逻辑行翻页步长。
        
        返回：
            int: 单页步长行数。
        """
        render_info = output_window.render_info

        if render_info is None:
            return 10

        return max(
            1,
            render_info.window_height - 1,
        )

    async def stream_ai_reply(user_text: str) -> None:
        """
        AI 响应的异步模拟任务协程。

        参数：
            user_text：用户输入的字符串

        异常处理规范：
            - asyncio.CancelledError: 在应用退出被 cancel 时必须原样 re-raise，不能吞没，以完成协程栈清理。
            - Exception: 兜底通用运行时异常并输出到 TUI，防止崩溃退出。
        """
        full_content: str | None = None
        full_reasoning: str | None = None
        full_content_list: list[str] = []
        full_reasoning_list: list[str] = []
        try:
            if appcontext.config_env_error:
                append_output("缺少环境变量，或仍为模板占位符，请在 .env 中写入真实的配置值！")
                append_output("\n")
            else:
                user_created_at: str = get_current_time_iso()
                api_messages: list[dict[str, str]]
                if appcontext.config["session_id"]:
                    api_messages = []
                    for message_each in appcontext.session["messages"]:
                        api_message_each = {
                            "role": message_each["role"],
                            "content": message_each["content"],
                        }
                        api_messages.append(
                            api_message_each
                        )
                else:
                    character_id: str = appcontext.config["current_character_id"]
                    character_name: str = Path(character_id).stem
                    while True:
                        hex_ran_num = hex(random.randint(0, 268436455))
                        session_id = f"{character_name}_{hex_ran_num}.json"
                        session_path: Path = appcontext.base_dir / "user_data" / "sessions" / f"{session_id}"
                        if not session_path.exists():
                            break
                    session: dict[str, Any] = {
                        "title": f"与{character_name}的对话",
                        "character_id": character_id,
                        "created_at": user_created_at,
                        "character_prompt": appcontext.character_prompt,
                        "messages": [
                            {
                                "role": "system",
                                "content": appcontext.character_prompt,
                                "created_at": user_created_at,
                            },
                        ]
                    }
                    
                    api_messages = [
                        {
                            "role": "system",
                            "content": appcontext.character_prompt,
                        },
                    ]

                async for text in model_connect.chat_with_model(appcontext=appcontext, user_text=user_text, messages=api_messages):
                    append_output(text)
                    full_content_list.append(text)
                full_content = "".join(full_content_list)
                assistant_created_at: str = get_current_time_iso()
                if full_content and full_content.strip():
                    if not appcontext.config["session_id"]:
                        appcontext.change_session(
                            session,
                            session_id
                        )
                    appcontext.session["messages"].extend(
                        [
                            {
                                "role": "user",
                                "content": user_text,
                                "created_at": user_created_at,
                            },
                            {
                                "role": "assistant",
                                "content": full_content,
                                "created_at": assistant_created_at,
                            },
                        ]
                    )
                else:
                    append_output("\n[系统提示] 模型未返回有效回复，本次对话未记录。")
                append_output("\n")
                
                if appcontext.session_path and appcontext.session:
                    file_operate.write_json_atomic(appcontext.session_path, appcontext.session)
                    file_operate.write_json_atomic(appcontext.base_dir / "user_data" / "config.json", appcontext.config)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            append_output(
                f"\n[系统错误] 生成回复失败：{exc}\n"
            )
        finally:
            state.busy = False
            state.notice = ""
            app.invalidate()

    def request_exit(event, message: str) -> None:
        """
        终端显示告别词，并中断 Application 事件循环。
        参数：
            event：上一级按键回调转交过来的一个按键事件对象，包含当前正在处理这个按键的 Application
            message：告别词
        """
        state.exit_message = message
        event.app.exit()

    @kb.add("enter", eager=True)
    def submit(event) -> None:
        """
        按下回车键触发函数。

        读入输入框字符串，对字符串判断。可能清空输入框。
        """
        user_text = input_buffer.text

        if user_text.casefold() == "/=exit":
            request_exit(
                event,
                "你离开了 AI 小酒馆。",
            )
            return

        if not user_text.strip():
            state.notice = "请输入内容后再提交。"
            event.app.invalidate()
            return

        if state.busy:
            state.notice = (
                "AI 还在回答；本次没有提交，输入草稿已保留。"
            )
            event.app.invalidate()
            return

        input_buffer.reset()

        state.busy = True
        state.notice = ""
        state.follow_output = True

        output_buffer.cursor_position = len(output_buffer.text)

        append_output(
            f"\n你：{user_text}\n"
            f"{appcontext.llm_model}："
        )

        event.app.create_background_task(
            stream_ai_reply(user_text)
        )

    @kb.add("pageup", eager=True)
    def scroll_output_up(event) -> None:
        """向上整页滚动屏幕浏览历史记录。"""
        state.follow_output = False
        output_buffer.cursor_up(
            count=get_page_size(),
        )
        event.app.invalidate()

    @kb.add("pagedown", eager=True)
    def scroll_output_down(event) -> None:
        """向下整页滚动屏幕浏览历史记录。"""
        document = output_buffer.document
        page_size = get_page_size()
        if (
            document.cursor_position_row + page_size
            < document.line_count - 1
        ):
            output_buffer.cursor_down(
                count=page_size,
            )
            state.follow_output = False
        else:
            output_buffer.cursor_position = len(
                output_buffer.text
            )
            state.follow_output = True

        event.app.invalidate()

    @kb.add("c-home", eager=True)
    def scroll_output_to_top(event) -> None:
        """Ctrl + Home 组合键：直接跳跃至输出区域顶部。"""
        state.follow_output = False
        output_buffer.cursor_position = 0
        event.app.invalidate()

    @kb.add("c-end", eager=True)
    def scroll_output_to_bottom(event) -> None:
        """Ctrl + End 组合键：直接跳跃至输出区域底部。"""
        output_buffer.cursor_position = len(
            output_buffer.text
        )
        state.follow_output = True
        event.app.invalidate()

    @kb.add("c-d", eager=True)
    def exit_with_ctrl_d(event) -> None:
        request_exit(
            event,
            "[系统] 已收到 Ctrl+D，你离开了酒馆。",
        )

    style = Style.from_dict(
        {
            "header": "bg:#3a2f25 #ffd787 bold",
            "output": "bg:#1c1c1c #e4e4e4",
            "separator": "bg:#1c1c1c #6c5c4c",
            "prompt": "bg:#262626 #00d7af bold",
            "input": "bg:#262626 #ffffff",
            "status.ready": "bg:#005f00 #ffffff",
            "status.busy": "bg:#875f00 #ffffff",
            "status.warning": "bg:#5f0000 #ffffff",
        }
    )

    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=True,
        style=style,
        mouse_support=False,
        enable_page_navigation_bindings=False,
        min_redraw_interval=0.02,
    )

    await app.run_async()
    return state.exit_message


if __name__ == "__main__":
    pass