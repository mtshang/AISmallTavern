import re
import hashlib
import json
import os
import tempfile
from pathlib import Path
import asyncio

import faiss
import numpy as np

from file_operate import write_json_atomic
from functools import lru_cache

def kb_preprocess(text: str) -> dict:
    """
    按 Markdown 标题组织正文，并按字符数限制生成文本块。

    参数：
        text:
            待分块的 Markdown 字符串。
            Setext 标题可先通过 strip_dividers() 转成 ATX 标题。

    返回值：
        以块编号为键的字典，例如：
        {
            1: {
                "title_path": ["世界观", "地理"],
                "content": "银爪城位于大陆北境。",
            },
        }

    规则：
        1. 遇到新标题时，先处理上一节正文，再更新标题栈。
        2. 正文元素超过 max_chars 时，先按字符位置拆开。
        3. 加入下一片会超限时，先保存当前块，再开始新块。
        4. 保留第一个标题前的介绍，其 title_path 为空列表。
        5. 不保存只有空白的块。
        6. 最后一个章节也会被处理。

    范围：
        这一版完成基本的 ATX 标题识别和字符数分块。
        尚未加入按句号、逗号择点，以及表格、代码块的专门处理。
    """
    max_chars = 350

    #/ 每个元素是一行，保留原来的换行符。
    #/ 这样后面直接拼接正文时，不会把相邻两行的文字粘在一起。
    pre_chunk: list[str] = text.splitlines(keepends=True)

    #/ 每项保存“标题级别、标题文字”。
    #/ 例如：
    #/ [(1, "世界观"), (2, "魔法"), (3, "力量的代价")]
    title_stack: list[tuple[int, str]] = []

    #/ 收集当前标题下尚未处理的正文。
    #/ 由于前面使用 splitlines()，这里的每个元素对应原文的一行。
    content: list[str] = []

    #/ 最终返回的所有文本块。
    chunk_dict: dict = {}

    #/ 识别 "# 标题" 到 "###### 标题"。
    #/
    #/  {0,3}：行首允许 0～3 个普通空格。
    #/ (#{1,6})：捕获连续的 1～6 个 "#"。
    #/ [ \t]+："#" 后要求至少一个空格或制表符。
    #/ (.+)：捕获后面的标题文字。
    #/
    #/ 后面使用 fullmatch()，要求整行符合这条规则。
    heading_re = re.compile(r" {0,3}(#{1,6})[ \t]+(.+)")

    def save_chunk(chunk_text: str) -> None:
        """
        将一个已经组装好的正文块加入 chunk_dict。
        使用调用此函数时的标题栈生成标题路径。
        """
        #/ 空字符串或只有空白的字符串不生成文本块。
        #/ strip() 这里只用来判断，实际保存时仍保留原正文。
        if not chunk_text.strip():
            return

        #/ 编号从 1 开始，随已保存的块数递增。
        chunk_id = len(chunk_dict) + 1

        chunk_dict[chunk_id] = {
            #/ 从标题栈中提取标题文字，创建一个新的列表。
            #/ 后面修改 title_stack，不会改变已经保存的标题路径。
            "title_path": [
                title
                for level, title in title_stack
            ],
            "content": chunk_text,
        }

    def flush_content() -> None:
        """
        遍历当前 content，拆分并合并正文，保存后清空 content。
        """
        #/ 当前正在累积、尚未保存的正文块。
        current_text = ""

        for text_part in content:
            #/ 按 max_chars 的步长遍历当前元素。
            #/
            #/ 如果长度为 200，start 只会取 0。
            #/ 如果长度为 720，start 依次取 0、350、700。
            #/
            #/ 因此短元素保持完整；
            #/ 超长元素会被切成若干片，每片不超过 max_chars。
            for start in range(0, len(text_part), max_chars):
                piece = text_part[start:start + max_chars]

                #/ 先判断，再拼接。
                #/ 如果加入这一片会超限，就先保存已经累积的正文。
                #/ 使用 ">"，所以刚好等于 max_chars 时仍允许合并。
                if len(current_text) + len(piece) > max_chars:
                    save_chunk(current_text)

                    #/ 已保存的内容不再参与下一块的累积。
                    current_text = ""

                #/ 此时当前块一定能够容纳 piece。
                #/ 如果上面刚保存过，这一片就成为新块的开头。
                current_text += piece

        #/ 遍历结束后，通常还会剩下一个没有触发“超限”的块。
        #/ 即使它不足 max_chars，也必须保存。
        #/ 如果为空，save_chunk() 会自行跳过。
        save_chunk(current_text)

        #/ 当前章节的正文已经全部处理，清空列表。
        content.clear()

    for line in pre_chunk:
        #/ 标题识别不需要行末换行符。
        #/ 这里没有修改 line，后面保存正文时仍可使用原始行。
        heading = heading_re.fullmatch(line.rstrip("\r\n"))

        if heading:
            #/ 必须先处理旧正文，再修改标题栈。
            #/ 否则旧正文会被错误地保存到新标题下面。
            flush_content()

            #/ 第一个捕获分组是 "#"，数量就是标题级别。
            #/ 例如 "### 魔法" → t_num = 3。
            t_num = len(heading.group(1))

            #/ 第二个捕获分组是标题文字。
            new_title = heading.group(2).strip()

            #/ 弹出与新标题同级或比它更深的标题。
            #/ 保留下来的标题，就是新标题的上级路径。
            #/
            #/ 例如：
            #/ 原栈：[(1, "世界观"), (2, "魔法"), (3, "代价")]
            #/ 新标题：## 地理
            #/ 先弹出三级“代价”，再弹出二级“魔法”。
            while title_stack and title_stack[-1][0] >= t_num:
                title_stack.pop()

            title_stack.append((t_num, new_title))

        else:
            #/ 普通正文先收集，等遇到下一个标题时统一处理。
            #/ 第一个标题之前的介绍也会进入这里。
            content.append(line)

    #/ 文件结束后，不会再出现新标题来触发处理。
    #/ 因此需要主动处理最后一节，否则最后的正文会丢失。
    flush_content()

    return chunk_dict


