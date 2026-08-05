"""全局配置。支持通过环境变量覆盖，便于部署。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 目录约定：server/app/config.py
FILE_DIR = Path(__file__).resolve().parent          # server/app
APP_DIR = FILE_DIR.parent                          # server
PROJECT_ROOT = APP_DIR.parent                      # smart-agent/
STATIC_DIR = APP_DIR / "static"                    # server/static

# 保证可从项目根导入 shared 包
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

HOST = os.getenv("SMART_AGENT_HOST", "0.0.0.0")
PORT = int(os.getenv("SMART_AGENT_PORT", "8000"))

# 配对码有效期（秒）
PAIR_CODE_TTL = int(os.getenv("SMART_AGENT_PAIR_TTL", "600"))
# token 有效期（秒），0 表示永不过期
TOKEN_TTL = int(os.getenv("SMART_AGENT_TOKEN_TTL", str(30 * 24 * 3600)))

# 心跳：服务端每 HEARTBEAT_INTERVAL 秒发一次 ping；
# 超过 HEARTBEAT_TIMEOUT 秒未收到 pong 视为掉线。
HEARTBEAT_INTERVAL = float(os.getenv("SMART_AGENT_HEARTBEAT", "30"))
HEARTBEAT_TIMEOUT = float(os.getenv("SMART_AGENT_HEARTBEAT_TIMEOUT", "45"))

# 审批超时（秒），超过未响应自动拒绝
APPROVAL_TTL = int(os.getenv("SMART_AGENT_APPROVAL_TTL", "600"))


def _default_desktop() -> str:
    home = Path.home()
    for candidate in (home / "Desktop", home / "桌面"):
        if candidate.exists():
            return str(candidate)
    return str(home)


# 「整理桌面文件」的默认目标目录；测试时可通过环境变量指向沙箱
DESKTOP_DIR = os.getenv("SMART_AGENT_DESKTOP_DIR", _default_desktop())
