
#/ - 在使用该 future 特性的 Python 版本中，`Path`、`str | None` 等注解不会在
#/   定义语句执行时立刻按普通表达式求值，而会以字符串化形式保存；
#/ - 这让前向引用更容易书写，也能减少仅由注解导致的导入时名称依赖；
from __future__ import annotations

from typing import Any
#/ asyncio提供协程、Task、Future 和事件循环等异步编程基础设施。
import asyncio

import random

import json

import contextlib

from openai import AsyncOpenAI

#/ dataclasses 是标准库模块；dataclass 是其中的类装饰器函数。
from dataclasses import dataclass

#/ pathlib 是标准库的面向对象路径模块。
#/ 使用 Path 通常比手工拼接 `"目录\\文件"` 更安全、更清晰。
from pathlib import Path

#/ prompt_toolkit 是第三方终端交互库。当前程序没有使用它的 `prompt()` 简单接口，
#/ 而是直接组合底层 Application、Layout、Window、Control 和 Buffer。

from prompt_toolkit.application import Application

from prompt_toolkit.buffer import Buffer

from prompt_toolkit.document import Document


#/ `@kb.add("enter")` 形式的装饰器会把一个回调函数登记为 Enter 的处理器。
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

import assets_tools_calls

import rag


#/ 装饰器语法：@xxx
#/ @dataclass 会读取类体中的字段注解和默认值，并自动生成常用样板方法，例如 __init__()、__repr__()、__eq__()。
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
    rag_status: str = ""