def kb_title_to_content(text: str) -> dict[str, str]:
    """
    将 Markdown 文本整理为“标题路径 → 完整正文”的字典。

    参数：
        text:
            Markdown 字符串。
            本函数按基本 ATX 标题识别，例如 "# 世界观"、"## 地理"。
            标题应有文字。

    返回值：
        键为标题路径字符串，值为该路径下的完整正文。

        例如：
        {
            "": "第一个标题前的介绍。",
            "世界观>地理": "这一节的完整正文。",
        }

    处理规则：
        1. 遇到新标题，先保存上一节正文，再更新标题栈。
        2. 不限制正文长度，不执行分块。
        3. 相同标题路径再次出现时，追加正文并补一个换行。
        4. 不保存只有空白的正文。
        5. 保留正文原有的换行符。

    范围：
        使用基本的行级标题识别。
        尚未专门处理代码围栏中的标题样式文本等复杂 Markdown 结构。
    """
    #/ 保存“标题级别、标题文字”，用于维护当前标题层级。
    title_stack: list[tuple[int, str]] = []

    #/ 收集当前标题下的正文，每个元素是原文的一行。
    content: list[str] = []

    #/ 最终返回的字典：标题路径字符串 → 完整正文字符串。
    title_content: dict[str, str] = {}

    #/ 第一个捕获分组是 1～6 个 "#"。
    #/ 第二个捕获分组是标题文字。
    #/ "#" 与标题文字之间要求有空格或制表符。
    heading_re = re.compile(r" {0,3}(#{1,6})[ \t]+(.+)")

    def flush_content() -> None:
        """保存当前收集的正文，然后清空正文列表。"""

        #/ 每一行已经带有原来的换行符，因此直接连接即可。
        body = "".join(content)

        #/ strip() 只用于判断是否有实际内容。
        #/ 保存时仍然使用 body，保留正文原有的空白和换行。
        if body.strip():
            #/ 从标题栈中提取标题文字，并用 " > " 连接。
            #/ 例如：
            #/ [(1, "世界观"), (2, "地理")]
            #/ → "世界观>地理"
            #/ 如果标题栈为空，join() 返回空字符串。
            #/ 这正好用来保存第一个标题前的介绍。
            title_path = ">".join(
                title
                for level, title in title_stack
            )

            if title_path in title_content:
                #/ 相同路径再次出现时合并正文，避免覆盖已有内容。
                #/ 前一次正文通常已以换行结束，
                #/ 再补一个换行，使两次收集的正文之间留有空行。
                title_content[title_path] += "\n" + body
            else:
                title_content[title_path] = body

        #/ 当前正文已经处理完，准备收集下一节。
        content.clear()

    #/ 保留每行末尾的换行符，方便之后还原正文。
    for line in text.splitlines(keepends=True):
        #/ 标题识别时去掉末尾换行，但不修改原始 line。
        heading = heading_re.fullmatch(line.rstrip("\r\n"))

        if heading:
            #/ 必须先用旧标题路径保存正文，再更新标题栈。
            flush_content()

            #/ "#" 的数量表示标题级别。
            level = len(heading.group(1))

            #/ 取出标题文字，去掉两端的空白。
            title = heading.group(2).strip()

            #/ 弹出与新标题同级或比它更深的标题。
            #/ 比较实际级别，因此也能处理从一级直接跳到三级的情况。
            while title_stack and title_stack[-1][0] >= level:
                title_stack.pop()

            title_stack.append((level, title))

        else:
            #/ 普通正文原样收集。
            content.append(line)

    #/ 文件结束后，主动保存最后一节正文。
    flush_content()

    return title_content

