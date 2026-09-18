from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from openai import AsyncOpenAI

from datetime import datetime, timedelta, timezone

@dataclass(
    slots=True,
)
class AppContext:
    """
    当前程序运行过程中需要共享的上下文数据。

    slots=True：
            只允许使用类中声明过的字段，
            可以减少误写属性名称的问题。
    """
    #/ 带默认值的参数必须排最后
    base_dir: Path
    #/ repr=False 可以避免打印 settings 时直接显示 API Key。
    #/ 这并不代表 API Key 被加密，只是不加入自动生成的字符串表示。
    llm_api_key: str | None = field(
        repr=False,
    )

    llm_base_url: str | None
    llm_model: str | None

    #/ 从 config.json 中读取的可变配置。
    config: dict[str, Any]

    config_env_error:str | None

    embedding_model_dir:Path

    character_path: Path
    #/ 从角色 Markdown 文件中读取的完整角色设定文本。
    character_prompt: str

    session:dict[str, Any]|None=None

    session_character_dir: Path|None=None
    
    session_path:Path | None = None

    assets_tools:list |None=None

    llm_client: AsyncOpenAI | None = None

    debug_text:list[str] =None


    

    
    def change_config(
        self,
        new_config: dict[str, Any],
    ) -> None:
        """
        更新config。

        参数：
            new_config:
                新的 config 。
        """
        self.config = new_config

    def change_session(
        self,
        new_session: dict[str, Any],
        new_session_id:str,
    ) -> None:
        """
        更新 session、session_path、config["session_id"] 和 session_character_dir。

        参数：
            new_session:
                新的 session 。

            new_session_id:
                新的会话文件名，例如“角色名_0x1a2b3c.json”。
        """
        self.session = new_session
        self.session_path=self.base_dir / "user_data" / "sessions"/f"{new_session_id}"
        self.config["session_id"]=new_session_id

        #/ 知识库目录跟着“会话角色”走，而不是当前选中的角色。
        #/ 两者可以不同：会话里的人设是创建时的快照，
        #/ 知识库必须与那份快照对应，否则会检索到别人的世界。
        #/ 这里与 main.py 启动时共用同一个解析函数，避免两处逻辑分叉。
        self.session_character_dir = resolve_character_dir(
            self.base_dir,
            str(new_session.get("character_id", "")),
        )

    def change_character(
        self,
        new_character_id: str | Path,
    ) -> None:
        """
        切换当前角色，并同步更新character_path、character_prompt和config["current_character_id"]。
        不会修改 session_character_dir

        参数：
            new_character_id:
                新角色人设 Markdown 文件的目录文件夹名称。
        """

        try:
            new_character_path: Path | None = (
                (self.base_dir / "user_data" / "characters" / new_character_id/"人设.md")
            )
            if not (new_character_path and new_character_path.is_file()):
                new_character_path = (
                    (self.base_dir / "assets" / "default" /  new_character_id/"人设.md")
                )
                if not (new_character_path and new_character_path.is_file()):
                    raise FileNotFoundError("角色目录未指定或不存在")
    
            self.character_path = new_character_path
    
        except Exception:
            return

        #/ 先完整读取新文件。
        #/ 如果读取失败，下面的字段都不会改变，
        #/ AppContext 仍然保留原来的有效角色。
        new_prompt: str = new_character_path.read_text(
            encoding="utf-8",
        )
        self.character_prompt = new_prompt

        #/ 在配置中只保存文件名，而不是整个绝对路径。
        self.config["current_character_id"] = (
            new_character_id
        )

def resolve_character_dir(
    base_dir: Path,
    character_id: str,
) -> Path | None:
    """
    按角色 id 解析角色目录（源文档与知识库索引所在目录）。

    查找顺序：
        1. 用户自定义角色目录：user_data/characters/<角色 id>
        2. 程序自带的默认角色目录：assets/default/<角色 id>

    参数：
        base_dir:
            项目根目录。

        character_id:
            角色目录名，例如“默认猫娘default_cat”。
            传入空字符串时直接返回 None。

    返回值：
        找到时返回目录 Path，找不到时返回 None。
        返回 None 而不是回退到某个默认角色，
        是为了避免出现“用甲角色的人设、检索乙角色知识”的错配。
        由调用方决定怎么降级（界面会跳过预检索）。
    """
    if not character_id:
        return None

    for parent in (
        base_dir / "user_data" / "characters",
        base_dir / "assets" / "default",
    ):
        candidate: Path = parent / character_id
        if candidate.is_dir():
            return candidate

    return None


def get_current_time_iso() -> str:
    """
    返回带有 UTC+8 时区信息的当前时间字符串。

    示例：
        2026-09-07T20:30:00+08:00
    """
    #/ timezone 类用来表示相对于 UTC 有固定偏移量的时区。此处偏移量为8小时。
    CHINA_TIMEZONE = timezone(
        timedelta(hours=8)
    )
    #/ datetime.now(...)：获取该时区的当前日期时间
    current_time: datetime = datetime.now(
        CHINA_TIMEZONE
    )
    #/ isoformat()：把日期时间实例转换成字符串
    #/ sep：日期与时间之间使用什么分隔符，默认是 "T"。
    #/ timespec：生成的字符串保留到哪个时间单位
    #/ 返回字符串如："2026-09-07T20:30:00+08:00"
    return current_time.isoformat(
        timespec="seconds",
    )