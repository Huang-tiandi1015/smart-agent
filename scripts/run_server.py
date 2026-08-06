"""后台/前台统一启动入口。

前台调试：.venv/Scripts/python scripts/run_server.py
开机自启：计划任务用 pythonw.exe 执行本文件（隐藏窗口，日志落 logs/smart-agent.log）。

以 log_config=None 运行 uvicorn，让 uvicorn 的 access/error 日志冒泡到根 logger，
统一走 main.py 配置的「控制台 + RotatingFileHandler 文件轮转」。
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

# pythonw 下没有控制台，sys.stdout/stderr 为 None，提前兜底避免 print/logging 抛错
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import uvicorn  # noqa: E402

from server.app import config  # noqa: E402
from server.app.main import app  # noqa: E402  # 模块级日志配置随之生效

if __name__ == "__main__":
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_config=None)