def strip_dividers(text: str) -> str:
    """
    将单行 Setext 标题转换成 ATX 标题，并删除普通 Markdown 分隔线。

    参数：
        text:
            待处理的 Markdown 字符串。

    返回值：
        处理后的 Markdown 字符串。

    处理规则：
        1. “标题文字 + 下一行 ===”转换成一级标题。
        2. “标题文字 + 下一行 ---”转换成二级标题。
        3. 普通分隔线删除符号，但保留原有换行作为段落边界。
        4. 支持的代码围栏内，所有内容原样保留。
        5. 其他内容按原来的顺序加入返回结果。

    范围：
        按“单行标题文字 + 下一行下划线”的约定处理。
        这是有限的行级处理，不是完整 Markdown 解析器，
        不完整支持多行 Setext 标题、HTML 块和嵌套结构。
    """

    #/ 将字符串拆成列表，每个元素对应一行
    #/ keepends=True 表示保留每行末尾的换行符
    lines = text.splitlines(keepends=True)

    #/ 依次收集处理后的文本，最后再拼成一个字符串。
    result: list[str] = []

    #/ re.compile() 将正则规则创建为可重复使用的匹配对象。
    #/
    #/ r"..." 是 Python 原始字符串：
    #/     例如其中的 \t 会交给正则引擎解释为制表符。
    #/
    #/  {0,3}：
    #/     开头允许有 0～3 个普通空格。
    #/     {0,3} 限制的是它前面的那个空格字符。
    #/
    #/ (=+|-+)：
    #/     + 表示前面的字符出现一次或多次。
    #/     | 表示“或者”。
    #/     因此这里接受连续的 "=" 或连续的 "-"，不接受混合的 "=-="。
    #/     括号还会把匹配到的符号保存为第一个捕获分组。
    #/
    #/ [ \t]*：
    #/     方括号表示从其中选择一个字符：普通空格或者制表符。
    #/     * 表示前面的规则重复零次或多次。
    #/     因此行尾可以有任意数量的空格、制表符，也可以没有。
    underline_re = re.compile(r" {0,3}(=+|-+)[ \t]*")

    #/ 识别普通 Markdown 分隔线。
    #/
    #/ (?:...)：
    #/     将内部规则作为一个整体，但不保存为捕获分组。
    #/     这里仅需判断是否匹配，不需要通过 group() 取出内部内容。
    #/
    #/ \*：
    #/     匹配字面上的星号 "*"。
    #/     因为 "*" 在正则里本身表示重复，所以这里需要用反斜杠转义。
    #/
    #/ (?:\*[ \t]*){3,}：
    #/     “一个星号 + 零个或多个空白”这一组至少重复三次。
    #/     因此 "***"、"* * *"、"****" 都符合。
    #/
    #/ 另外两条分支同理，分别匹配 "-" 和 "_"。
    #/ 三个分支通过 | 连接，因此必须使用同一种分隔符。
    #/
    #/ Python 会自动拼接括号内相邻的字符串字面量。
    #/ 下面虽然写成多行，传给 compile() 的仍然是一个完整字符串。
    divider_re = re.compile(
        r" {0,3}(?:"
        r"(?:\*[ \t]*){3,}|"
        r"(?:-[ \t]*){3,}|"
        r"(?:_[ \t]*){3,}"
        r")"
    )

    #/ 识别不适合直接当作“普通标题文字”的行首结构。
    #/
    #/  {4}：
    #/     以四个普通空格开头，可能是缩进代码。
    #/
    #/  *\t：
    #/     零个或多个普通空格后跟一个制表符，也保守地排除。
    #/
    #/  {0,3}(?:...)：
    #/     下面几类结构前面允许有 0～3 个普通空格：
    #/
    #/     #{1,6}(?:[ \t]|$)
    #/         1～6 个 "#"，后面是空白或字符串结束，表示已有 ATX 标题。
    #/         $ 表示字符串结束的位置。
    #/
    #/     > 或 <
    #/         排除引用起始行和可能的 HTML 起始行。
    #/
    #/     [-+*](?:[ \t]|$)
    #/         "-", "+" 或 "*" 后面接空白或结束，可能是无序列表项。
    #/         字符放在这种方括号集合中时，"+"、"*" 按字面字符匹配。
    #/
    #/     [0-9]{1,9}[.)](?:[ \t]|$)
    #/         1～9 位数字，后跟 "." 或 ")"，再接空白或结束，
    #/         用来识别 "1. 内容"、"2) 内容" 等有序列表项。
    block_start_re = re.compile(
        r"(?: {4}| *\t| {0,3}(?:"
        r"#{1,6}(?:[ \t]|$)|>|<|"
        r"[-+*](?:[ \t]|$)|"
        r"[0-9]{1,9}[.)](?:[ \t]|$)"
        r"))"
    )

    #/ fence_char 表示当前代码围栏使用的符号。
    #/ 空字符串表示目前不在代码围栏内。
    #/ 进入围栏后，它会变成反引号 "`" 或波浪号 "~"。
    fence_char = ""

    #/ 记录开始围栏的符号数量，用于判断后面是否真正关闭了围栏。
    fence_length = 0

    #/ 当前正在处理的行下标，从 0 开始。
    i = 0

    while i < len(lines):
        line = lines[i]

        #/ 取出这一行的内容，去掉末尾的回车符和换行符。
        #/ rstrip("\r\n") 不会删除正文末尾的普通空格。
        body = line.rstrip("\r\n")

        #/ 从正文结束的位置切到行末，取回原有换行符。
        #/ 例如：
        #/     line = "正文\r\n"
        #/     body = "正文"
        #/     newline = "\r\n"
        #/ 文件最后一行如果没有换行符，这里得到空字符串。
        newline = line[len(body):]

        #/ 非空字符串在 if 条件中视为真。
        #/ 因此 fence_char 非空，说明当前正在代码围栏内部。
        if fence_char:
            #/ 代码内容直接保留，不转换其中的标题，也不删除分隔线。
            result.append(line)

            #/ 构造结束围栏的匹配规则。
            #/
            #/ rf"..." 同时使用：
            #/     r：原始字符串。
            #/     f：把 {...} 内的 Python 表达式结果插入字符串。
            #/
            #/ f 字符串里的 {{ 和 }} 会生成字面的 { 和 }，
            #/ 这样就可以在结果中保留正则表达式的重复次数语法。
            #/
            #/ re.escape() 将字符转换为适合按字面匹配的正则片段。
            #/
            #/ 假设开始围栏是三个反引号，最终规则相当于：
            #/     开头 0～3 个空格 + 至少三个反引号 + 行尾空白。
            #/ 结束围栏必须使用相同符号，数量不能少于开始围栏。
            closing = (
                rf" {{0,3}}{re.escape(fence_char)}"
                rf"{{{fence_length},}}[ \t]*"
            )

            #/ re.fullmatch() 要求整个 body 都符合规则。
            #/ 成功时返回匹配对象，失败时返回 None。
            #/ 这里直接利用它们在 if 条件中的真假判断。
            if re.fullmatch(closing, body):
                fence_char = ""

            #/ 当前行已处理，移动到下一行。
            #/ continue 跳过本轮循环后面的所有代码。
            i += 1
            continue

        #/ 不在围栏内部时，检查当前行是否为开始围栏。
        #/
        #/ (`{3,}|~{3,})：
        #/     至少三个反引号，或者至少三个波浪号。
        #/     这是第一个捕获分组。
        #/
        #/ (.*)：
        #/     "." 匹配普通字符，"*" 表示零次或多次。
        #/     这里接收围栏后面的语言说明等内容，也允许为空。
        #/     这是第二个捕获分组。
        opening = re.fullmatch(r" {0,3}(`{3,}|~{3,})(.*)", body)

        if opening:
            #/ groups() 返回所有捕获分组组成的元组。
            #/ 例如输入 "```python"：
            #/     marker = "```"
            #/     info = "python"
            marker, info = opening.groups()

            #/ 波浪号围栏可以直接接受。
            #/ 反引号围栏后面的说明文字不能再包含反引号。
            if marker[0] == "~" or "`" not in info:
                fence_char = marker[0]
                fence_length = len(marker)

                #/ 开始围栏这一行本身也要保留。
                result.append(line)
                i += 1
                continue

        #/ 当前行若是普通分隔线，删除符号，只保留它原来的换行。
        #/ 例如 "正文\n***\n后文" 会成为 "正文\n\n后文"，
        #/ 从而继续保留前后两段的边界。
        if divider_re.fullmatch(body):
            result.append(newline)
            i += 1
            continue

        #/ 获取可能的标题文字，去掉两端的普通空格和制表符。
        title = body.strip(" \t")

        #/ 只有满足以下条件，才继续检查下一行：
        #/     title 非空；
        #/     当前行不含 "|"，保守地避开表格行；
        #/     行首不是前面列出的其他 Markdown 结构；
        #/     后面确实还有一行。
        #/
        #/ match() 只要求从字符串开头匹配，不要求整行匹配。
        #/ 此处只想识别“行首是什么结构”，所以使用 match()。
        #/
        #/ 含 "|" 的合法标题也会被跳过，这是当前保守规则的限制。
        if (
            title
            and "|" not in body
            and not block_start_re.match(body)
            and i + 1 < len(lines)
        ):
            following = lines[i + 1]
            following_body = following.rstrip("\r\n")

            #/ 下一行必须整行都是合法的 Setext 下划线。
            underline = underline_re.fullmatch(following_body)

            if underline:
                #/ group(1) 取出 (=+|-+) 捕获到的符号文本，
                #/ 不包含下划线行前后的空格。
                #/ 例如 "  ---  " 匹配后，group(1) 得到 "---"。
                #/ 再用 [0] 取出第一个字符，判断标题级别。
                prefix = "#" if underline.group(1)[0] == "=" else "##"

                #/ 保护标题末尾本来就有的字面 "#"。
                #/ 否则 "标题 ###" 转成 ATX 后，
                #/ 末尾的 "###" 可能被当作标题闭合标记。
                #/
                #/ (?<=\s)：
                #/     要求当前位置前面是空白字符，但不把空白算进匹配内容。
                #/     \s 表示空白字符。
                #/
                #/ (#+)$：
                #/     捕获位于字符串末尾的一个或多个 "#"。
                #/
                #/ re.sub() 对匹配到的部分进行替换，返回新字符串。
                #/ lambda 是一个简短的匿名函数：
                #/     接收匹配对象 match，
                #/     返回“一个反斜杠 + 捕获到的井号文本”。
                #/ Python 字符串 "\\" 表示一个实际的反斜杠。
                title = re.sub(
                    r"(?<=\s)(#+)$",
                    lambda match: "\\" + match.group(1),
                    title,
                )

                #/ 原来的两行将缩成一行。
                #/ 使用第二行，也就是下划线行的换行符结束新标题。
                ending = following[len(following_body):]
                result.append(f"{prefix} {title}{ending}")

                #/ 标题文字和下划线两行都已处理，因此一次前进两行。
                #/ 这样下一轮也不会再次把标题下划线当作普通分隔线处理。
                i += 2
                continue

        #/ 当前行未触发任何转换或删除规则，原样保留。
        result.append(line)
        i += 1

    #/ result 中的文本已经保留了所需换行符。
    #/ 用空字符串连接，不额外插入换行或其他字符。
    #/ 如果输入为空，result 也是空列表，最终返回空字符串。
    return "".join(result)


