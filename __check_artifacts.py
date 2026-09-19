"""提交前检查：扫描源文件中的 HTML 实体残留与隐形 Unicode 字符。

用法：python check_artifacts.py
发现问题时退出码为 1，并打印文件、行号与上下文；干净时打印 OK。
"""

import pathlib
import re
import sys

# HTML 实体（复制网页内容时的典型残留）
ENTITY = re.compile(r"&#\d+;|&amp;|&lt;|&gt;|&quot;|&nbsp;")

# 隐形 Unicode 字符（渲染/复制链路的典型残留）
INVISIBLE = {
    "\u200b": "ZWSP 零宽空格",
    "\u200c": "ZWNJ 零宽不连字",
    "\u200d": "ZWJ 零宽连接符",
    "\u2060": "WJ 字词连接符",
    "\ufeff": "BOM/零宽不换行空格",
    "\u00a0": "不换行空格",
}

# 检查范围：项目内这些扩展名的文本文件
CHECK_SUFFIXES = {".py", ".md", ".txt", ".json", ".bat", ".spec", ".example", ""}
SKIP_DIRS = {"build", "dist", "dist_probe", ".venv", "__pycache__", ".git",
             "granite-embedding-r2", "hooks"}

problems: list[str] = []
checked = 0

for path in sorted(pathlib.Path(".").rglob("*")):
    if path.is_dir():
        continue
    if any(part in SKIP_DIRS for part in path.parts):
        continue
    if path.name == "check_artifacts.py":
        continue  # 跳过自身：本脚本的检测正则里就包含实体字面量，会自指误报
    if path.suffix not in CHECK_SUFFIXES:
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError):
        continue  # 非文本文件，跳过

    checked += 1
    for lineno, line in enumerate(text.splitlines(), 1):
        for match in ENTITY.finditer(line):
            problems.append(f"{path}:{lineno} HTML实体 [{match.group(0)}] {line.strip()[:70]}")
        for ch, name in INVISIBLE.items():
            if ch in line:
                col = line.index(ch) + 1
                problems.append(f"{path}:{lineno}:{col} 隐形字符 [{name}] {line.strip()[:70]}")

if problems:
    print(f"发现 {len(problems)} 处问题：")
    for p in problems:
        print(" ", p)
    sys.exit(1)

print(f"OK：已检查 {checked} 个文件，无 HTML 实体与隐形字符残留。")
