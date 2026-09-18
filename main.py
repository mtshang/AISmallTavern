#/ - 在使用该 future 特性的 Python 版本中，`Path`、`str | None` 等注解不会在
#/   定义语句执行时立刻按普通表达式求值，而会以字符串化形式保存；
#/ - 这让前向引用更容易书写，也能减少仅由注解导致的导入时名称依赖；
from __future__ import annotations

from typing import Any
#/ asyncio提供协程、Task、Future 和事件循环等异步编程基础设施。
import asyncio

import json

import sys

#/ pathlib 是标准库的面向对象路径模块。
#/ 使用 Path 通常比手工拼接 `"目录\\文件"` 更安全、更清晰。
from pathlib import Path

#/ load_dotenv() 会解析 `.env` 文本，并把键值载入“当前 Python 进程”的`os.environ` 中；它不会永久修改 Windows 的系统环境变量。
from dotenv import load_dotenv


import model_connect
import ui
import file_operate
from app_context import AppContext, resolve_character_dir

import rag



def main() -> None:
    """
    程序的同步顶层主入口。
    
    职责：
    1. 使用 asyncio.run 初始化全新的事件循环并驱动 tavern_loop。
    2. 针对操作系统级物理信号和控制台异常进行顶层拦截兜底。
    3. 在退出全屏缓冲区后安全输出退出日志。
    """
    print("酒馆正在加载，请稍等...")

    BASE_DIR: Path

    if getattr(sys, "frozen", False):
        #/ 打包为 exe 后，以 exe 所在文件夹作为项目根目录。
        BASE_DIR = Path(sys.executable).resolve().parent
    else:
        #/ 直接运行源码时，以 main.py 所在文件夹作为项目根目录。
        #/ 右侧表达式按以下顺序求值：
        #/ 1. `__file__`：当前这个 Python 源文件的路径；
        #/ 2. `Path(__file__)`：调用 Path 构造器，把字符串路径包装成 Path 对象；
        #/ 3. `.resolve()`：得到规范化的绝对路径，并处理 `.`、`..` 等路径成分；
        #/ 4. `.parent`：取得文件所在目录，而不是文件本身。
        #/ 大写名称 BASE_DIR 是“模块常量”的命名约定；Python 并不会禁止后续重新赋值。
        BASE_DIR = Path(__file__).resolve().parent
    EMBEDDING_MODEL_DIR:Path=BASE_DIR / "granite-embedding-r2"
    CONFIG_PATH:Path =BASE_DIR / "user_data" / "config.json"
    DEFAULT_CONFIG_PATH:Path =BASE_DIR / "assets" / "default"/"default_config.json"
    CONFIG:dict[str, Any]
    try:
        #/ CONFIG_PATH.exists()致命缺陷：如果路径指向的是一个文件夹（Directory）、符号链接、Socket、管道，它同样返回 True
        #/ CONFIG_PATH.is_file()如果路径指向的是一个文件夹，它会返回 False
        if not CONFIG_PATH.is_file():
            raise FileNotFoundError("未找到用户配置文件")
            
        with CONFIG_PATH.open("r", encoding="utf-8") as file:
            config_data = json.load(file)
            
        if not isinstance(config_data, dict):
            raise TypeError("config.json 根结构必须是键值字典")
            
        CONFIG = config_data
    except Exception as exc:
        #/ 捕获 JSONDecodeError, TypeError, FileNotFoundError 等全部异常
        print(f"[提示] 读取配置文件异常（{exc}），已回退至默认配置。")
        with DEFAULT_CONFIG_PATH.open("r", encoding="utf-8") as file:
            CONFIG = json.load(file)

    SESSION:dict[str, Any]|None=None
    DEFAULT_SESSION_PATH:Path =BASE_DIR / "assets" / "default"/"default_session.json"
    try:
        #/ config["session_id"]     键不存在时：抛出 KeyError 致命异常，程序当场崩溃
        #/ config.get("session_id") 键不存在时：返回 None（或指定的默认值）
        session_id:str = CONFIG.get("session_id", "")
        SESSION_PATH: Path | None = (BASE_DIR / "user_data" / "sessions" / f"{session_id}") if session_id else None
        if not (session_id and SESSION_PATH.is_file()):
            raise FileNotFoundError("会话未指定或文件不存在")

        with SESSION_PATH.open("r", encoding="utf-8") as file:
            sessison_data = json.load(file)

        #/ 必须是字典且 messages 必须是列表
        if not isinstance(sessison_data, dict) or not isinstance(sessison_data.get("messages"), list):
            raise TypeError("会话文件格式损坏（缺少有效 messages 列表）")
        
        SESSION = sessison_data
    except Exception:
        CONFIG["session_id"] = ""
        SESSION_PATH = None
        with DEFAULT_SESSION_PATH.open("r", encoding="utf-8") as file:
            SESSION = json.load(file)

    character_id:str = CONFIG.get("current_character_id", "")
    CHARACTER_PATH:Path =BASE_DIR / "user_data"/"characters" / f"{character_id}"
    DEFAULT_CHARACTER_ID: str = "默认猫娘default_cat"
    DEFAULT_CHARACTER_PATH:Path =BASE_DIR / "assets" / "default"/"默认猫娘default_cat"/ "人设.md"
    CHARACTER_PROMPT:str
    try:
        character_id: str = CONFIG.get("current_character_id", "")
        CHARACTER_PATH: Path | None = (BASE_DIR / "user_data"/"characters" / f"{character_id}"/ "人设.md") if character_id else None

        #/ 优先检查用户自定义目录；若不存在，再检查是否为默认预设目录中的角色
        if not (CHARACTER_PATH and CHARACTER_PATH.is_file()):
            CHARACTER_PATH = (BASE_DIR / "assets" / "default" / f"{character_id}"/ "人设.md") if character_id else None
            if not (CHARACTER_PATH and CHARACTER_PATH.is_file()):
                raise FileNotFoundError("角色未指定或角色文件不存在")

        CHARACTER_PROMPT = CHARACTER_PATH.read_text(encoding="utf-8")

        #/ 校验角色设定是否为空
        if not CHARACTER_PROMPT.strip():
            raise ValueError("角色设定文件内容为空")

    except Exception:
        CONFIG["current_character_id"] = DEFAULT_CHARACTER_ID
        CHARACTER_PATH = DEFAULT_CHARACTER_PATH
        CHARACTER_PROMPT = DEFAULT_CHARACTER_PATH.read_text(encoding="utf-8")


    #/ 知识库目录跟着“对话角色”走，而不是当前选中的角色。
    #/
    #/ 当前选定的角色 config["current_character_id"] 与
    #/ 会话记录的角色 SESSION["character_id"] 是两个可以不同的东西：
    #/ 会话里的人设是创建时的快照。加载已有会话时，
    #/ 模型的上下文以对话角色为主，知识库也必须与那份快照对应，
    #/ 否则会出现"用甲角色的人设 + 检索乙角色的知识"。
    #/
    #/ 解析不到时为 None，不回退到默认角色：
    #/ 界面会跳过预检索，工具调用会明确提示知识库不可用。
    #/
    #/ 新建会话不在这里处理 —— 那时还没有会话记录，
    #/ 由 ui.py 建好会话后经 change_session() 解析，两处共用同一实现。
    SESSION_CHARACTER_DIR: Path | None = resolve_character_dir(
        BASE_DIR,
        str(SESSION.get("character_id", "")) if isinstance(SESSION, dict) else "",
    )

    ASSETS_TOOLS_PATH:Path =BASE_DIR / "assets" / "assets_tools.json"
    ASSETS_TOOLS: list[dict] | None = None
    try:
        if not ASSETS_TOOLS_PATH.is_file():
            raise FileNotFoundError("未找到系统工具文件")
            
        with ASSETS_TOOLS_PATH.open("r", encoding="utf-8") as file:
            ASSETS_TOOLS = json.load(file)
            
        if not isinstance(ASSETS_TOOLS, list):
            raise TypeError("系统工具文件格式损坏（缺少有效 assets_tools 列表）")
        if not all(isinstance(tool, dict) for tool in ASSETS_TOOLS):
            raise TypeError("系统工具列表中的每个元素必须是字典。")
        
    except Exception as exc:
        print(f"[提示] 读取系统工具文件异常（{exc}）。")
        ASSETS_TOOLS=None
        


    #/ 这里使用关键字实参 `dotenv_path=...`，明确告诉 load_dotenv 哪个参数被赋值。
    #/ `BASE_DIR / ".env"` 其语义相当于路径拼接，结果为当前脚本同目录下的 `.env` 路径。
    load_dotenv(dotenv_path=BASE_DIR / ".env")

    LLM_API_KEY: str | None = None
    LLM_BASE_URL: str | None = None
    LLM_MODEL: str | None = None
    CONFIG_ENV_ERROR: str | None = None

    try:
        LLM_API_KEY = model_connect.require_env("LLM_API_KEY")
        LLM_BASE_URL = model_connect.require_env("LLM_BASE_URL")
        LLM_MODEL = model_connect.require_env("LLM_MODEL")

    except RuntimeError as error:
        CONFIG_ENV_ERROR = str(error)

        # 保证三个配置要么全部有效，要么全部不可使用。
        print(f"获取环境变量（api key、base url、model）出错了，错误为：{error}")
        LLM_API_KEY = None
        LLM_BASE_URL = None
        LLM_MODEL = None

    appcontext=AppContext(
        base_dir=BASE_DIR,
        llm_api_key=LLM_API_KEY,
        llm_base_url=LLM_BASE_URL,
        llm_model=LLM_MODEL,
        embedding_model_dir=EMBEDDING_MODEL_DIR,
        config=CONFIG,
        config_env_error=CONFIG_ENV_ERROR,
        session=SESSION,
        session_character_dir=SESSION_CHARACTER_DIR,
        session_path=SESSION_PATH,
        character_path=CHARACTER_PATH,
        character_prompt=CHARACTER_PROMPT,
        assets_tools=ASSETS_TOOLS
    )

    #/ 预加载向量模型：放在进入全屏 TUI 之前。
    #/ 此刻还是普通终端模式，模型的加载进度条直接打印在命令行里，
    #/ 不会混进 TUI 画面破坏布局。
    print("向量化模型正在加载，请稍等...")
    try:
        asyncio.run(rag.preload_worldview_embedding_model(appcontext.embedding_model_dir))
    except Exception as error:
        print(f"\n[错误] 向量化模型加载失败：{error}")
        print("\n若是模型缺失，请先运行 \"下载向量化模型.bat\" 或者 \"download_embedding_model.py\"")
        raise SystemExit(1) from error


    try:
        exit_message = asyncio.run(ui.tavern_loop(appcontext))

    #/ 当 Ctrl+C 在 Application 完全接管按键之前/之外形成 KeyboardInterrupt 时，用这一分支兜底。
    except KeyboardInterrupt:
        exit_message = (
            "[系统] 已收到 Ctrl+C，离开酒馆。"
        )

    #/ EOFError 表示输入接口遇到文件结束条件；这里为异常关闭的标准输入提供兜底消息。
    except EOFError:
        exit_message = (
            "[系统] 输入流已关闭，离开酒馆。"
        )

    

    if appcontext.config.get("session_id") and appcontext.session:
        #/ f"{}"内使用单引号，兼容Python 3.11 或更早版本
        SESSION_PATH:Path=BASE_DIR / "user_data" / "sessions"/f"{appcontext.config['session_id']}"
        file_operate.write_json_atomic(SESSION_PATH,appcontext.session)

    #/ 原子写入
    file_operate.write_json_atomic(CONFIG_PATH,appcontext.config)

    
    #/ 放在 run_async() 返回后执行，可以让告别语显示在已经恢复的普通终端中。
    print(exit_message)



if __name__ == "__main__":
    main()