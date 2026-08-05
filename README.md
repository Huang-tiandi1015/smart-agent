# Smart Agent

手机端远程向电脑发送指令、电脑端调用 AI 自动执行的智能工具系统。

当前进度：**里程碑 0-2 完成**（通信链路 + 指令执行与审批）。支持「整理桌面文件」等指令，敏感操作自动弹手机端审批。

## 目录结构

```
smart-agent/
├── shared/                  # 跨端消息协议（JSON over WebSocket）
├── server/                  # 电脑端控制中心（FastAPI）
│   ├── app/
│   │   ├── main.py          # 入口
│   │   ├── config.py        # 配置（环境变量可覆盖）
│   │   ├── api/routes.py    # REST：/health /pair
│   │   ├── api/ws.py        # WebSocket：认证+心跳+指令+审批
│   │   ├── agents/          # 规划器（关键词规则）+ 工具层（organize_desktop）
│   │   └── core/            # auth、hub、jobs（任务状态机）、approval（审批记忆）
│   └── static/              # 手机端 PWA 页面（免构建）
├── scripts/client_demo.py       # 里程碑 1 冒烟测试（配对/echo/心跳）
├── scripts/milestone2_demo.py   # 里程碑 2 端到端测试（沙箱，指令/审批/1h信任）
└── docs/architecture.md     # 架构设计文档
```

## 环境要求

- Python 3.11+
- 手机端无需额外依赖（浏览器即可，免安装）

## 快速开始（本机验证）

```bash
cd smart-agent
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m uvicorn server.app.main:app --host 0.0.0.0 --port 8000
```

1. 启动后在控制台看到 6 位**配对码**。
2. 本机浏览器打开 `http://127.0.0.1:8000`，输入配对码完成绑定。
3. 在指令框输入指令，如「整理桌面文件」，敏感操作会弹出**审批弹窗**（批准 / 拒绝 / 仅本次 / 1 小时信任），并在「任务记录」里看到状态流转。

命令行验证（里程碑 1：通信链路）：

```bash
.venv/Scripts/python scripts/client_demo.py --code <控制台显示的配对码>
```

验证里程碑 2（指令执行 + 审批，**沙箱模式**避免动真实桌面）：

```bash
# 1) 建沙箱目录
mkdir -p .sandbox_demo/desktop .sandbox_demo/desktop2
# 2) 用沙箱桌面启动服务（另开终端）
SMART_AGENT_DESKTOP_DIR="D:/Claude Code/smart-agent/.sandbox_demo/desktop" \
  .venv/Scripts/python -m uvicorn server.app.main:app --host 0.0.0.0 --port 8000
# 3) 另开终端，取服务端控制台配对码后运行
.venv/Scripts/python scripts/milestone2_demo.py --code <配对码> \
  --sandbox "D:/Claude Code/smart-agent/.sandbox_demo"
```

`milestone2_demo.py` 覆盖四场景：批准执行、拒绝执行、未知指令、1 小时信任免审批。当前支持指令见「支持指令」。

## 支持指令

| 指令 | 动作 | 风险 |
|---|---|---|
| `整理桌面文件` / `整理桌面` | 把桌面文件按类型归档到 图片/文档/… 子目录（仅移动，不删除） | 敏感，需审批 |
| `整理 <目录路径>` | 归档指定目录 | 敏感，需审批 |
| `帮助` / `能做什么` | 返回支持指令列表 | 安全 |
| 其他 | 返回「未识别的指令」提示 | 安全 |

## 手机远程访问（Tailscale）

1. **电脑**：安装 [Tailscale](https://tailscale.com/download)，登录账号，执行 `tailscale ip` 记下电脑地址（`100.x.x.x`）。
2. **手机**：安装 Tailscale App，用**同一账号**登录（同一 tailnet）。
3. 手机浏览器打开 `http://<电脑tailscale地址>:8000`，输入配对码绑定即可远程控制。
4. 可选：用 `tailscale cert` 申请证书后通过 HTTPS 访问。

> Tailscale 基于 WireGuard 端到端加密、自动 NAT 穿透，无需公网端口。
> 若手机无法安装 Tailscale，后续里程碑将支持「WebSocket + 中继服务器」兜底通道。

## 消息协议摘要

所有消息为 JSON，均带 `type` 字段，定义见 `shared/protocol.py`。

| 方向 | type | 说明 |
|---|---|---|
| 客户端→服务端 | `auth` | 首条消息，携带 token |
| 客户端→服务端 | `echo` | 连通性测试 |
| 客户端→服务端 | `pong` | 心跳回复 |
| 客户端→服务端 | `command` | 远程指令：`{"text": "..."}` |
| 客户端→服务端 | `approval_response` | 审批决定：`{"job_id","decision","trust"}` |
| 服务端→客户端 | `authed` | 认证成功 |
| 服务端→客户端 | `echo_reply` | echo 回复 |
| 服务端→客户端 | `ping` | 心跳（默认每 30s，收到须回 pong） |
| 服务端→客户端 | `job_status` | 任务状态推送（created→…→done/failed/rejected） |
| 服务端→客户端 | `approval_request` | 审批请求：`{"job_id","text","risk","summary","details","ttl"}` |
| 服务端→客户端 | `error` | 错误（含 code） |

## 配置项（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `SMART_AGENT_HOST` | `0.0.0.0` | 监听地址 |
| `SMART_AGENT_PORT` | `8000` | 监听端口 |
| `SMART_AGENT_PAIR_TTL` | `600` | 配对码有效期（秒） |
| `SMART_AGENT_TOKEN_TTL` | `2592000` | token 有效期（秒），0 永不过期 |
| `SMART_AGENT_HEARTBEAT` | `30` | 心跳间隔（秒） |
| `SMART_AGENT_HEARTBEAT_TIMEOUT` | `45` | 心跳超时（秒） |
| `SMART_AGENT_DESKTOP_DIR` | 系统桌面 | 「整理桌面」的默认目标目录（沙箱测试时指向测试目录） |
| `SMART_AGENT_APPROVAL_TTL` | `600` | 审批超时（秒），超时自动拒绝 |

## Roadmap

- [x] 里程碑 2：任务状态机 + 工具抽象 + 规则指令 + 审批机制
- [ ] 里程碑 3：接入 Claude API 做意图解析与行动计划
- [ ] 里程碑 4：任务持久化 / 恢复、危险操作黑白名单、pytest
- [ ] 里程碑 5：Windows 开机自启、中继服务器兜底

详细设计见 [docs/architecture.md](docs/architecture.md)。
