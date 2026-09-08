from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from datetime import datetime, timedelta, timezone

@dataclass(
    slots=True,
)
class AppContext:
    base_dir: Path
    llm_api_key: str | None = field(
        repr=False,
    )

    llm_base_url: str | None
    llm_model: str | None

    config: dict[str, Any]

    config_env_error: str | None

    character_path: Path
    character_prompt: str

    session: dict[str, Any] | None = None
    
    session_path: Path | None = None

    def change_config(
        self,
        new_config: dict[str, Any],
    ) -> None:
        self.config = new_config

    def change_session(
        self,
        new_session: dict[str, Any],
        new_session_id: str,
    ) -> None:
        self.session = new_session
        self.session_path = self.base_dir / "data" / "sessions" / f"{new_session_id}"
        self.config["session_id"] = new_session_id

    def change_character(
        self,
        new_character_path: str | Path,
    ) -> None:
        new_path = Path(
            new_character_path
        )

        if not new_path.is_file():
            raise FileNotFoundError(
                f"角色文件不存在：{new_path}"
            )

        new_prompt: str = new_path.read_text(
            encoding="utf-8",
        )

        self.character_path = new_path
        self.character_prompt = new_prompt

        self.config["current_character_id"] = (
            new_path.name
        )

def get_current_time_iso() -> str:
    CHINA_TIMEZONE = timezone(
        timedelta(hours=8)
    )
    current_time: datetime = datetime.now(
        CHINA_TIMEZONE
    )
    return current_time.isoformat(
        timespec="seconds",
    )