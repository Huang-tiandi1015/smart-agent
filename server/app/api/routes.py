"""REST 接口：健康检查、配对换 token。"""
from __future__ import annotations

import time

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from ..core.auth import AuthManager

router = APIRouter(prefix="/api")


class PairRequest(BaseModel):
    code: str
    device_id: str


class PairResponse(BaseModel):
    token: str
    device_id: str
    expires_in: int  # 秒；0 表示永不过期


class PairCodeResponse(BaseModel):
    code: str
    expires_in: int  # 秒；0 表示永不过期（固定码）
    fixed: bool  # 是否固定码（永不过期、不限次数）


class RotateRequest(BaseModel):
    token: str


def init_routes(auth: AuthManager) -> APIRouter:
    @router.get("/health")
    def health() -> dict:
        return {"status": "ok", "time": time.time()}

    @router.post("/pair", response_model=PairResponse)
    def pair(req: PairRequest) -> PairResponse:
        token = auth.exchange(req.code, req.device_id)
        if token is None:
            raise HTTPException(status_code=401, detail="配对码无效或已过期")
        expires_in = max(0, int(token.expires_at - time.time())) if token.expires_at else 0
        return PairResponse(token=token.token, device_id=token.device_id, expires_in=expires_in)

    @router.get("/pair-code", response_model=PairCodeResponse)
    def pair_code(authorization: str | None = Header(default=None)) -> PairCodeResponse:
        # 仅已绑定设备可查看当前配对码（用于给新设备绑定），需要有效 token
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="缺少 token")
        token = authorization[len("Bearer "):].strip()
        if auth.validate(token) is None:
            raise HTTPException(status_code=401, detail="token 无效或已过期")
        code, expires_at = auth.current_pair_code()
        # 固定码 expires_at=0（永不过期）；随机码计算剩余秒数
        expires_in = 0 if expires_at == 0 else max(0, int(expires_at - time.time()))
        return PairCodeResponse(code=code, expires_in=expires_in, fixed=expires_at == 0)

    @router.post("/rotate", response_model=PairResponse)
    def rotate(req: RotateRequest) -> PairResponse:
        token = auth.rotate(req.token)
        if token is None:
            raise HTTPException(status_code=401, detail="token 无效或已过期")
        expires_in = max(0, int(token.expires_at - time.time())) if token.expires_at else 0
        return PairResponse(token=token.token, device_id=token.device_id, expires_in=expires_in)

    return router
