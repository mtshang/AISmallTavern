# -*- coding: utf-8 -*-
"""
一键下载 granite-embedding-r2 到项目根目录。

用法（在项目根目录执行）：
    .venv\\Scripts\\python.exe download_embedding_model.py
    .venv\\Scripts\\python.exe download_embedding_model.py --force        # 强制重新下载
    .venv\\Scripts\\python.exe download_embedding_model.py --mirror 官方   # 只用官方源

只下载运行 RAG 必需的文件（约 630 MB）。
仓库里另有 onnx / openvino 等约 3.4 GB 的冗余格式，本脚本会跳过。

上游仓库不提供 LICENSE 文件（模型卡只声明 license: apache-2.0），
因此脚本会在许可证缺失时，从 apache.org 补取官方文本放进模型目录。

下载中断后重新运行即可续传：已存在的文件会被跳过。
"""

import argparse
import sys
import time
import urllib.request
from pathlib import Path

#/ 项目根目录：本脚本所在目录，与 main.py / rag.py 同级。
BASE_DIR: Path = Path(__file__).resolve().parent

#/ 模型最终放置位置。rag.py 默认在项目根目录下寻找这个文件夹。
TARGET_DIR: Path = BASE_DIR / "granite-embedding-r2"

#/ HuggingFace 仓库名。
REPO_ID: str = "ibm-granite/granite-embedding-311m-multilingual-r2"

#/ 只下载这些文件。
#/ fnmatch 里的 "*" 会跨越 "/"，因此 "*.json" 也能匹配 1_Pooling/config.json。
#/
#/ 其中的 "LICENSE" 是防御性写法：上游仓库目前并不提供该文件，
#/ 正常取不到东西；缺失时交由 ensure_license() 补取。
ALLOW_PATTERNS: list[str] = [
    "*.json",
    "*.safetensors",
    "*.md",
    "LICENSE",
]

#/ 下游补取许可证时使用的官方地址。
LICENSE_URL: str = "https://www.apache.org/licenses/LICENSE-2.0.txt"

#/ 许可证在模型目录中的文件名。
LICENSE_FILENAME: str = "LICENSE"

#/ 下载完成后必须存在的文件；缺任何一个都说明下载不完整。
REQUIRED_FILES: list[str] = [
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "config.json",
    "config_sentence_transformers.json",
    "modules.json",
    "sentence_bert_config.json",
    "special_tokens_map.json",
    "1_Pooling/config.json",
]

#/ 体积明显偏小的文件，视为下载残缺。
#/ 只判断"文件存在"是不够的：0 字节或中断的 LFS 下载同样会通过，
#/ 直到加载模型时才失败，而那时的报错离真正原因很远。
#/ 下限取得很保守，括号内是当前上游的实际大小，只为拦住明显残缺的下载。
MIN_BYTES: dict[str, int] = {
    "model.safetensors": 300 * 1024 * 1024,   # 实际约 623 MB
    "tokenizer.json": 10 * 1024 * 1024,       # 实际约 33 MB
    "tokenizer_config.json": 100 * 1024,      # 实际约 1.1 MB
}

#/ 未列在 MIN_BYTES 里的文件，至少不能为空。
DEFAULT_MIN_BYTES: int = 1

#/ 依次尝试的下载源：(显示名, endpoint)。
#/ endpoint 为 None 表示使用 huggingface_hub 的默认官方地址。
#/ 国内网络下镜像通常可用，官方源作为兜底。
MIRRORS: list[tuple[str, str | None]] = [
    ("hf-mirror 镜像", "https://hf-mirror.com"),
    ("HuggingFace 官方", None),
]


def check_dependency() -> bool:
    """
    检查 huggingface_hub 是否可用。

    这个包由 requirements.txt 中的 sentence-transformers 一并安装，
    因此在项目虚拟环境里必然存在。
    若用户用系统 Python 直接运行本脚本，这里给出明确提示，
    避免后面报出难懂的“所有下载源都失败”。
    """
    try:
        import huggingface_hub  # noqa: F401
    except ImportError:
        print("[错误] 缺少依赖 huggingface_hub。")
        print("       请改用项目虚拟环境运行：")
        print(r"           .venv\Scripts\python.exe download_embedding_model.py")
        print("       或先安装依赖：")
        print(r"           .venv\Scripts\python.exe -m pip install -r requirements.txt")
        return False
    return True


def ensure_license() -> None:
    """
    确保模型目录里有一份许可证文本。

    上游仓库并不提供 LICENSE 文件（模型卡只声明 license: apache-2.0），
    因此 ALLOW_PATTERNS 里的 "LICENSE" 通常取不到东西。
    这里从 apache.org 补取官方文本，让模型目录自包含许可证。

    取不到时只打印提示，不算下载失败——
    许可证缺失不影响程序运行，所以它也不在 REQUIRED_FILES 里。
    """
    license_path: Path = TARGET_DIR / LICENSE_FILENAME

    #/ 已存在就不覆盖：Git 里可能已跟踪了一份，或上次已经补取过。
    if license_path.is_file():
        print(f"[信息] 许可证已存在：{license_path}")
        return

    print("[下载] 上游不含 LICENSE，从 apache.org 补取……")

    try:
        with urllib.request.urlopen(LICENSE_URL, timeout=30) as response:
            text: str = response.read().decode("utf-8")
    except Exception as error:
        #/ 网络不通、超时、证书问题都归到这里，仅提示、不中断。
        print(f"[提示] 未能获取许可证文本（{type(error).__name__}：{error}）")
        print("       这不影响程序运行；完整文本见：")
        print(f"       {LICENSE_URL}")
        return

    #/ 简单校验内容，避免把错误页当成许可证写进文件。
    if "Apache License" not in text:
        print("[提示] 返回内容不像许可证文本，已跳过写入。")
        print(f"       完整文本见：{LICENSE_URL}")
        return

    license_path.write_text(text, encoding="utf-8")
    print(f"[完成] 已写入许可证：{license_path}")


