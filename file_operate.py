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
    """
    将 Python 对象以 JSON 格式原子写入文件。

    原子写入流程：
        1. 在目标文件所在目录创建临时文件；
        2. 将完整 JSON 写入临时文件；
        3. 刷新 Python 和操作系统的写入缓冲区；
        4. 使用 os.replace() 将临时文件替换目标文件。

    如果程序在完成替换前中断，原文件通常仍然完整。
    读取程序看到的会是完整的旧文件或者完整的新文件，
    而不是正在写入一半的文件。

    参数：
        file_path:
            目标 JSON 文件路径。

        data:
            要保存的 Python 对象。
            通常由 dict、list、str、int、float、bool、None 组成。
    """
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
    """
    将 文本格式（如 Markdown ）文本原子写入目标文件。

    工作流程：
        1. 在目标文件所在目录创建临时文件；
        2. 将完整 Markdown 内容写入临时文件；
        3. 刷新 Python 和操作系统的写入缓冲区；
        4. 使用 os.replace() 将临时文件替换目标文件。

    如果写入过程中发生异常，原来的目标文件不会被写坏。

    参数：
        file_path:
            目标 Markdown 文件路径。

        markdown_content:
            要写入文件的完整 Markdown 字符串。
    """
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