"""跨端消息协议定义（MVP 阶段：JSON over WebSocket）。

所有消息为扁平 dict，均携带 ``type`` 字段。手机端与电脑端共用本协议，
未来若引入 pydantic schema 也以此为准。
"""
from __future__ import annotations

import json
from typing import Any

# ---- 客户端 -> 服务端 ----
MSG_AUTH = "auth"                       # 首条消息，携带 token
MSG_ECHO = "echo"                       # 连通性测试
MSG_PONG = "pong"                       # 心跳回复
MSG_COMMAND = "command"                 # 远程指令：{"text": "..."}
MSG_APPROVAL_RESPONSE = "approval_response"  # 审批决定：{"job_id","decision","trust"}

# ---- 服务端 -> 客户端 ----
MSG_AUTHED = "authed"                   # 认证成功
MSG_ECHO_REPLY = "echo_reply"           # echo 回复
MSG_PING = "ping"                       # 心跳
MSG_JOB_STATUS = "job_status"           # 任务状态推送
MSG_APPROVAL_REQUEST = "approval_request"  # 审批请求：{"job_id","text","risk","summary","details","ttl"}
MSG_ERROR = "error"                     # 错误


def make_message(type_: str, **payload: Any) -> dict:
    """构造一条协议消息。"""
    return {"type": type_, **payload}


def dumps(message: dict) -> str:
    return json.dumps(message, ensure_ascii=False)


def loads(raw: str) -> dict:
    return json.loads(raw)
