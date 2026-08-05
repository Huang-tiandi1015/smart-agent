# 开发进度记录

> 更新：2026-08-05（里程碑 2 收官，完成首次 git 提交）

## 当前状态

**里程碑 0-1（通信链路）已完成并验证**：配对 → WS 认证 → echo → 心跳，全通过。

**里程碑 2（指令执行 + 审批）已完成并通过沙箱端到端测试**：

- 工具层：`server/app/agents/tools/`（base.py 的 Tool 基类 + RiskLevel + ActionDetail.noop；
  organize_desktop.py 按类型归档，只移动不删除；registry.py 注册表）
- 规划器：`server/app/agents/planner.py`（关键词规则：整理桌面 / 整理 <路径> / 帮助 / 未知）
- 状态机：`server/app/core/jobs.py`（created→parsing→awaiting_approval→approved/rejected→executing→done/failed；
  JobManager + 审批缓存 + 审计；审批超时自动拒绝）
- 审批记忆：`server/app/core/approval.py`（1h 信任）
- WebSocket：`server/app/api/ws.py` 已接入 command / approval_response；`main.py` 装配 JobManager
- 前端：`server/static/` 支持发送指令、任务记录、审批弹窗（批准/拒绝/仅本次/1h）
- 端到端测试 `scripts/milestone2_demo.py`：四场景 15 项断言全通过（批准/拒绝/未知指令/1h 信任）

## 本次收官发现的 bug（均已修复）

1. **hub 推送未 await**：`hub.py` 的 `send_to_device` 调用 `ws.send_json(message)` 但未 `await`，
   Starlette 的 send_json 是协程，导致 job_status / approval_request 从未真正发送。
   修复：`send_to_device` 改为 `async`，`jobs.py` 的 submit/handle_approval/_process/_execute/
   _notify/_set_status/_push_approval_request 一并改 async 并 await，`ws.py` 调用点加 await。
   里程碑 1 的 echo 走 ws.py 内的 await 路径，未经过 hub，所以当时没暴露。
2. **planner 路径误判**：`整理 <路径>` 的路径若含子串 "desktop"（如 `...\desktop2`），
   会被「整理桌面文件」分支截胡，错误使用 config.DESKTOP_DIR。
   修复：先提取显式路径（有路径走路径分支），无路径再按「桌面/desktop」关键词走默认桌面。

## 与早期文档的一个差异

进度文档原写「场景3 未知指令 → failed」，但实际 `_process` 对未知指令返回
`done + result.reply`（提示「未识别的指令」），与帮助指令一致，前端 formatResult 会展示提示语。
测试按此实际行为断言（done + reply），不改动状态机。

## 启动命令备忘

```bash
cd "D:/Claude Code/smart-agent"
.venv/Scripts/python -m uvicorn server.app.main:app --host 0.0.0.0 --port 8000
```
配对码打印在控制台，手机访问 `http://<电脑IP>:8000`。防火墙规则已放行 8000 端口。

## 沙箱测试命令备忘

```bash
mkdir -p .sandbox_demo/desktop .sandbox_demo/desktop2
SMART_AGENT_DESKTOP_DIR="D:/Claude Code/smart-agent/.sandbox_demo/desktop" \
  .venv/Scripts/python -m uvicorn server.app.main:app --host 0.0.0.0 --port 8000
# 另开终端，取配对码
.venv/Scripts/python scripts/milestone2_demo.py --code <配对码> --sandbox "D:/Claude Code/smart-agent/.sandbox_demo"
```
`.sandbox_demo/` 已加入 .gitignore。

## 下一步（里程碑 3）

- 用 Claude API 替换 planner.py 关键词规则（保持 plan_command 接口不变）
- 依据 Tool.args_schema 自动生成 function definitions 给大模型
- 手机端 PWA 接入审批交互与状态展示的打磨
