"""检索类测评一键入口：延迟 → 检索质量 → 生成中文报告。

延迟测评必须最先跑：冷加载数据只有在本进程第一次加载
嵌入模型时才测得准，后面的测评复用同一个模型缓存。

运行：在项目根目录执行
    .venv\\Scripts\\python.exe eval\\retrieval\\run_retrieval.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
import eval_latency  # noqa: E402
import eval_retrieval  # noqa: E402
import make_report  # noqa: E402


def main() -> None:
    common.setup_console()

    print()
    print("#" * 62)
    print("# 检索质量测评（eval/retrieval/）")
    print("#" * 62)
    print()

    eval_latency.run()
    eval_retrieval.run()
    make_report.main()

    print("[完成] 报告已生成：eval/检索质量测评报告.md")
    print()


if __name__ == "__main__":
    main()