def write_faiss_atomic(
    file_path: str | Path,
    index: faiss.Index,
) -> str:
    """将 CPU FAISS 索引原子写入文件，返回文件内容的 SHA-256 字符串。

    file_path 是包含文件名的目标路径，例如 cache_dir / "rag.faiss"。
    index 是已建立的索引对象，例如 faiss.IndexFlatIP，不是向量矩阵。

    返回的摘要供 metadata.json 记录，用来检查两份文件是否匹配。
    本函数只保证这一个文件的原子替换，不保证两个文件一起提交。
    """
    target_path = Path(file_path)

    #/ 先将整个索引序列化，再转换为 Python bytes。
    #/ serialize_index() 的返回值是 uint8 数组，表示文件字节；
    #/ 这不等于把索引中的 float32 向量量化为 uint8 向量。
    binary_data = faiss.serialize_index(index).tobytes()
    file_sha256 = hashlib.sha256(binary_data).hexdigest()

    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None

    try:
        #/ 用 Python 打开二进制文件，支持 Path 和中文路径。
        #/ 二进制模式不设置 encoding、newline，也不补文本换行。
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target_path.parent,
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(binary_data)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        #/ with 结束后文件已经关闭，Windows 下也能进行替换。
        #/ 临时文件与目标文件位于同一目录、同一文件系统。
        os.replace(temporary_path, target_path)

    finally:
        #/ 失败时尝试清理临时文件；成功替换后，临时路径已不存在。
        #/ 清理失败不覆盖写入或替换阶段本来的异常。
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    return file_sha256

