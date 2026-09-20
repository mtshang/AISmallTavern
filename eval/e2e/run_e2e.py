"""e2e 类测评一键入口：A/B 测评 → 生成中文报告。

会产生真实 API 费用（默认 16 题 × 2 组 × 2 次 = 64 次请求）。
冒烟模式：--smoke（3 题 × 2 组 × 1 次 = 6 次请求）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

import agent_common  # noqa: E402
import eval_e2e_ab  # noqa: E402
import make_report  # noqa: E402


def main() -> None:
    agent_common.setup_console()

    print()
    print("#" * 62)
    print("# 端到端问答测评（eval/e2e/）—— 产生真实 API 费用")
    print("#" * 62)
    print()

    import asyncio

    asyncio.run(eval_e2e_ab.main(smoke=False))
    make_report.main()

    print("[完成] 报告已生成：eval/端到端问答测评报告.md")
    print()


if __name__ == "__main__":
    main()
