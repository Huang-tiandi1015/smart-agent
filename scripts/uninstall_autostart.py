"""删除「Smart Agent」开机自启计划任务。"""
from __future__ import annotations

import subprocess
import sys

TASK_NAME = "Smart Agent"


def main() -> int:
    result = subprocess.run(
        ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
        capture_output=True, text=True, errors="replace",
    )
    if result.returncode != 0:
        # 任务不存在视为已删除
        print(f"任务不存在或已删除（{result.stderr.strip()}）")
        return 0
    print(f"已删除计划任务 '{TASK_NAME}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