async def tavern_loop(appcontext:AppContext) -> str:
    """
    AI 酒馆的主终端交互异步事件循环。
    
    返回：
        str: 退出应用时拟输出到标准输出终态的 exit_message。
    """


    #/ state 是 tavern_loop 的局部变量；下面许多嵌套函数会通过闭包访问这个对象。
    state = UIState()


    #/ 整个应用共用一个客户端：连接池与 TLS 会话跨请求复用。
    appcontext.llm_client = AsyncOpenAI(
        api_key=appcontext.llm_api_key,
        base_url=appcontext.llm_base_url,
        max_retries=2,
        timeout=20.0,
    )


    async def animate_status(waiting_message: str) -> None:
        """
        在状态区循环显示旋转指示，直到任务被取消。

        取消时机：task.cancel() 会在下一个 await 点送达，
        由 except CancelledError 接住，finally 负责清理。
        """
        frames = ("|", "/", "-", "\\")
        index = 0
        try:
            while True:
                #/ 先画再睡：调用后立刻能看到第一帧。
                state.rag_status = f"{waiting_message}（{frames[index]}）"
                app.invalidate()
                index = (index + 1) % len(frames)
                await asyncio.sleep(0.12)          # ← 取消在这里送达
        except asyncio.CancelledError:
            pass                                   # 正常取消，不是错误
        finally:
            #/ 无论如何退出，都把状态栏清干净。
            state.rag_status = ""
            app.invalidate()


    credential_status = f"已配置（***{appcontext.llm_api_key[-3:]}）" if appcontext.llm_api_key else "未配置"
    endpoint_status = f"已配置（***{appcontext.llm_base_url.split('://')[-1]}）" if appcontext.llm_base_url else "未配置"
    #/文本显示流程
    #/ Application（app）
    #/ └── Layout（layout）
    #/     └── HSplit（root_container）
    #/         └── Window（如output_window）
    #/             └── BufferControl（如output_control）
    #/                 └── Buffer（output_buffer）
    #/                     └── Document（当前文本和光标位置的快照）
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
    initial_screen_text:str
    if appcontext.config_env_error is not None:
        initial_screen_text =welcome_text+ (
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
        initial_screen_text = history_display+welcome_text


    #/ prompt_toolkit Style 实例；运行时 Application 会查询它，
    #/ 把 class:xxx 名称转换成终端颜色和粗体等属性。该调用只建立规则，不会在此刻立即绘制终端。
    #/ 字典中的键是样式类名称，值是 prompt_toolkit 样式描述字符串。
    style = Style.from_dict(
        {   #/bg:   #十六进制颜色   设置背景色
            #/      #十六进制颜色   设置前景色，也就是文字或字符颜色
            #/bold  设置为粗体

            #/ 顶部标题栏样式。
            #/ #3a2f25：深棕色
            #/ #ffd787：浅金黄色
            "header": "bg:#3a2f25 #ffd787 bold",

            #/ AI 对话输出区域样式。
            #/ #1c1c1c：接近黑色的深灰色
            #/ #e4e4e4：浅灰色
            "output": "bg:#1c1c1c #e4e4e4",

            #/ 输出区与输入区之间的分隔线样式。
            #/ #1c1c1c：接近黑色的深灰色
            #/ #6c5c4c：偏棕的灰色
            "separator": "bg:#1c1c1c #6c5c4c",

            #/ 输入框左侧提示文字的样式，例如“你：”。
            #/ #262626：深灰色
            #/ #00d7af：青绿色
            "prompt": "bg:#262626 #00d7af bold",

            #/ 用户实际输入内容的样式。
            #/ #262626：深灰色
            #/ #ffffff：纯白色
            "input": "bg:#262626 #ffffff",

            #/ 状态栏处于“空闲、可以提交”状态时的样式。
            #/ #005f00：深绿色
            #/ #ffffff：纯白色
            "status.ready": "bg:#005f00 #ffffff",

            #/ 状态栏处于“AI 正在生成回复”状态时的样式。
            #/ #875f00：深黄褐色
            #/ #ffffff：纯白色
            "status.busy": "bg:#875f00 #ffffff",

            #/ 状态栏显示警告或错误提示时的样式。
            #/ #5f0000：深红色
            #/ #ffffff：纯白色
            "status.warning": "bg:#5f0000 #ffffff",
        }
    )


    #/ `Buffer` 是 prompt_toolkit 提供的类；写成 `Buffer(...)` 是在调用它的构造器并创建一个 Buffer 实例。
    #/ 这个实例专门保存“聊天输出区”的全部文本、光标位置以及与文本相关的编辑状态。
    #/ 它本身不会直接在终端上绘图，稍后还要由`BufferControl` 读取它，再由 `Window` 把读取结果显示出来。
    output_buffer = Buffer(
        #/`document` 参数指定 Buffer 创建时采用的初始 Document 快照。
        #/如果省略该参数，Buffer 默认从空文本开始。
        document=Document(
            #/ `Document` 也是 prompt_toolkit 提供的类。
            text=initial_screen_text,

            #/ `cursor_position` 是以 Python 字符串索引表示的光标位置。
            #/ 设置为 len(...) 后，光标落在文本末尾；
            cursor_position=len(initial_screen_text),  
        ),

        #/ `read_only=True` 阻止用户通过正常编辑命令修改这个 Buffer。
        #/ 程序仍可通过 `set_document(..., bypass_readonly=True)` 主动更新它，
        #/ 所以后面的流式模型文本依然能够被 append_output() 追加进来。
        read_only=True,
    )


    #/ 这是定义在 tavern_loop 内部的“嵌套函数”。它可以访问外层（tavern_loop()内）的 state，形成闭包。
    def clear_notice_when_editing(_: Buffer) -> None:
        """
        Buffer 文本变化事件回调（Event Handler）。
        
        参数说明：
            参数名 `_` 只是 Python 社区惯例，表示“协议要求接收，但函数体不使用”。
            `_` 仍然是完全正常的变量名，解释器不会赋予它特殊的忽略语义。
        """
        state.notice = ""

    input_buffer = Buffer(
        #/ `multiline=False` 把该 Buffer 配置为单行编辑模式。
        multiline=False,

        #/ 这里传入的是函数对象，而不是调用函数。
        #/ Buffer 的文本以后每次发生变化时，prompt_toolkit 都会调用
        #/ clear_notice_when_editing(changed_buffer)，从而清空状态栏的临时 notice。
        on_text_changed=clear_notice_when_editing,
    )


    output_control = BufferControl(
        #/ 指定要读取和显示的 Buffer 实例：output_buffer。
        buffer=output_buffer,

        #/ 禁止布局把键盘焦点切换到聊天输出区。
        #/ 运行时可见效果是：用户输入的普通字符始终进入底部输入框，而不会意外编辑或选中输出 Buffer。
        focusable=False,
    )

    #/ input_control 没有显式传 focusable；BufferControl 默认允许获得焦点。
    #/ 当它拥有焦点时，普通字符按键会编辑 input_buffer。
    input_control = BufferControl(
        #/ 指定要读取和显示的 Buffer 实例：input_buffer。
        buffer=input_buffer,
    )





    output_window = Window(
        #/ 指定 Window 要渲染哪个 UIControl。
        content=output_control,


        #/至少保留 1 行；当 HSplit 分配完固定高度组件后，按 weight=1 参与剩余高度分配。
        #/这里只有一个弹性大区域（output_window），因此它会吃掉几乎全部剩余行。
        height=Dimension(min=1, weight=1),


    #/True：逻辑行超过窗口显示宽度时软折行；不会把 `\n` 写入原 Buffer 文本。
        wrap_lines=True,

        #/ True：不绘制 output_buffer 的可见终端光标；内部光标仍存在并继续用于控制滚动位置。
        always_hide_cursor=True,

        #/ `ScrollOffsets` 创建滚动留白配置。
        #/ top=1、bottom=1 表示条件允许时，光标与视口上下边缘之间各尽量保留一行。
        scroll_offsets=ScrollOffsets(top=1, bottom=1),

    #/     右边距参数需要一个 Margin 对象列表；这里right_margins列表中只有一个滚动条。
        #/ `right_margins` 接受 Margin 实例列表；列表中的对象依次画在终端窗口右侧。
        right_margins=[
            
            #/ ScrollbarMargin 通常占一列，它只是视觉指示器；
            #/ 后续Application中mouse_support=False 时不能把它当成可用鼠标拖动的桌面 GUI 滚动条。
            #/ `ScrollbarMargin` 创建字符滚动条。
            #/ display_arrows=True：在滚动条上下端显示箭头字符作为提示（终端支持时）。
            ScrollbarMargin(display_arrows=True),
        ],

        #/ prompt_toolkit 的样式语法。使用后续的 Style 对象中键名为 output 的样式规则。
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

        #/ 加载中的提示优先级最高：它表示系统还没就绪。
        if state.rag_status:
            return [
                (
                    "class:status.busy",
                    f" {state.rag_status} ",
                )
            ]
        
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


    #/ `HSplit(...)` 创建垂直分割容器。它不保存文字，也不直接处理键盘；
    #/ 它只负责按 children 列表的顺序从上到下摆放各个 Window/Container。
    root_container = HSplit(
        #/ HSplit 的第一个位置参数是 children：一个容器列表。
        [
            #/ 这个 Window（标题） 只占据一行，用于绘制动态标题文字。
            Window(
                #/ FormattedTextControl 把“样式片段 + 文本”转换成可由 Window绘制的内容。
                
                content=FormattedTextControl(
                    #/ 这里传 `text=get_header_text`，即函数对象，而不是调用结果。
                    #/ FormattedTextControl 因此能在绘制阶段动态取值。
                    text=get_header_text,
                ),

                height=1,

                style="class:header",
            ),

            #/ 输出 Window 没有固定高度，会伸缩占据中间区域。
            output_window,

            #/ 这个 Window 没有 content，因此只绘制空白/填充字符；配合 char="-"后形成贯穿可用宽度的横向分隔线。
            Window(
                #/ 固定占用一行。
                height=1,

                #/ 用连字符填充这一行的未占用单元格。
                char="-",  

                #/ 使用 separator 样式类。
                style="class:separator",
            ),

            #/ 状态栏 Window 同样固定一行；text 接收动态函数对象。
            Window(
                content=FormattedTextControl(
                    text=get_status_text,
                ),
                height=1,
            ),

            #/ `VSplit(...)` 创建水平分割容器，按 children 顺序从左到右排列。
            #/ 这里把固定宽度的“你 >”提示符和可伸缩输入区放在同一行。
            VSplit(
                #/ VSplit 的第一个位置参数同样是 children 列表。
                [
                    #/ 左侧静态提示符。
                    Window(
                        content=FormattedTextControl(
                            text=[
                                (
                                    "class:prompt",
                                    " 你 > ",
                                )
                            ]
                        ),

                        #/ width=6 表示终端“显示列”约束，不是 6 个 Unicode 字符。
                        #/ 字符串 ` 你 > ` 的 Python 长度为 5，但中文“你”通常占 2 个显示列，
                        #/ 所以视觉宽度正好约为 6 列。
                        width=6,
                        height=1,

                        #/ 默认布局可能把 Window 扩展到超过首选宽度；设为 True 后，
                        #/ 提示符区尽量只占自己的固定宽度，把其余宽度留给输入区。
                        #/ 传入整数 width=6 本身会被转换成精确 Dimension，因此这里的
                        #/ dont_extend_width=True 主要是进一步表达布局意图，作用有限。
                        dont_extend_width=True,
                    ),

                    #/ 右侧为输入 Window。
                    Window(
                        #/ 接入 input_control，显示 input_buffer 的实时内容。
                        content=input_control,

                        #/ 为一行。
                        height=1,

                        #/ 父 VSplit 已经固定为一行，这个参数进一步表明子 Window不应主动向额外高度扩展。
                        dont_extend_height=True,
                        style="class:input",
                    ),
                ],
                #/ 整个 VSplit 固定一行，所以它稳定停留在 HSplit 的最底部。
                height=1,

                #/ 给整条底部输入栏提供 input 默认样式。
                style="class:input",
            ),
        ]
    )


    #/ `Layout(...)` 创建布局管理器。它保存整棵容器树，还负责记录当前焦点。
    #/ 运行后 Application 会通过这个对象确定每块区域的位置和按键应交给哪个控件。
    layout = Layout(
        #/ 指定刚才的 HSplit 是整棵布局树的根节点（即其他分支的根结构起点）。
        container=root_container,

        #/ 指定程序启动时 input_control 获得焦点，用户无需先按 Tab 就能输入。
        focused_element=input_control,
    )


    #/ `KeyBindings()` 创建空的按键绑定注册表。构造器没有传入参数，因此此刻没有自定义规则；
    #/ 后续 `@kb.add(...)` 会逐条把回调登记到这个同一实例中。
    kb = KeyBindings()

    #/ 这是一条“仅注解、不赋值”的局部变量声明。主要服务于 VS Code/Pylance 等静态分析工具。
    app: Application


    def append_output(text: str) -> None:
        """
        在 Application 所在事件循环中，向只读输出缓冲区追加文本。
        
        参数说明：
            text (str): 待追加的增量文本碎片。
        """

        #/ `cursor_position` 是以 Python 字符串索引表示的光标位置。
        old_cursor_position = output_buffer.cursor_position

        new_text = output_buffer.text + text
        #/ 如果处于自动跟随状态，把输出 Buffer 的光标放到新文本末尾；
        #/ Window 会以受控光标为参照，把最新内容滚动到可见区域。
        if state.follow_output:
            new_cursor_position = len(new_text)
        else:
            #/ 当前程序只追加不删除，所以 old_cursor_position 通常仍合法；
            #/ 保留 min是为了即使未来改为截断历史，也不会产生超过新文本长度的游标位置。
            new_cursor_position = min(
                old_cursor_position,
                len(new_text),
            )

        #/ Buffer.set_document() 用一个新 Document 整体替换当前文本快照。
        output_buffer.set_document(
            Document(
                #/ 输出区的新完整文本。
                text=new_text,

                #/ 根据 follow_output 决定跟随末尾，还是保留用户正在浏览的位置。
                cursor_position=new_cursor_position,
            ),

            #/ 绕过 output_buffer 的 read_only 保护；只允许这次程序控制的替换，
            #/ 并不会把 Buffer 永久改成可编辑状态。
            bypass_readonly=True,
        )

        #/ invalidate() 的意思是“请求安排一次重绘”。
        #/ 它不一定会在调用返回前绘制完成；Application 会在事件循环合适的时机重新计算动态文本和布局，再把变化输出到终端。
        app.invalidate()


    def get_page_size() -> int:
        """
        参考 Window 上一帧的物理高度，计算逻辑行翻页步长。
        
        返回：
            int: 单页步长行数。
        """

        #/ render_info 保存上一次渲染该 Window 时产生的信息。包括：
        #/ 窗口实际高度、
        #/ 竖直滚动位置、
        #/ 哪些内容行正在显示、
        #/ 内容位置与终端坐标的对应关系、
        #/ 光标在窗口中的显示位置等。
        render_info = output_window.render_info

        if render_info is None:
            #/ 第一次渲染之前它可能为 None，不知道真实高度时，使用一个保守的逻辑行回退值。
            return 10

        #/ 确保步长至少是 1。
        #/ 减 1 可以让连续翻页保留少量上下文，降低视觉跳跃。
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
        
        #/ 模型完整回复和完整思考链字符串
        full_content: str |None = None
        full_reasoning: str |None = None
        full_tool_calls: list |None = None
        full_tool_calls_str: str |None = None
        #/ 模型完整回复和完整思考链列表
        full_content_list: list[str] = []
        full_reasoning_list: list[str] = []
        full_tool_calls_list:list[dict] = []
        try:
            if appcontext.config_env_error:
                append_output("缺少环境变量，或仍为模板占位符，请在 .env 中写入真实的配置值！")
                append_output("\n")
            else:
                need_tool_calls:bool=True
                tool_calls_error_times:int=0
                tool_calls_times:int=0
                full_tool_calls= None
                full_tool_calls_str= None
                full_tool_calls_list= []
                #/ 记录用户提交消息的时间。
                user_created_at: str = get_current_time_iso()
                api_messages: list[dict[str, str]]=[]
                #/ 如果配置文件中记录了历史对话id
                if appcontext.config["session_id"]:
                    api_messages= []
                    #/ 提取session["messages"]中需要的内容
                    for message_each in appcontext.session["messages"]:
                        #/ 复制message_each，避免api_message_each指向appcontext.session["messages"]
                        api_message_each = message_each.copy()
                        api_message_each.pop("created_at", None)
                        api_messages.append(
                            api_message_each
                        )
                else:
                    character_id: str = appcontext.config["current_character_id"]
                    character_name: str = character_id
                    #/ 创建一个对话json文件，并记录id
                    while True:
                        hex_ran_num = hex(random.randint(0, 268436455))
                        session_id= f"{character_name}_{hex_ran_num}.json"
                        session_path:Path=appcontext.base_dir / "user_data" / "sessions"/f"{session_id}"
                        if not session_path.exists():
                            break
                    session:dict[str, Any]={
                        "title": f"与{character_name}的对话",
                        "character_id": character_id,
                        "created_at": user_created_at,
                        "character_prompt":appcontext.character_prompt,
                        "messages": [
                            {
                                "role": "system",
                                "content": appcontext.character_prompt,
                                "created_at": user_created_at,
                            },
                        ]
                    }
                    
                    api_messages= [
                        {
                            "role": "system",
                            "content": appcontext.character_prompt,
                        },
                    ]
                    appcontext.change_session(
                        session,
                        session_id
                    )
                #/ 提取user_text并清空
                if user_text:
                    appcontext.session["messages"].append(
                        {
                            "role": "user",
                            "content": user_text,
                            "created_at": user_created_at,
                        },
                    )

                #/ 程序侧先对用户原话做一次预检索，
                #/ 把有效背景随本轮问题一起发给模型。
                #/ 这样即使用户后续追问时模型不调用工具，也有设定依据。
                #/
                #/ 检索失败不能让普通聊天一起失败：
                #/ 缺少世界观文档、索引损坏、模型加载失败，
                #/ 都只降级为"本轮不参考知识库"，并提示用户。
                #/ 检索包含同步的编码与建索引，放进线程避免卡住界面。
                background: str = ""
                if appcontext.session_character_dir is not None:
                    try:
                        background = await asyncio.to_thread(
                            rag.search_worldview,
                            appcontext.embedding_model_dir,
                            appcontext.session_character_dir,
                            user_text,
                        )
                    except Exception as error:
                        background = ""
                        append_output(
                            f"\n[系统提示] 世界观检索不可用"
                            f"（{type(error).__name__}），本轮将只依据角色人设回答。\n"
                        )

                #/ 检索无有效结果时不注入，避免塞一个空的【背景】块。
                #/ 存档用的上一条 message 仍是干净的 user_text。
                if background:
                    api_messages.append({
                        "role": "user",
                        "content": (
                            "<reference_character_worldview>\n"
                            f"{background.strip()}\n"
                            "</reference_character_worldview>\n\n"
                            "<user_question>\n"
                            f"{user_text.strip()}\n"
                            "</user_question>"
                        ),
                    })

                else:
                    api_messages.append(
                        {"role": "user", "content": user_text}
                    )
                user_text=""

                while(need_tool_calls and tool_calls_error_times<4 and tool_calls_times<11):
                    need_tool_calls=False
                    #/ 重置临时变量
                    full_content = None
                    full_reasoning= None
                    full_tool_calls= None
                    full_tool_calls_list_each:list=None
                    full_content_list=[]
                    full_reasoning_list= []
                    full_tool_calls_list= []
                    tmp_index_list:list=[]
                    tmp_tool_calls_dict:dict={}
                    #/ arguments 分片缓冲：index → 已拼接的字符串。
                    #/ 单独存一份，避免直接修改 SDK 返回的对象。
                    tmp_arguments_dict:dict[int,str]={}
                    #/ 记录本次模型请求开始前的消息数量。
                    #/ 必须放在 while 内部，每次请求重新记录。
                    api_message_count_before_reply: int = len(api_messages)

                    session_message_count_before_reply: int = len(
                        appcontext.session["messages"]
                    )
                    #/ chat_with_model() 是异步生成器函数。
                    #/ `async for` 会异步等待生成器产生下一个值（yield 产生的字符串）
                    tool_calls_times+=1
                    async for content,tool_calls in model_connect.chat_with_model(appcontext=appcontext,messages=api_messages,tools=appcontext.assets_tools):
                        if content:
                            append_output(content)
                            full_content_list.append(content)
                        if tool_calls:

                            #/ 每个tool_calls块是一个含有一个dict的list，用索引（index）拼接
                            for tool_call in tool_calls:
                                index:int = tool_call.index
                                tmp_index_list.append(index)

                                if index not in tmp_tool_calls_dict:
                                    tmp_tool_calls_dict[index]=tool_call
                                    tmp_arguments_dict[index]=""

                                #/ 对同一个index的arguments进行拼接。
                                #/ 只累加实际存在的增量：SDK 允许该字段为空，
                                #/ 首片可能是 None，直接 += 会抛 TypeError。
                                piece:str|None = tool_call.function.arguments
                                if piece:
                                    tmp_arguments_dict[index] += piece
                            
                    full_content= "".join(full_content_list)
                    #/ 把字典的所有值转存为list
                    for index, call in tmp_tool_calls_dict.items():
                        full_tool_calls_list.append( 
                            {
                                "id": call.id,
                                "type": call.type,
                                "function": {
                                    "name": call.function.name,
                                    "arguments": tmp_arguments_dict.get(index, ""),
                                },
                            }   
                        )
                    #/ 助手消息的时间应在回复完成后获取。
                    assistant_created_at: str = get_current_time_iso()
                    if (full_content and full_content.strip()) or (full_tool_calls_list):
                        #/ 收到回复后修改appcontext
                        if not appcontext.config["session_id"]:
                            appcontext.change_session(
                                session,
                                session_id
                            )
                        #/ extend 依次添加多条消息
                        if not full_tool_calls_list:
                            appcontext.session["messages"].append(
                                {
                                    "role": "assistant",
                                    "content": full_content,
                                    "created_at": assistant_created_at,
                                },
                            )
                            api_messages.append(
                                {
                                    "role": "assistant", 
                                    "content": full_content
                                }
                            )
                        else:
                            if not (full_content and full_content.strip()):
                                append_output("\n[系统提示] 模型正在调用工具，暂无回复。")
                            appcontext.session["messages"].append(
                                {
                                    "role": "assistant",
                                    "content": full_content,
                                    "tool_calls":full_tool_calls_list,
                                    "created_at": assistant_created_at,
                                },
                            )
                            api_messages.append(
                                {
                                    "role": "assistant", 
                                    "content": full_content,
                                    "tool_calls":full_tool_calls_list
                                }
                            )
                        
                    else:
                        append_output("\n[系统提示] 模型未返回有效回复，本次用户输入已保留。")

                    if full_tool_calls_list:
                        tool_call_result:list[dict]=[]
                        try:
                            full_tool_calls = full_tool_calls_list
                            
                            
                            for tool_call in full_tool_calls:
                                tool_call_id: str = tool_call["id"]
                                tool_type: str = tool_call["type"]
                                
                                #/ 目前只实现 function 类型，不假定其他类型也具有相同结构。
                                if tool_type != "function":
                                    tool_calls_error_times+=1
                                    tool_call_result.append({
                                        "tool_call_id":tool_call_id,
                                        "content":f"工具调用失败：暂不支持的工具类型：{tool_type}。"
                                    })
                                    continue
                                tool_info: dict = tool_call[tool_type]
                                tool_name: str = tool_info["name"]
                                tool_args: str = tool_info["arguments"]

                                try:
                                    args = json.loads(tool_args)
                                except Exception as exc:
                                    tool_calls_error_times+=1
                                    append_output(
                                        f"\n[系统提示] 调用工具{tool_name}失败。稍后尝试重新调用。"
                                    )
                                    tool_call_result.append({
                                        "tool_call_id":tool_call_id,
                                        "content":f"\n[系统提示] 调用工具{tool_name}失败。参数 JSON 解析失败。"
                                    })
                                    continue
                                if not isinstance(args, dict):
                                    tool_calls_error_times+=1
                                    tool_call_result.append({
                                        "tool_call_id":tool_call_id,
                                        "content":"工具调用失败：工具arguments参数必须是 dictionary 对象。"
                                    })
                                    continue
                                try:
                                    #/ 工具内部可能包含同步的检索与编码，
                                    #/ 放进线程执行，避免阻塞事件循环。
                                    result = await asyncio.to_thread(
                                        assets_tools_calls.tool_calls,
                                        appcontext,
                                        name=tool_name,
                                        **args,
                                    )
                                    tool_call_result.append({
                                        "tool_call_id":tool_call_id,
                                        "content":str(result)
                                    })
                                except Exception as exc:
                                    tool_calls_error_times+=1
                                    append_output(
                                        f"\n[系统提示] 调用工具{tool_name}失败。稍后尝试重新调用。"
                                    )
                                    tool_call_result.append({
                                        "tool_call_id":tool_call_id,
                                        "content":f"\n[系统提示] 调用工具{tool_name}失败。可能是name或arguments参数有误。"
                                    })
                                    continue
                            if not tool_call_result:
                                tool_calls_error_times+=1
                                need_tool_calls=True
                                append_output(
                                    "\n[系统提示] 调用工具失败。正在尝试重新调用。"
                                )
                            
                        #/ 异常：大多数继承自 Exception 的普通异常
                        except Exception as exc:
                            tool_calls_error_times += 1
                            need_tool_calls = False

                            #/ 删除本次模型请求之后追加的消息，
                            #/ 避免留下不完整的 assistant 工具调用及其结果。
                            del api_messages[api_message_count_before_reply:]

                            del appcontext.session["messages"][
                                session_message_count_before_reply:
                            ]

                            append_output(
                                f"\n[系统错误] 工具调用处理出现异常："
                                f"{type(exc).__name__}：{exc}\n"
                                "已停止本轮处理，并移除本次未完成的消息记录。"
                                "此前已执行的工具操作不会因此撤销。\n"
                            )

                            #/ 此处已经位于内部 for 循环之外，
                            #/ 因此 break 跳出的是外层 while，不再请求模型。
                            break
                    tool_created_at: str = get_current_time_iso()
                    if full_tool_calls_list:
                        #/ 收到回复后修改appcontext
                        if not appcontext.config["session_id"]:
                            appcontext.change_session(
                                session,
                                session_id
                            )
                        if tool_call_result:
                            need_tool_calls=True
                            for tool_call_result_each in tool_call_result:
                                appcontext.session["messages"].append(
                                    {
                                        "role": "tool",
                                        "tool_call_id":tool_call_result_each["tool_call_id"],
                                        "content": tool_call_result_each["content"],
                                        "created_at": tool_created_at,
                                    },
                                )
                                api_messages.append(
                                    {
                                        "role": "tool", 
                                        "tool_call_id":tool_call_result_each["tool_call_id"],
                                        "content":tool_call_result_each["content"]
                                    }
                                )
                    
                    #/ 回复结束后追加换行符
                    append_output("\n")

                    if appcontext.session_path and appcontext.session:
                        file_operate.write_json_atomic(appcontext.session_path, appcontext.session)
                        file_operate.write_json_atomic(appcontext.base_dir / "user_data" / "config.json", appcontext.config)
                #/ 正常回答结束或异常回档时，need_tool_calls 已经是 False。
                #/ 仍然为 True 却退出循环，说明触及了次数限制。
                if need_tool_calls:
                    append_output(
                        "\n[系统提示] 已达到本轮请求或错误次数上限，"
                        "已停止继续调用工具。\n"
    )

        #/ 异常：异步任务被要求取消
        except asyncio.CancelledError:
            #/ 裸 `raise` 会原样重新抛出当前正在处理的异常，并保留其 traceback（异常发生时记录的“函数调用路径”）。
            raise

        #/ 异常：大多数继承自 Exception 的普通异常
        except Exception as exc:
            append_output(
                f"\n[系统错误] 生成回复失败：{exc}\n"
            )

        finally:
            #/ busy 只是单事件循环内的布尔“提交状态标志”，不是线程互斥锁，不能用来保护多线程共享数据。
            state.busy = False
            state.notice = ""
            app.invalidate()
            if appcontext.session_path and appcontext.session:
                file_operate.write_json_atomic(appcontext.session_path, appcontext.session)
                file_operate.write_json_atomic(appcontext.base_dir / "user_data" / "config.json", appcontext.config)


    def request_exit(event, message: str) -> None:
        """
        终端显示告别词，并中断 Application 事件循环。
        参数：
            event：上一级按键回调转交过来的一个按键事件对象，包含当前正在处理这个按键的 Application
            message：告别词
        """

        state.exit_message = message

        #/ Application.exit() 请求结束当前 run_async()。
        #/ 这里不直接调用 sys.exit()，因为要让 prompt_toolkit 有机会恢复终端状态，并取消、等待它管理的后台任务。
        event.app.exit()


    #/ kb.add 返回一个装饰器，装饰器把函数登记到按键映射中。此处是“enter”键。
    #/ eager=True 表示该键序列已经匹配时，不继续等待它是否会成为更长键序列（如“enter”+“ctrl”）的前缀。
    @kb.add("enter", eager=True)
    def submit(event) -> None:
        """
        按下回车键触发函数。

        读入输入框字符串，对字符串判断。可能清空输入框。
        """

        user_text = input_buffer.text

        #/ str.casefold() 返回适合 Unicode 无视大小写比较的标准化字符串，通常比 lower() 更全面。
        #/ 这里让 /=EXIT、/=Exit、/=exit 都能触发退出。
        if user_text.casefold() == "/=exit":
            request_exit(
                event,
                "你离开了 AI 小酒馆。",
            )

            return
        #/ 过滤纯空白消息
        if not user_text.strip():
            state.notice = "请输入内容后再提交。"
            event.app.invalidate()
            return

        #/ 因为这个分支没有调用 input_buffer.reset()，输入框中的草稿会保留。
        if state.busy:
            state.notice = (
                "AI 还在回答；本次没有提交，输入草稿已保留。"
            )
            event.app.invalidate()
            return

        #/ Buffer.reset() 重置输入 Buffer 的 Document 和部分编辑状态。
        input_buffer.reset()

        #/ 下一次 Enter 到来时会立刻看见 busy 状态，从而避免快速连按产生多个任务。
        state.busy = True
        state.notice = ""
        state.follow_output = True

        #/ 把输出 Buffer 的受控光标移到文本末尾，重新启用跟随最新内容。
        output_buffer.cursor_position = len(output_buffer.text)

        append_output(
            f"\n你：{user_text}\n"
            f"{appcontext.llm_model}："
        )

        #/ 把异步函数对象传给 Application.create_background_task()。
        #/ 与裸 asyncio.create_task() 相比，此方法的关键价值是：
        #/ - Application 会跟踪这个 Task；
        #/ - Application 退出时会取消并等待仍未完成的受管任务；
        #/ - 后台任务不应把普通异常泄漏出去，所以协程内部仍有异常处理。
        event.app.create_background_task(
            stream_ai_reply(user_text)
        )

    #/ 绑定键“PU”（“pageup”）
    @kb.add("pageup", eager=True)
    def scroll_output_up(event) -> None:
        """向上整页滚动屏幕浏览历史记录。"""

        #/ 用户主动向上浏览后关闭自动跟随；否则新字符到来会把视图拉回底部。
        state.follow_output = False

        #/ Buffer.cursor_up(count=n) 将 Document 光标向上移动 n 个逻辑行，
        output_buffer.cursor_up(
            count=get_page_size(),
        )

        event.app.invalidate()

    @kb.add("pagedown", eager=True)
    def scroll_output_down(event) -> None:
        """向下整页滚动屏幕浏览历史记录。"""
        document = output_buffer.document
        page_size = get_page_size()
        #/ cursor_position_row 表示当前光标位于第几个逻辑行，第一行返回 0
                #/ line_count 是总逻辑行数，所以最后一行索引是 line_count - 1。
        if (
            document.cursor_position_row+page_size
            < document.line_count - 1
        ):
            output_buffer.cursor_down(
                count=page_size,
            )
            state.follow_output = False
        else:
            #/ 光标跳跃至输出区域底部
            output_buffer.cursor_position = len(
                output_buffer.text
            )
            #/ 打开自动跟随
            state.follow_output = True

        event.app.invalidate()

    #/ `"c-home"` 是 Ctrl+Home 组合键的名称。
    @kb.add("c-home", eager=True)
    def scroll_output_to_top(event) -> None:
        """Ctrl + Home 组合键：直接跳跃至输出区域顶部。"""

        state.follow_output = False

        #/ 光标索引 0 表示字符串第一个字符之前，也就是输出最顶部。
        output_buffer.cursor_position = 0
        event.app.invalidate()

    #/ `"c-end"` 是 Ctrl+End 组合键的名称。
    @kb.add("c-end", eager=True)
    def scroll_output_to_bottom(event) -> None:
        """Ctrl + End 组合键：直接跳跃至输出区域底部。"""

        output_buffer.cursor_position = len(
            output_buffer.text
        )
        state.follow_output = True
        event.app.invalidate()


    #/`"c-d"` 是 Ctrl+D 的按键名称。
    @kb.add("c-d", eager=True)
    def exit_with_ctrl_d(event) -> None:
        request_exit(
            event,
            "[系统] 已收到 Ctrl+D，你离开了酒馆。",
        )

    #/ 此处已删除对方向键“上”的绑定，使其默认作用于输入框


    #/ `Application(...)` 创建本 TUI 的顶层应用实例。前面的 Buffer、Control、
    #/ Window、Layout、KeyBindings、Style 到这里才被汇总到同一个可运行对象中。
    #/ 构造器只完成配置；真正接管终端是在后面的 `await app.run_async()`。
    app = Application(
        #/ 使用 layout 管理布局树和当前焦点。
        layout=layout,

        #/ 使用 kb 中已经登记的 Enter、翻页和退出按键规则。
        key_bindings=kb,

        #/ True：使用整个终端窗口（通常是终端备用屏幕）绘制应用。并非常见的“全屏”。
        full_screen=True,

        #/ 使用前面由 Style.from_dict 创建的样式表。
        style=style,

        #/ False：不解析鼠标事件，主要通过键盘操作界面。
        mouse_support=False,

        #/ False：不额外挂载库自带的 PageUp/PageDown 导航规则，避免和自定义规则冲突。
        enable_page_navigation_bindings=False,

        #/ 两次真实重绘之间至少间隔约 0.02 秒，避免流式片段过密时反复刷屏。
        min_redraw_interval=0.02,
    )


    load_status_task = app.create_background_task(
        animate_status("正在加载向量模型")
    )
    async def preload_then_clear() -> None:
        """后台完成预加载；结束时停掉状态栏动画并清理。"""
        try:
            await rag.preload_worldview_embedding_model(
                appcontext.embedding_model_dir
            )
        finally:
            load_status_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await load_status_task

    #/ 预加载与状态栏动画并发进行：
    #/ run_async() 启动渲染器之后，动画的每一帧才会真正绘制出来。
    app.create_background_task(preload_then_clear())


    #/ `await` 会暂停 tavern_loop 本身，等待 app.run_async() 结束
    #/ 等待期间，Application 仍会处理：
    #/ - 键盘输入监听（key_bindings=kb）等内部制定规则触发的事件
    #/ - 事件对应的回调函数执行过程中创建或登记的新任务、重绘请求和退出请求。
    #/ 当某个按键回调调用 app.exit() 后，Application 开始退出，
    #/ run_async() 恢复终端并完成清理，随后这个 await 才结束。
    try:
        await app.run_async()
    finally:
        await appcontext.llm_client.close()      # 释放连接池


    #/ 返回告别词给外层 main()。此时 prompt_toolkit 已结束全屏 Application。
    return state.exit_message






if __name__ == "__main__":
    pass
