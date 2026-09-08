from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_json_atomic(
    file_path: str | Path,
    data: Any,
) -> None:
    target_path = Path(file_path)

    target_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target_path.parent,
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)

            json.dump(
                data,
                temporary_file,
                ensure_ascii=False,
                indent=2,
            )

            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        os.replace(
            temporary_path,
            target_path,
        )

    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(
                missing_ok=True,
            )
        raise


def write_markdown_or_text_atomic(
    file_path: str | Path,
    markdown_content: str,
) -> None:
    target_path = Path(file_path)

    target_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target_path.parent,
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(
                temporary_file.name
            )

            temporary_file.write(
                markdown_content
            )

            temporary_file.flush()
            os.fsync(
                temporary_file.fileno()
            )

        assert temporary_path is not None

        os.replace(
            temporary_path,
            target_path,
        )

    finally:
        if temporary_path is not None:
            temporary_path.unlink(
                missing_ok=True,
            )