def build_rag_files(
    chunk_dict: dict,
    output_dir: str | Path,
    *,
    model_dir: str | Path | None = None,
    model_version: str = "local-v1",
    dimension: int = 512,
    model=None,
    force: bool = False,
    worldview_files: list[str] | None = None,
) -> tuple[dict, bool]:
    """
    根据分块字典创建或复用 metadata.json、rag.faiss。

    参数：
        chunk_dict:
            正整数为键的分块字典。

            每个块需要包含：
                title_path：标题列表；
                content：分块正文。

            可以额外包含：
                source_filename：来源世界观文件名。

        output_dir:
            两个输出文件所在的目录。

        model_dir:
            默认使用 rag.py 同目录下的 granite-embedding-r2。

        model_version:
            手动维护的模型版本标记。
            同一目录下替换模型权重后，应更新这个值。

        dimension:
            向量维度，默认 512。

        model:
            可选的已加载模型对象。
            应与 model_dir、model_version 描述一致。

        force:
            True 表示强制重建。

        worldview_files:
            本次处理的全部世界观文件名。
            包括没有生成文本块的空文档。

            不传时，从文本块的 source_filename 推导。
            原有不提供来源信息的单字典调用仍然可用。

    返回值：
        (metadata, rebuilt)

        metadata：
            元数据字典。

        rebuilt：
            本次重新构建为 True，复用缓存为 False。

    一个输出目录对应一份知识库，同一时间由一个调用者更新。
    """

    if not isinstance(chunk_dict, dict):
        raise TypeError("chunk_dict 必须是字典。")

    if type(dimension) is not int or dimension <= 0:
        raise ValueError("dimension 必须是正整数。")

    if (
        not isinstance(model_version, str)
        or not model_version.strip()
    ):
        raise ValueError(
            "model_version 必须是非空字符串。"
        )

    #/ 文档列表单独传入：
    #/ 空文档不会生成块，因此不能仅从块推断全部文档名称。
    if worldview_files is not None:
        if (
            not isinstance(worldview_files, list)
            or not all(
                isinstance(name, str) and name.strip()
                for name in worldview_files
            )
        ):
            raise TypeError(
                "worldview_files 必须是非空文件名组成的列表。"
            )

    cache_dir = Path(output_dir)
    metadata_path = cache_dir / "metadata.json"
    index_path = cache_dir / "rag.faiss"

    resolved_model_dir = (
        Path(model_dir)
        if model_dir is not None
        else Path(__file__).resolve().parent / "granite-embedding-r2"
    ).resolve()

    if any(
        type(key) is not int or key <= 0
        for key in chunk_dict
    ):
        raise ValueError(
            "分块字典的键必须是正整数。"
        )

    chunks: list[dict] = []

    for index_id, source_chunk_id in enumerate(
        sorted(chunk_dict)
    ):
        block = chunk_dict[source_chunk_id]

        if not isinstance(block, dict):
            raise TypeError(
                f"第 {source_chunk_id} 块必须是字典。"
            )

        title_parts = block.get("title_path")
        content = block.get("content")

        #/ 原始 kb_preprocess() 没有来源字段。
        #/ 兼容旧调用时，空字符串表示来源未知。
        source_filename = block.get(
            "source_filename",
            "",
        )

        if (
            not isinstance(title_parts, list)
            or not all(
                isinstance(title, str)
                for title in title_parts
            )
        ):
            raise TypeError(
                f"第 {source_chunk_id} 块的 "
                "title_path 必须是 list[str]。"
            )

        if not isinstance(content, str) or not content.strip():
            raise ValueError(
                f"第 {source_chunk_id} 块的 "
                "content 必须是非空正文。"
            )

        if not isinstance(source_filename, str):
            raise TypeError(
                f"第 {source_chunk_id} 块的 "
                "source_filename 必须是字符串。"
            )

        chunks.append({
            #/ FAISS 返回的有效编号，对应 chunks 的列表下标。
            "index_id": index_id,

            #/ 多文档合并后，这里保存合并字典的全局块编号。
            "source_chunk_id": source_chunk_id,

            #/ 标记这个块来自哪份文档。
            "source_filename": source_filename,

            "title_parts": title_parts.copy(),
            "title_path": ">".join(title_parts),
            "content": content,
        })

    #/ 收集实际出现在文本块中的来源文件名。
    #/ 使用集合去重，排除表示“来源未知”的空字符串。
    chunk_sources = {
        chunk["source_filename"]
        for chunk in chunks
        if chunk["source_filename"]
    }

    #/ 显式传入列表时使用该列表，它还可能包含空文档名称。
    #/ 没有传入时，才从文本块来源推导。
    #/ 稳定排序，避免仅列表顺序变化就重新构建。
    processed_files = sorted(
        (
            chunk_sources
            if worldview_files is None
            else set(worldview_files)
        ),
        key=lambda name: (
            name.casefold(),
            name,
        ),
    )

    #/ 文档列表应覆盖所有有来源标记的块。
    if not chunk_sources.issubset(set(processed_files)):
        raise ValueError(
            "worldview_files 没有包含所有文本块的来源文件名。"
        )

    payload = {
        #/ 模型目录字段由 model_path 更名为 model_dir，升级元数据结构版本。
        "schema_version": 3,

        #/ metadata.json 第一层的文档名称列表。
        #/ 空文档名称也会保存在这里。
        "worldview_files": processed_files,

        "encoding": {
            "model_dir": str(resolved_model_dir),
            "model_version": model_version,
            "dimension": dimension,
            "normalized": True,
            "index_type": "IndexFlatIP",
            "similarity": "cosine",
            "document_format": (
                "title_path + LF + content; "
                "content only if title is empty"
            ),
        },

        "chunks": chunks,
    }

    #/ 原检查函数对整个 payload 计算摘要，因此不用修改它。
    #/ 文档列表也参与摘要计算：
    #/ 新增、删除、重命名空文档，同样会使缓存失效。
    input_sha256, cached_metadata = check_rag_cache(
        payload,
        cache_dir,
        force=force,
    )

    if cached_metadata is not None:
        return cached_metadata, False

    #/ 先在内存中完成编码和索引构建，再覆盖磁盘缓存。
    index = faiss.IndexFlatIP(dimension)

    if chunks:
        texts = [
            f"{chunk['title_path']}\n{chunk['content']}"
            if chunk["title_path"]
            else chunk["content"]
            for chunk in chunks
        ]

        if model is None:
            #/ 与启动预加载、查询编码共用同一个模型缓存。
            model = _load_worldview_embedding_model(
                str(resolved_model_dir),
                model_version,
            )

        embeddings = model.encode(
            texts,
            convert_to_numpy=True,
            truncate_dim=dimension,
            normalize_embeddings=False,
            show_progress_bar=False,
        )

        embeddings = np.ascontiguousarray(
            embeddings,
            dtype=np.float32,
        )

        expected_shape = (len(chunks), dimension)

        if embeddings.shape != expected_shape:
            raise ValueError(
                f"模型返回形状 {embeddings.shape}，"
                f"期望 {expected_shape}。"
            )

        if not np.isfinite(embeddings).all():
            raise ValueError(
                "embedding 包含 NaN 或无穷大，不能保存。"
            )

        norms = np.linalg.norm(
            embeddings,
            axis=1,
        )

        if (
            not np.isfinite(norms).all()
            or np.any(norms == 0)
        ):
            raise ValueError(
                "embedding 存在零向量或异常长度，无法归一化。"
            )

        #/ 单位向量之间的内积对应余弦相似度。
        #/ 后续查询向量也需要归一化。
        faiss.normalize_L2(embeddings)

        #/ 加入顺序与 chunks 列表顺序一致。
        index.add(embeddings)

    #/ 全部文档为空时，同样保存空索引，避免残留旧知识。
    faiss_sha256 = write_faiss_atomic(
        index_path,
        index,
    )

    metadata = {
        **payload,
        "input_sha256": input_sha256,
        "faiss_sha256": faiss_sha256,
    }

    write_json_atomic(
        metadata_path,
        metadata,
    )

    return metadata, True

