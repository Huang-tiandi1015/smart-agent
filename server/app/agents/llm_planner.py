"""LLM 规划器：用大模型工具调用把自然语言指令解析为工具调用。

里程碑 3：从工具注册表自动生成 function definitions，调 OpenAI 兼容 API
（默认 DeepSeek，base_url 可配置）的 tool calling 能力做意图解析，
返回与规则 planner 相同的 PlanResult。
大模型只负责「意图 -> 工具调用」，执行与审批仍由本地 harness 管控。

不可用/失败时返回 None，由 planner.plan_command 回退到关键词规则。
"""
from __future__ import annotations

import json
import logging

from .. import config
from ..agents.planner import PlanResult
from .tools import registry

logger = logging.getLogger("smart-agent.llm_planner")

_client = None


def _get_client():
    """惰性创建 OpenAI 兼容异步客户端；无 API key 返回 None。"""
    global _client
    if not config.DEEPSEEK_API_KEY:
        return None
    if _client is None:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            logger.warning("openai SDK 未安装，LLM 规划器不可用")
            return None
        _client = AsyncOpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
            timeout=config.LLM_TIMEOUT,
        )
    return _client


def build_tool_definitions() -> list[dict]:
    """依据工具注册表生成 OpenAI 格式的 function definitions。

    parameters 直接复用各工具的 args_schema（已是 JSON Schema），新增工具自动生效。
    """
    definitions = []
    for tool in registry.all_tools():
        definitions.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.args_schema,
                },
            }
        )
    return definitions


_SYSTEM_PROMPT = (
    "你是 PC 远程控制系统的指令解析器。请把用户的自然语言指令映射为一次工具调用，"
    "只能使用下面列出的工具。若指令确实无法用任何工具完成，直接回复一句普通文本说明。"
    "「整理桌面」可以省略 directory 参数（服务端默认使用桌面目录）。"
)


async def plan_with_llm(text: str) -> PlanResult | None:
    """调用 LLM 解析指令，返回 PlanResult；不可用/失败返回 None（触发规则回退）。"""
    client = _get_client()
    if client is None:
        return None
    try:
        response = await client.chat.completions.create(
            model=config.LLM_MODEL,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            tools=build_tool_definitions(),
            tool_choice="auto",
        )
    except Exception as e:  # noqa: BLE001 - 覆盖 API 异常/超时/网络错误，统一回退
        logger.warning("LLM 意图解析失败，回退规则引擎: %s", e)
        return None

    message = response.choices[0].message
    for tool_call in message.tool_calls or []:
        name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        # 校验工具名与入参合法性，避免无效调用
        if name in registry.tool_names() and isinstance(args, dict):
            logger.info("LLM 解析为工具调用: %s %s", name, args)
            return PlanResult(tool_name=name, args=args)
        logger.warning("LLM 返回未知工具或非法入参: %s", name)
        return None
    if message.content and message.content.strip():
        return PlanResult(reply=message.content.strip())
    return None
