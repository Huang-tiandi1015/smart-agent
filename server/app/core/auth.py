"""认证：配对码换长期 token，支持 token 轮换。

流程：服务端启动时生成一次性配对码并打印到控制台 -> 手机端输入配对码 + 设备名
调用 POST /api/pair -> 换取长期 token -> 后续 WebSocket 连接携带该 token。
里程碑 4：token 落 SQLite（重启不失效）+ POST /api/rotate 轮换。
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

PAIR_CODE_LEN = 6


@dataclass
class PairCode:
    code: str
    expires_at: float
    used: int = 0
    max_uses: int = 3  # 同一配对码最多换取 token 次数


@dataclass
class Token:
    token: str
    device_id: str
    created_at: float
    expires_at: float  # 0 = 永不过期


class AuthManager:
    def __init__(self, code_ttl: float, token_ttl: int, store=None) -> None:
        self._code_ttl = code_ttl
        self._token_ttl = token_ttl
        self._store = store
        self._pair_codes: dict[str, PairCode] = {}
        self._tokens: dict[str, Token] = {}

    def issue_pair_code(self) -> str:
        """生成一个新的配对码。"""
        self._cleanup()
        code = "".join(secrets.choice("0123456789") for _ in range(PAIR_CODE_LEN))
        self._pair_codes[code] = PairCode(code=code, expires_at=time.time() + self._code_ttl)
        return code

    def exchange(self, code: str, device_id: str) -> Token | None:
        """用配对码换取 token；失败（无效/过期/次数用尽）返回 None。"""
        self._cleanup()
        pc = self._pair_codes.get(code.strip())
        if pc is None or time.time() > pc.expires_at:
            return None
        pc.used += 1
        if pc.used >= pc.max_uses:
            del self._pair_codes[code]
        token = self._new_token(device_id)
        self._tokens[token.token] = token
        if self._store:
            self._store.save_token(token)
        return token

    def rotate(self, token: str) -> Token | None:
        """用旧 token 换新 token；旧 token 立即失效。失败返回 None。"""
        old = self.validate(token)
        if old is None:
            return None
        new = self._new_token(old.device_id)
        self._tokens[new.token] = new
        if self._store:
            self._store.save_token(new)
        self.revoke(old.token)
        return new

    def _new_token(self, device_id: str) -> Token:
        return Token(
            token=secrets.token_urlsafe(32),
            device_id=device_id,
            created_at=time.time(),
            expires_at=(time.time() + self._token_ttl) if self._token_ttl > 0 else 0,
        )

    def validate(self, token: str) -> Token | None:
        """校验 token 是否有效，返回对应 Token；失效则移除。"""
        tok = self._tokens.get(token)
        if tok is None:
            return None
        if tok.expires_at and time.time() > tok.expires_at:
            del self._tokens[token]
            if self._store:
                self._store.delete_token(token)
            return None
        return tok

    def revoke(self, token: str) -> None:
        self._tokens.pop(token, None)
        if self._store:
            self._store.delete_token(token)

    def restore(self) -> None:
        """从 store 加载未过期 token（启动时调用）。"""
        if not self._store:
            return
        now = time.time()
        for token, device_id, created_at, expires_at in self._store.load_tokens():
            if expires_at and now > expires_at:
                self._store.delete_token(token)
                continue
            self._tokens[token] = Token(
                token=token, device_id=device_id, created_at=created_at, expires_at=expires_at
            )

    def _cleanup(self) -> None:
        now = time.time()
        for c in [c for c, pc in self._pair_codes.items() if now > pc.expires_at]:
            del self._pair_codes[c]
        for t in [
            t for t, tok in self._tokens.items() if tok.expires_at and now > tok.expires_at
        ]:
            del self._tokens[t]