def check_rag_cache(
    payload: dict,
    output_dir: str | Path,
    *,
    force: bool = False,
) -> tuple[str, dict | None]:
    """
    计算当前输入摘要，并检查已有缓存是否可以复用。

    参数：
        payload:
            build_rag_files() 整理后的数据，包含：
                schema_version：元数据格式版本；
                encoding：模型、维度、编码方式等设置；
                chunks：按 FAISS 编号排列的文本块列表。

            注意：不是 kb_preprocess() 返回的原始字典，
            也不应包含 input_sha256、faiss_sha256 两个结果字段。

        output_dir:
            metadata.json 和 rag.faiss 所在的目录。

        force:
            True 时只计算当前输入摘要，不检查旧缓存，
            直接返回 None，通知构建函数强制重建。

    返回值：
        (input_sha256, cached_metadata)

        input_sha256:
            本次 payload 的 SHA-256 摘要，
            后续创建新元数据时需要保存它。

        cached_metadata:
            可以复用时，返回旧元数据字典。
            不能复用时，返回 None。

    本函数只计算摘要、读取和检查文件。
    不加载模型、不生成向量、不修改文件。
    """

    #/ 将当前分块和编码设置转换成格式稳定的 JSON 字符串。
    #/ sort_keys 只稳定字典字段顺序，不改变 chunks 列表顺序。
    #/ SHA-256 接收 bytes，因此先将字符串编码为 UTF-8 字节。
    input_sha256 = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    #/ 强制重建时，仍然需要返回当前摘要，
    #/ 供 build_rag_files() 写入新的 metadata.json。
    if force:
        return input_sha256, None

    cache_dir = Path(output_dir)
    metadata_path = cache_dir / "metadata.json"
    index_path = cache_dir / "rag.faiss"

    #/ 这些值来自本次准备构建的数据，而不是旧元数据。
    expected_dimension = payload["encoding"]["dimension"]
    expected_count = len(payload["chunks"])

    try:
        with metadata_path.open(
            "r",
            encoding="utf-8",
        ) as metadata_file:
            old_metadata = json.load(metadata_file)

        #/ 合法 JSON 不一定是字典，例如文件内容也可能是 []。
        if not isinstance(old_metadata, dict):
            return input_sha256, None

        #/ 检查一：当前输入是否与上次相同。
        #/ 标题、正文、分块或编码设置变化，都会影响这个摘要。
        if old_metadata.get("input_sha256") != input_sha256:
            return input_sha256, None

        #/ 再核对元数据本身。
        #/ 避免有人只修改了旧文件中的 chunks，却保留了旧摘要，
        #/ 导致程序错误地认为元数据仍然有效。
        if any(
            old_metadata.get(key) != value
            for key, value in payload.items()
        ):
            return input_sha256, None

        #/ 检查二：当前索引文件是否与元数据匹配。
        #/ 读取的是整个 FAISS 文件的二进制内容。
        index_bytes = index_path.read_bytes()

        actual_sha256 = hashlib.sha256(
            index_bytes
        ).hexdigest()

        if actual_sha256 != old_metadata.get("faiss_sha256"):
            return input_sha256, None

        #/ 文件摘要匹配后，再检查索引是否能正常恢复。
        #/ np.frombuffer() 将文件字节视为 uint8 数组，
        #/ 然后交给 FAISS 反序列化。
        old_index = faiss.deserialize_index(
            np.frombuffer(
                index_bytes,
                dtype=np.uint8,
            )
        )

        #/ 索引类型、向量维度、向量数量也必须符合当前数据。
        if (
            not isinstance(old_index, faiss.IndexFlatIP)
            or old_index.d != expected_dimension
            or old_index.ntotal != expected_count
        ):
            return input_sha256, None

        #/ 所有检查通过，返回可以直接复用的旧元数据。
        return input_sha256, old_metadata

    except (OSError, UnicodeError, ValueError, RuntimeError):
        #/ 文件不存在、JSON 损坏或索引无法读取时，
        #/ 返回 None，由 build_rag_files() 负责重新构建。
        return input_sha256, None

def md_to_metadata_and_faiss_and_TtoC(
    model_dir: Path,
    character_dir: Path,
) -> None:
    """
    读取角色目录内的世界观 Markdown，生成或更新：
        metadata.json、rag.faiss、title_to_content.json。

    最终标题路径：
        角色目录名 > 文件名（不含 .md） > 文档中的章节路径。

    例如角色目录为“默认猫娘default_cat”，文档为“世界观1.md”：
        默认猫娘default_cat>世界观1>二、地理>1. 北境

    如果文档的首个标题是唯一的一级标题，且文字等于文件名、
    “世界观”“世界观设定”或“角色目录名 + 世界观 / 世界观设定”，
    将其视为文档总标题，在最终路径中省略；其正文仍然保留。
    其他标题原样保留，避免误删普通的一级章节。

    第一个标题前的介绍，以及被省略的总标题直属正文，
    都归入“角色目录名>文件名”。同一路径的正文按原顺序合并。

    参数：
        character_dir：角色文件夹的 Path 对象。

    返回值：
        无业务返回值，正常结束时返回 None。
    """
    if not isinstance(character_dir, Path):
        raise TypeError("character_dir 必须是 pathlib.Path 对象。")

    character_dir = character_dir.resolve()

    if not character_dir.exists():
        raise FileNotFoundError(f"角色目录不存在：{character_dir}")

    if not character_dir.is_dir():
        raise NotADirectoryError(f"传入的路径不是目录：{character_dir}")

    #/ name 取得角色文件夹的名字，不包含前面的父目录。
    character_name = character_dir.name

    #/ 只匹配当前目录内文件名包含“世界观”的 Markdown 文件。
    #/ 不递归进入子目录，扩展名不区分大小写。
    worldview_paths = sorted(
        (
            path
            for path in character_dir.iterdir()
            if path.is_file()
            and "世界观" in path.stem
            and path.suffix.lower() == ".md"
        ),
        key=lambda path: (path.name.casefold(), path.name),
    )

    if not worldview_paths:
        raise FileNotFoundError(
            f"角色目录中没有世界观 Markdown 文档：{character_dir}。"
            "文件名需要包含‘世界观’，扩展名需要是 .md。"
        )

    #/ 元数据中的来源文件列表保留扩展名，也记录空文档。
    worldview_files = [path.name for path in worldview_paths]

    combined_chunks: dict = {}
    title_to_content: dict[str, str] = {}

    #/ 与现有两个解析函数使用相同的基本 ATX 标题识别规则。
    heading_re = re.compile(r" {0,3}(#{1,6})[ \t]+(.+)")

    for md_path in worldview_paths:
        text = md_path.read_text(encoding="utf-8-sig")
        clean_text = strip_dividers(text)

        #/ stem 去掉最后一个扩展名：世界观1.md → 世界观1。
        #/ 列表里的每个元素都是一个路径层级，不是磁盘目录。
        source_parts = [character_name, md_path.stem]

        #/ 只识别明确的文档总标题，不直接丢弃任意第一个标题。
        document_title_names = {
            md_path.stem,
            "世界观",
            "世界观设定",
            f"{character_name}世界观",
            f"{character_name}世界观设定",
        }

        headings: list[tuple[int, str]] = []
        for line in clean_text.splitlines():
            match = heading_re.fullmatch(line)
            if match:
                headings.append(
                    (
                        len(match.group(1)),
                        match.group(2).strip(),
                    )
                )

        document_title: str | None = None
        if headings:
            first_level, first_title = headings[0]
            h1_count = sum(level == 1 for level, _ in headings)

            if (
                first_level == 1
                and h1_count == 1
                and first_title in document_title_names
            ):
                document_title = first_title

        #/ 两个解析函数仍然接收完全相同的正文，保留其原有接口。
        #/ 这里只调整它们的输出路径，不修改 Markdown 文件或正文。
        document_chunks = kb_preprocess(clean_text)
        document_title_content = kb_title_to_content(clean_text)

        #/ 记录“原始路径字符串 → 新路径字符串”。
        #/ 后面完整正文映射直接使用它，保证与分块的路径完全一致。
        #/ 不需要将字符串按 > 拆开，再猜测原来的标题列表。
        path_lookup: dict[str, str] = {}

        for local_chunk_id in sorted(document_chunks):
            block = document_chunks[local_chunk_id]
            original_parts = block["title_path"]
            original_path = ">".join(original_parts)

            #/ 切片或 copy() 创建新列表，不修改解析函数返回的原列表。
            chapter_parts = original_parts.copy()
            if (
                document_title is not None
                and chapter_parts
                and chapter_parts[0] == document_title
            ):
                #/ 只省略最外层的文档总标题，下面的章节全部保留。
                chapter_parts = chapter_parts[1:]

            #/ 原始路径为空时，仍保留角色名和文件名两个来源层级。
            full_parts = source_parts + chapter_parts
            full_path = ">".join(full_parts)
            path_lookup[original_path] = full_path

            #/ 每份文档的局部编号可能重复，合并后重新连续编号。
            combined_id = len(combined_chunks) + 1
            combined_chunks[combined_id] = {
                "title_path": full_parts,
                "content": block["content"],
                "source_filename": md_path.name,
            }

        for original_path, full_content in document_title_content.items():
            #/ 有非空正文的路径应至少产生一个分块。
            #/ 如果以后修改两个解析器导致它们不一致，在这里明确报错。
            if original_path not in path_lookup:
                raise ValueError(
                    f"文档 {md_path.name} 的完整正文路径没有对应分块："
                    f"{original_path!r}"
                )

            full_path = path_lookup[original_path]

            if full_path in title_to_content:
                #/ 例如标题前的介绍与总标题直属正文会归入同一路径。
                #/ 追加正文并补换行，保留两部分内容及其先后顺序。
                title_to_content[full_path] += "\n" + full_content
            else:
                title_to_content[full_path] = full_content

    #/ 分块的 title_path 已包含角色名和文件名。
    #/ build_rag_files 会将它写入 title_parts、title_path，
    #/ 并把新路径和正文一起用于编码；路径改变也会使旧缓存失效。
    build_rag_files(
        combined_chunks,
        character_dir,
        model_dir=model_dir,
        worldview_files=worldview_files,
    )

    #/ 保存与 metadata 中 title_path 一致的完整正文映射。
    #/ 全部文档为空时写入 {}，避免继续保留旧正文。
    write_json_atomic(
        character_dir / "title_to_content.json",
        title_to_content,
    )

