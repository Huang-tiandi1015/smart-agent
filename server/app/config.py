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


def _load_env() -> None:
    """读取 PROJECT_ROOT/.env 的 KEY=VALUE 写入 os.environ。

    仅当该变量尚未设置时写入，避免覆盖测试/部署时注入的环境变量。
    简单实现，无第三方依赖；每行最多 2 段拆分，忽略 # 注释与空行。
    """
    env_file = PROJECT_ROOT / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env()

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

# ---- 里程碑 3：LLM 意图解析（OpenAI 兼容端点，默认 DeepSeek）----
# API 密钥，经 .env 提供（DEEPSEEK_API_KEY）
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
# OpenAI 兼容 API 端点；默认 DeepSeek，可切任意兼容服务商
DEEPSEEK_BASE_URL = os.getenv("SMART_AGENT_DEEPSEEK_BASE_URL", "https://api.deepseek.com")
# 意图解析模型
LLM_MODEL = os.getenv("SMART_AGENT_LLM_MODEL", "deepseek-chat")
# 单次意图解析的 API 超时（秒）
LLM_TIMEOUT = float(os.getenv("SMART_AGENT_LLM_TIMEOUT", "30"))
# 规划器模式：auto（有 key 则走 LLM）/ llm（强制 LLM）/ rules（强制规则）
PLANNER_MODE = os.getenv("SMART_AGENT_PLANNER", "auto")


def _default_desktop() -> str:
    home = Path.home()
    for candidate in (home / "Desktop", home / "桌面"):
        if candidate.exists():
            return str(candidate)
    return str(home)


# 「整理桌面文件」的默认目标目录；测试时可通过环境变量指向沙箱
DESKTOP_DIR = os.getenv("SMART_AGENT_DESKTOP_DIR", _default_desktop())
