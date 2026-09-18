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

    # 将字符串路径转换为 Path 对象。
    target_path = Path(file_path)

    # 如果父目录不存在，则递归创建。
    target_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # 临时文件必须创建在目标文件的同一个目录中。
    # 这样可以保证二者位于同一文件系统，
    # os.replace() 才能完成可靠的原子替换。
    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",

            # 临时文件与目标文件放在同一目录。
            dir=target_path.parent,

            # 例如目标是 conversation.json，
            # 临时文件可能类似：
            # .conversation.json.abcd1234.tmp
            prefix=f".{target_path.name}.",
            suffix=".tmp",

            # 退出 with 后不自动删除。
            # 因为稍后需要使用它替换目标文件。
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)

            json.dump(
                data,
                temporary_file,
                ensure_ascii=False,
                indent=2,
            )

            # 在文件末尾增加换行，使文本文件格式更整洁。
            temporary_file.write("\n")

            # 将 Python 自己的写入缓冲区推送给操作系统。
            temporary_file.flush()

            # 请求操作系统把文件数据刷新到磁盘。
            os.fsync(temporary_file.fileno())

        # 此时临时文件已经关闭。
        #
        # os.replace(source, destination)：
        # 使用 source 替换 destination。
        # 如果 destination 已经存在，也会将其覆盖。
        os.replace(
            temporary_path,
            target_path,
        )

    except Exception:
        # 如果序列化、写入或者替换失败，
        # 尝试删除未完成的临时文件。
        if temporary_path is not None:
            temporary_path.unlink(
                missing_ok=True,
            )

        # 原样重新抛出当前异常，让调用者知道保存失败。
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

    #/ 将字符串路径转换为 Path 对象。
    target_path = Path(file_path)

    #/ 如果目标文件的父目录不存在，就递归创建。
    target_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    #/ 保存临时文件路径。
    #/ 在临时文件真正创建前，它还不存在，因此初始值是 None。
    temporary_path: Path | None = None

    try:
        #/ 在目标文件所在目录创建临时文件。
        #/ 临时文件和目标文件位于同一个文件系统中，
        #/ os.replace() 才能可靠地进行原子替换。
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",

            #/ 统一使用 \n 作为文本换行符。
            newline="\n",

            #/ 临时文件与目标文件放在同一目录。
            dir=target_path.parent,

            #/ 临时文件名称的开头部分。
            prefix=f".{target_path.name}.",

            #/ 临时文件扩展名。
            suffix=".tmp",

            #/ 关闭临时文件后不自动删除，
            #/ 因为稍后要用它替换目标文件。
            delete=False,
        ) as temporary_file:
            temporary_path = Path(
                temporary_file.name
            )

            #/ 将完整 Markdown 字符串写入临时文件。
            temporary_file.write(
                markdown_content
            )

            #/ 将 Python 内部缓冲区的数据交给操作系统。
            temporary_file.flush()

            #/ 请求操作系统将文件内容刷新到磁盘。
            os.fsync(
                temporary_file.fileno()
            )

        #/ 帮助类型检查器确认临时文件路径已经得到赋值。
        assert temporary_path is not None

        #/ 使用临时文件替换目标文件。
        #/
        #/ 目标文件不存在：创建目标文件。
        #/ 目标文件已经存在：完整替换原文件。
        os.replace(
            temporary_path,
            target_path,
        )

    finally:
        #/ 如果写入或替换过程中发生异常，
        #/ 尝试删除遗留下来的临时文件。
        #/
        #/ 如果 os.replace() 已经成功，临时路径已经不存在，
        #/ missing_ok=True 会让此处不报错。
        if temporary_path is not None:
            temporary_path.unlink(
                missing_ok=True,
            )