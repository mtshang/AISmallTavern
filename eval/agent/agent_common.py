"""工具调用测评（agent 类）的公共设施。

与 retrieval/common.py 分开维护：三大类测评各自自足，
避免跨子文件夹的 import 依赖。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

#/ 项目根目录 = eval/agent/ 向上三级（main.py 所在目录）。
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

#/ eval/ 根目录：中文报告统一输出到这里。
EVAL_ROOT: Path = Path(__file__).resolve().parent.parent

#/ 本大类目录与结果目录。
EVAL_DIR: Path = Path(__file__).resolve().parent
RESULTS_DIR: Path = EVAL_DIR / "results"

#/ 默认角色目录与嵌入模型目录（与 main.py 源码运行时一致）。
CHARACTER_DIR: Path = PROJECT_ROOT / "assets" / "default" / "默认猫娘default_cat"
MODEL_DIR: Path = PROJECT_ROOT / "granite-embedding-r2"

#/ 真实工具定义（与生产完全相同的 assets_tools.json）。
ASSETS_TOOLS_PATH: Path = PROJECT_ROOT / "assets" / "assets_tools.json"


def setup_console() -> None:
    """让 Windows 控制台/重定向输出稳定使用 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def load_assets_tools() -> list[dict]:
    """读取生产使用的工具定义列表。"""
    tools = json.loads(ASSETS_TOOLS_PATH.read_text(encoding="utf-8"))
    if not isinstance(tools, list):
        raise ValueError("assets_tools.json 根结构必须是列表。")
    return tools


def load_character_prompt() -> str:
    """读取默认角色的人设（作为 system 消息，与生产一致）。"""
    return (CHARACTER_DIR / "人设.md").read_text(encoding="utf-8").strip()


def load_llm_env() -> tuple[str, str, str]:
    """加载 .env 中的三项模型配置，返回 (api_key, base_url, model)。

    只编程式读取环境变量，不打印、不落盘任何凭证内容。
    缺失时抛 RuntimeError（与生产 require_env 的提示一致）。
    """
    from dotenv import load_dotenv

    import model_connect

    load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

    try:
        api_key = model_connect.require_env("LLM_API_KEY")
        base_url = model_connect.require_env("LLM_BASE_URL")
        model = model_connect.require_env("LLM_MODEL")
    except RuntimeError as error:
        raise RuntimeError(
            f"真实调用测评需要模型配置：{error}"
        ) from error

    return api_key, base_url, model


def make_client(api_key: str, base_url: str):
    """构造真实调用的 AsyncOpenAI 客户端（一次性，用完关闭）。"""
    from openai import AsyncOpenAI

    return AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        max_retries=2,
        timeout=60.0,
    )


def safe_endpoint(base_url: str) -> str:
    """报告展示用的接口地址：只保留域名部分，不暴露完整路径。"""
    if not base_url:
        return "未配置"
    return base_url.split("://")[-1].split("/")[0]


def save_json(name: str, data: dict) -> Path:
    """把结果 JSON 写入 agent/results/。"""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / name
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def load_result(name: str) -> dict | None:
    """读取 results/ 下已有的结果 JSON（报告可从数据单独重生成）。"""
    path = RESULTS_DIR / name
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