@lru_cache(maxsize=1)
def _load_worldview_embedding_model(
    model_dir: str,
    model_version: str,
):
    """
    加载并缓存最近使用的查询模型。

    相同的模型目录和版本再次传入时，复用已有模型对象。

    model_version 参与缓存键，不是传给 SentenceTransformer 的参数。
    同目录替换模型权重后，应更新构建缓存使用的 model_version。
    """
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(
        model_dir,
        local_files_only=True,
    )

async def preload_worldview_embedding_model(
    model_dir: Path,
    model_version: str = "local-v1",
) -> None:
    """
    在线程中提前加载 embedding 模型。

    加载后的模型由 _load_worldview_embedding_model 的
    lru_cache 保存在内存中，因此本函数不需要返回模型对象。
    """
    #/ 统一为绝对路径字符串，与 metadata 中记录的路径保持一致。
    resolved_model_dir = str(model_dir.resolve())

    #/ 将同步加载函数交给工作线程执行。
    #/ await 等待加载完成，期间允许事件循环处理其他任务。
    #/ 加载失败时，异常会在这里向调用者抛出。
    await asyncio.to_thread(
        _load_worldview_embedding_model,
        resolved_model_dir,
        model_version,
    )


#/ 以下三个常量只影响 search_worldview() 的取块行为。
#/ 它们都是经验值，换语料或换模型后需要重新校准。

#/ 相对间隔：与最高分相差不超过这个范围的块都算达标。
#/ 用相对值而不是固定阈值，是因为不同模型的分数量纲差别很大。
SCORE_GAP: float = 0.03

#/ 绝对下限：最高分低于此值时，认为知识库没有相关内容。
#/ 依据：本地实测中，有答案的查询最高分落在 0.884~0.920，
#/ 无答案的落在 0.784~0.830，故取交界 0.85。
MIN_SCORE: float = 0.85

#/ 单次检索最多返回多少个分块，用于控制注入 prompt 的长度。
#/ 注意这是"分块个数"上限，不是"正文字数"上限：
#/ 每条都会展开成该标题下的完整正文，返回内容仍可能很长。
MAX_CHUNKS: int = 6


