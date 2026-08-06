"""Smart Agent 服务入口。

启动方式（项目根目录）：
    .venv/Scripts/python -m uvicorn server.app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import logging
import logging.handlers
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config
from .agents.tools.registry import tool_names
from .api import routes, ws
from .core.auth import AuthManager
from .core.hub import ConnectionHub
from .core.jobs import JobManager
from .core.store import Store

# 日志双输出：控制台（前台调试）+ 文件轮转（后台/开机自启无窗口时也能留痕）
Path(config.LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            config.LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8",
        ),
    ],
    force=True,
)
logger = logging.getLogger("smart-agent")

store = Store(config.DB_PATH)
auth = AuthManager(code_ttl=config.PAIR_CODE_TTL, token_ttl=config.TOKEN_TTL, store=store)
hub = ConnectionHub()
job_manager = JobManager(hub=hub, approval_ttl=config.APPROVAL_TTL, store=store)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时生成一个配对码，打印到控制台供手机端输入
    code = auth.issue_pair_code()
    logger.info("=" * 56)
    logger.info("首次配对码: %s  （%d 分钟内有效，最多使用 %d 次）",
                code, int(config.PAIR_CODE_TTL / 60), 3)
    logger.info("手机端访问 http://<本机地址>:%d 后，在页面输入该配对码完成绑定", config.PORT)
    logger.info("=" * 56)
    # 恢复持久化数据：未过期 token、审批信任、任务历史（非终态标记为中断）
    auth.restore()
    job_manager.restore()
    yield
    await job_manager.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(title="Smart Agent", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(routes.init_routes(auth))
    app.include_router(ws.init_ws(
        auth, hub, config.HEARTBEAT_INTERVAL, config.HEARTBEAT_TIMEOUT, job_manager,
    ))

    if config.STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="static")
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    # log_config=None：uvicorn 的 access/error 日志冒泡到根 logger（控制台 + 文件轮转）
    uvicorn.run("server.app.main:app", host=config.HOST, port=config.PORT, log_config=None)