def existing_files() -> list[str]:
    """返回目标目录里"存在且体积合理"的必需文件（相对路径）。

    体积检查是必要的：0 字节或中断下载留下的残缺文件，
    如果只按存在性判断，会被当成"模型已就绪"。
    """
    found: list[str] = []

    for name in REQUIRED_FILES:
        path: Path = TARGET_DIR / name
        if not path.is_file():
            continue

        minimum: int = MIN_BYTES.get(name, DEFAULT_MIN_BYTES)
        if path.stat().st_size < minimum:
            print(f"[提示] {name} 体积异常（{path.stat().st_size} 字节），视为未下载完整。")
            continue

        found.append(name)

    return found


def download_from(
    endpoint: str | None,
    label: str,
    force: bool = False,
) -> bool:
    """
    从指定镜像下载模型。

    参数：
        endpoint:
            镜像地址；None 表示官方默认地址。

        label:
            用于打印的镜像名称。

        force:
            True 时把 force_download 传给 snapshot_download，
            已存在的文件也会重新下载。

    返回值：
        下载成功且必需文件齐全时返回 True，否则返回 False。
    """
    from huggingface_hub import snapshot_download

    print(f"[下载] 使用{label}……")
    if endpoint:
        print(f"       地址：{endpoint}")
    if force:
        print("       已指定 --force：将重新下载所有文件。")

    started = time.perf_counter()

    try:
        snapshot_download(
            repo_id=REPO_ID,
            local_dir=str(TARGET_DIR),
            allow_patterns=ALLOW_PATTERNS,
            endpoint=endpoint,
            #/ 必须真的把 force 传下去。
            #/ 否则 --force 只跳过本脚本自己的"已存在"判断，
            #/ snapshot_download 仍然会跳过现有文件，等于什么都没重下。
            force_download=force,
        )
    except Exception as error:
        #/ 网络不通、镜像挂了、磁盘满等，都归到这里，交给下一个镜像重试。
        print(f"[失败] {label} 下载出错：{type(error).__name__}: {error}")
        return False

    elapsed = time.perf_counter() - started

    #/ 复用 existing_files()：它同时检查存在性与体积，
    #/ 因此 0 字节或残缺的文件也会被算作"缺失"。
    present = existing_files()
    missing = [name for name in REQUIRED_FILES if name not in present]

    if missing:
        print(f"[失败] {label} 下载结束，但缺少 {len(missing)} 个文件：")
        for name in missing:
            print(f"         {name}")
        return False

    print(f"[完成] {label} 下载成功，用时 {elapsed:.1f} 秒。")
    return True


def report_result() -> int:
    """打印最终结果，返回进程退出码。"""
    total_bytes = sum(
        path.stat().st_size
        for path in TARGET_DIR.rglob("*")
        if path.is_file()
    )

    print()
    print(f"[校验] 必需文件齐全，共 {len(REQUIRED_FILES)} 项。")
    print(f"[校验] 目录：{TARGET_DIR}")
    print(f"[校验] 占用：{total_bytes / 1024 / 1024:.0f} MB")
    print()
    print("模型已就绪，可以启动程序了：")
    print(r"    .venv\Scripts\python.exe main.py")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="下载 granite-embedding-r2 到项目根目录。",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="即使文件已存在，也重新下载。",
    )
    parser.add_argument(
        "--mirror",
        choices=["镜像", "官方"],
        default=None,
        help="只使用指定的下载源，不做自动重试。",
    )
    args = parser.parse_args()

    print("=" * 56)
    print("granite-embedding-r2 一键下载")
    print("=" * 56)
    print(f"[信息] 目标目录：{TARGET_DIR}")

    #/ 已经下载过就直接跳过，避免每次重复联网检查。
    present = existing_files()
    if len(present) == len(REQUIRED_FILES) and not args.force:
        print("[信息] 本地已有所需文件，跳过下载。")
        print("       如需重新下载，请加 --force。")
        ensure_license()
        return report_result()

    if present:
        print(f"[信息] 已存在 {len(present)}/{len(REQUIRED_FILES)} 个文件，将续传缺失部分。")

    #/ 依赖检查放在“跳过下载”之后：
    #/ 文件已齐全时，连 huggingface_hub 都不需要导入。
    if not check_dependency():
        return 1

    if args.mirror == "镜像":
        candidates = MIRRORS[:1]
    elif args.mirror == "官方":
        candidates = MIRRORS[1:]
    else:
        candidates = MIRRORS

    for label, endpoint in candidates:
        if download_from(endpoint, label, force=args.force):
            ensure_license()
            return report_result()
        print()

    print("=" * 56)
    print("[错误] 所有下载源都失败了。请检查网络后重试，或手动下载：")
    print(f"       仓库地址：https://huggingface.co/{REPO_ID}")
    print("       镜像地址：https://hf-mirror.com/" + REPO_ID)
    print(f"       把文件放进：{TARGET_DIR}")
    print("=" * 56)
    return 1


if __name__ == "__main__":
    sys.exit(main())
