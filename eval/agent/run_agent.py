"""agent 类测评一键入口（零成本部分）：契约 → Mock → 生成中文报告。

真实调用测评（eval_agent_real.py）产生 API 费用，单独运行：
    .venv\\Scripts\\python.exe eval\\agent\\eval_agent_real.py --smoke   # 冒烟
    .venv\\Scripts\\python.exe eval\\agent\\eval_agent_real.py           # 全量 40×3
跑完后重新执行本脚本（或单独跑 make_report.py）即可把真实结果合入报告。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_common  # noqa: E402
import eval_tool_path  # noqa: E402
import eval_agent_mock  # noqa: E402
import make_report  # noqa: E402


def main() -> None:
    agent_common.setup_console()

    print()
    print("#" * 62)
    print("# 工具调用测评 · 零成本部分（eval/agent/）")
    print("#" * 62)
    print()

    eval_tool_path.run()
    eval_agent_mock.run()
    make_report.main()

    print("[完成] 报告已生成：eval/工具调用测评报告.md")
    print("[提示] 真实调用测评请单独运行 eval_agent_real.py（产生 API 费用），")
    print("       完成后重新运行本脚本合并报告。")
    print()


if __name__ == "__main__":
    main()
