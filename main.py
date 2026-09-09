from __future__ import annotations

from typing import Any
import asyncio
import json
from pathlib import Path
from dotenv import load_dotenv

import model_connect
import ui
import file_operate
from app_context import AppContext


def main() -> None:
    """
    程序的同步顶层主入口。
    
    职责：
    1. 使用 asyncio.run 初始化全新的事件循环并驱动 tavern_loop。
    2. 针对操作系统级物理信号和控制台异常进行顶层拦截兜底。
    3. 在退出全屏缓冲区后安全输出退出日志。
    """
    BASE_DIR: Path = Path(__file__).resolve().parent

    CONFIG_PATH: Path = BASE_DIR / "user_data" / "config.json"
    DEFAULT_CONFIG_PATH: Path = BASE_DIR / "assets" / "default" / "default_config.json"
    CONFIG: dict[str, Any]
    try:
        if not CONFIG_PATH.is_file():
            raise FileNotFoundError("未找到用户配置文件")
            
        with CONFIG_PATH.open("r", encoding="utf-8") as file:
            config_data = json.load(file)
            
        if not isinstance(config_data, dict):
            raise TypeError("config.json 根结构必须是键值字典")
            
        CONFIG = config_data
    except Exception as exc:
        print(f"[提示] 读取配置文件异常（{exc}），已回退至默认配置。")
        with DEFAULT_CONFIG_PATH.open("r", encoding="utf-8") as file:
            CONFIG = json.load(file)

    SESSION: dict[str, Any] | None = None
    DEFAULT_SESSION_PATH: Path = BASE_DIR / "assets" / "default" / "default_session.json"
    try:
        session_id: str = CONFIG.get("session_id", "")
        SESSION_PATH: Path | None = (BASE_DIR / "user_data" / "sessions" / f"{session_id}") if session_id else None
        if not (session_id and SESSION_PATH.is_file()):
            raise FileNotFoundError("会话未指定或文件不存在")

        with SESSION_PATH.open("r", encoding="utf-8") as file:
            sessison_data = json.load(file)

        if not isinstance(sessison_data, dict) or not isinstance(sessison_data.get("messages"), list):
            raise TypeError("会话文件格式损坏（缺少有效 messages 列表）")
        
        SESSION = sessison_data
    except Exception:
        CONFIG["session_id"] = ""
        SESSION_PATH = None
        with DEFAULT_SESSION_PATH.open("r", encoding="utf-8") as file:
            SESSION = json.load(file)

    DEFAULT_CHARACTER_ID: str = "默认猫娘default_cat.md"
    DEFAULT_CHARACTER_PATH: Path = BASE_DIR / "assets" / "default" / "默认猫娘default_cat.md"
    CHARACTER_PATH: Path
    CHARACTER_PROMPT: str
    try:
        character_id: str = CONFIG.get("current_character_id", "")
        target_path: Path | None = (BASE_DIR / "user_data" / "characters" / f"{character_id}") if character_id else None

        if not (target_path and target_path.is_file()):
            target_path = (BASE_DIR / "assets" / "default" / f"{character_id}") if character_id else None
            if not (target_path and target_path.is_file()):
                raise FileNotFoundError("角色未指定或角色文件不存在")

        CHARACTER_PROMPT = target_path.read_text(encoding="utf-8")

        if not CHARACTER_PROMPT.strip():
            raise ValueError("角色设定文件内容为空")

        CHARACTER_PATH = target_path

    except Exception:
        CONFIG["current_character_id"] = DEFAULT_CHARACTER_ID
        CHARACTER_PATH = DEFAULT_CHARACTER_PATH
        CHARACTER_PROMPT = DEFAULT_CHARACTER_PATH.read_text(encoding="utf-8")

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
        print(f"获取环境变量（api key、base url、model）出错了，错误为：{error}")
        LLM_API_KEY = None
        LLM_BASE_URL = None
        LLM_MODEL = None

    appcontext = AppContext(
        base_dir=BASE_DIR,
        llm_api_key=LLM_API_KEY,
        llm_base_url=LLM_BASE_URL,
        llm_model=LLM_MODEL,
        config=CONFIG,
        config_env_error=CONFIG_ENV_ERROR,
        session=SESSION,
        session_path=SESSION_PATH,
        character_path=CHARACTER_PATH,
        character_prompt=CHARACTER_PROMPT
    )

    try:
        exit_message = asyncio.run(ui.tavern_loop(appcontext))
    except KeyboardInterrupt:
        exit_message = (
            "[系统] 已收到 Ctrl+C，离开酒馆。"
        )
    except EOFError:
        exit_message = (
            "[系统] 输入流已关闭，离开酒馆。"
        )

    if appcontext.config.get("session_id") and appcontext.session:
        SESSION_PATH: Path = BASE_DIR / "user_data" / "sessions" / f"{appcontext.config['session_id']}"
        file_operate.write_json_atomic(SESSION_PATH, appcontext.session)

    file_operate.write_json_atomic(CONFIG_PATH, appcontext.config)

    print(exit_message)


if __name__ == "__main__":
    main()