def search_worldview(
    model_dir: Path,
    character_dir: Path,
    query_string: str,
) -> str:
    """
    根据查询与分块的相似度，返回标题路径及其完整正文。

    参数：
        query_string:
            用户的查询字符串。

        character_dir:
            包含世界观文档的角色目录，类型为 Path。

    选择规则：
        1. 最高分低于 MIN_SCORE 时，认为知识库没有相关内容，返回空字符串。
        2. 其余情况取分数在 top1 - SCORE_GAP 以内的分块，最多 MAX_CHUNKS 个。
        3. 先选择分块，再按标题路径去重，同一标题只输出一次。
        4. 从完整正文映射取该路径的完整正文（不受分块上限限制）。


    返回值：
        将若干段“标题路径 + 换行 + 完整正文”
        使用两个换行拼接后的字符串。

        保持相似度从高到低的顺序，同一标题只输出一次。
        查询只有空白或知识库没有分块时，返回空字符串。

    查询前会调用 md_to_metadata_and_faiss_and_TtoC()，
    检查世界观变化，并更新或复用缓存。
    """

    if not isinstance(query_string, str):
        raise TypeError("query_string 必须是字符串。")

    if not isinstance(character_dir, Path):
        raise TypeError(
            "character_dir 必须是 pathlib.Path 对象。"
        )

    if not query_string.strip():
        return ""

    character_dir = character_dir.resolve()

    #/ 使用你已经改名的入口。
    #/ 它会读取最新世界观、检查向量缓存，并生成完整正文映射。
    #/ 如果更新失败，异常直接向上传递，不继续检索旧数据。
    md_to_metadata_and_faiss_and_TtoC(model_dir,character_dir)

    with (character_dir / "metadata.json").open(
        "r",
        encoding="utf-8",
    ) as file:
        metadata = json.load(file)

    with (character_dir / "title_to_content.json").open(
        "r",
        encoding="utf-8",
    ) as file:
        title_to_content = json.load(file)

    if (
        not isinstance(metadata, dict)
        or not isinstance(title_to_content, dict)
    ):
        raise ValueError(
            "元数据和完整正文映射必须是 JSON 对象。"
        )

    chunks = metadata["chunks"]
    encoding = metadata["encoding"]

    if (
        not isinstance(chunks, list)
        or not isinstance(encoding, dict)
    ):
        raise ValueError(
            "metadata.json 中的 chunks 或 encoding 格式错误。"
        )

    dimension = encoding["dimension"]

    if type(dimension) is not int or dimension <= 0:
        raise ValueError(
            "元数据中的向量维度必须是正整数。"
        )

    if (
        encoding.get("index_type") != "IndexFlatIP"
        or encoding.get("similarity") != "cosine"
        or encoding.get("normalized") is not True
    ):
        raise ValueError(
            "本函数需要归一化向量构建的 IndexFlatIP 余弦检索索引。"
        )

    #/ 通过 Python 读取二进制文件，支持中文路径。
    #/ 再核对将要真正加载的这份索引，避免与元数据错配。
    index_bytes = (
        character_dir / "rag.faiss"
    ).read_bytes()

    actual_sha256 = hashlib.sha256(
        index_bytes
    ).hexdigest()

    if actual_sha256 != metadata.get("faiss_sha256"):
        raise ValueError(
            "rag.faiss 与 metadata.json 不匹配，请重新构建缓存。"
        )

    index = faiss.deserialize_index(
        np.frombuffer(
            index_bytes,
            dtype=np.uint8,
        )
    )

    if (
        not isinstance(index, faiss.IndexFlatIP)
        or index.metric_type != faiss.METRIC_INNER_PRODUCT
        or index.d != dimension
        or index.ntotal != len(chunks)
    ):
        raise ValueError(
            "索引类型、维度或向量数量与元数据不一致。"
        )

    #/ 没有向量时直接返回，也不需要加载查询模型。
    if index.ntotal == 0:
        return ""

    #/ 查询必须使用与文档相同的模型和向量维度。
    #/ 路径和版本不变时，辅助函数复用已经加载的模型。
    model = _load_worldview_embedding_model(
        encoding["model_dir"],
        encoding["model_version"],
    )

    #/ 使用 [query]，使返回值保持二维形状：(1, dimension)。
    query_embeddings = model.encode(
        [query_string],
        convert_to_numpy=True,
        truncate_dim=dimension,
        normalize_embeddings=False,
        show_progress_bar=False,
    )

    query_embeddings = np.ascontiguousarray(
        query_embeddings,
        dtype=np.float32,
    )

    if query_embeddings.shape != (1, dimension):
        raise ValueError(
            f"查询向量形状为 {query_embeddings.shape}，"
            f"期望 {(1, dimension)}。"
        )

    if not np.isfinite(query_embeddings).all():
        raise ValueError(
            "查询向量包含 NaN 或无穷大。"
        )

    norm = np.linalg.norm(query_embeddings[0])

    if not np.isfinite(norm) or norm == 0:
        raise ValueError(
            "查询向量为零向量或长度异常，无法归一化。"
        )

    #/ 文档向量已经归一化。
    #/ 查询向量也归一化后，内积就对应余弦相似度。
    faiss.normalize_L2(query_embeddings)

    #/ 搜索全部分块，才能获取所有超过 0.80 的结果。
    #/ 如果只搜索前三个，就无法知道达标块是否超过三个。
    #/
    #/ scores：相似度分数，形状为 (1, 分块数量)。
    #/ indices：对应的 FAISS 编号，形状同上。
    #/ IndexFlatIP 的结果按相似度从高到低排列。
    scores, indices = index.search(
        query_embeddings,
        index.ntotal,
    )

    query_scores = scores[0]
    query_indices = indices[0]

    top1 = float(query_scores[0])

    #/ 布尔索引：选出相对间隔内的块编号。
    #/ 筛选后仍然保持原来的相似度顺序。
    high_indices = query_indices[
        query_scores >= np.float32(top1 - SCORE_GAP)
    ]

    #/ 绝对下限：最高分都不到 MIN_SCORE，认为知识库没有相关内容。
    #/ 置空数组即可，循环不会执行，最终返回空字符串。
    if np.float32(top1) < np.float32(MIN_SCORE):
        high_indices = high_indices[:0]

    selected_indices = high_indices[:MAX_CHUNKS]

    #/ 集合负责去重，列表负责保存输出顺序。
    #/ 不直接遍历集合，因为集合不保证相似度顺序。
    seen_titles: set[str] = set()
    result_parts: list[str] = []

    for chunk_index in selected_indices:
        chunk_index = int(chunk_index)

        if not 0 <= chunk_index < len(chunks):
            raise ValueError(
                f"检索返回了无效的分块编号：{chunk_index}"
            )

        title_path = chunks[chunk_index]["title_path"]

        if not isinstance(title_path, str):
            raise ValueError(
                "元数据中的 title_path 必须是字符串。"
            )

        #/ 同一标题可能命中多个块，但完整正文只输出一次。
        if title_path in seen_titles:
            continue

        #/ 从映射文件取完整正文，不返回块中被截短的正文。
        if title_path not in title_to_content:
            raise ValueError(
                f"完整正文映射缺少标题路径：{title_path!r}"
            )

        full_content = title_to_content[title_path]

        if not isinstance(full_content, str):
            raise ValueError(
                f"标题路径 {title_path!r} 对应的完整正文不是字符串。"
            )

        seen_titles.add(title_path)

        #/ 标题前的介绍使用空字符串作为标题路径。
        #/ 这种情况下直接输出介绍正文，不额外增加空标题行。
        result_parts.append(
            f"{title_path}\n{full_content}"
            if title_path
            else full_content
        )

    return "\n\n".join(result_parts)

if __name__ =="__main__":
    from pathlib import Path
    BASE_DIR = Path(__file__).resolve().parent
    character_dir:Path =BASE_DIR / "assets" /"default"/ "默认猫娘default_cat"
    model_dir=BASE_DIR / "granite-embedding-r2"
    md_to_metadata_and_faiss_and_TtoC(model_dir,character_dir)
    print(search_worldview(model_dir,character_dir,"小咪在哪里出生"))