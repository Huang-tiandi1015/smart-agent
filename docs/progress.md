# 开发进度记录

> 更新：2026-08-18（新增固定配对码 + 手机端查看）

## 当前状态

**固定配对码（2026-08-18）**：

- 配置项 `SMART_AGENT_PAIR_CODE`（`.env`）：设置后始终用该码，永不过期、不限次数；留空则恢复「启动随机生成 + 10 分钟有效」。
- `AuthManager` 增加 `fixed_code` 参数；`issue_pair_code`/`exchange`/`current_pair_code`/`_cleanup` 兼容
  `expires_at=0`（永不过期）语义；`/api/pair-code` 响应加 `fixed` 字段。
- 前端弹窗区分固定码（「长期有效，不限次数」）与临时码（倒计时）；配对页提示文案通用化；sw.js 缓存升 v4。
- 已在 `.env` 启用固定码（值见本地 `.env`，不入库）。
- 验证：pytest 66 项全绿（新增固定码 4 项）；E2E：同一固定码连续配对多次成功、`/api/pair-code` 返回
  `{"code":"******","expires_in":0,"fixed":true}`、启动日志显示「固定码，长期有效，不限次数」。

## 当前状态（旧）

**手机端可查看配对码（2026-08-18）**：

- 后端：`AuthManager.current_pair_code()`（返回当前仍有效配对码，无则新生成）+ `GET /api/pair-code`（需 Bearer token，
  未认证 401）。安全设计：**首次配对仍需电脑端看码**；绑定后的设备可在「指令」页随时查看/刷新新码，供新设备绑定。
- 前端：指令卡新增「查看配对码」按钮 + 大号数字弹窗（显示码 + 剩余有效期 + 最多 3 次）；配对页提示文案更新。
- sw.js 缓存升 v3（否则手机 PWA 会继续用缓存的旧外壳）。
- 验证：pytest 62 项全绿（新增 `test_auth.py` 4 项）；E2E：配对→带 token 查码 200 返回当前码、无/假 token 均 401；
  静态文件 /、style.css、app.js、sw.js 均 200 且含新元素。

## 当前状态（旧）

**手机端页面全面优化**（2026-08-12，纯静态改造，后端不动）：

- **视觉**：CSS 变量 + 系统暗色模式（`prefers-color-scheme`）、渐变品牌顶栏、卡片阴影圆角、动效（状态脉冲/卡片入场/弹窗弹出）
- **交互**：任务记录从纯文本日志改为**结构化任务卡片**（状态徽标 + 指令 + 时间，点击展开详情，到达终态自动展开）；快捷指令 chips（整理桌面/打开 Steam/帮助）；发送按钮随连接状态禁用
- **功能**：指令历史（localStorage 最近 8 条，点击重发，可清空）；Toast 瞬时提示（连接/配对/审批/错误）；审批弹窗按 risk 着色（safe 蓝/sensitive 琥珀/dangerous 红），dangerous 隐藏 1h 信任选项；清空任务记录
- **PWA**：新增 `scripts/gen_icons.py`（纯 stdlib 手写 PNG，蓝渐变圆角方块+白色闪电，4x4 超采样抗锯齿），生成 `server/static/icons/`（180/192/512 + maskable-512）；manifest 补 description/id/orientation/icons；sw.js 缓存升 v2
- 验证：pytest 58 项全绿；静态文件 /、style.css、app.js、manifest.json、sw.js、4 个图标全部 200；JS 引用的 29 个 DOM ID 与 HTML 一一对应
- 注：手机需刷新页面（或重新打开）拉取 sw v2 新外壳

**新工具 `launch_app`（打开应用）已加入并验证**（2026-08-12）：

- `server/app/agents/tools/launch_app.py`：按名称解析已安装软件的可启动目标
  （开始菜单快捷方式 .lnk → 常见安装目录 .exe → PATH 兜底），精确/前缀/词级/子串分级匹配，
  找不到明确报错；`RiskLevel.SENSITIVE` 需手机审批；.lnk 用 `os.startfile` 交给 Windows 解析，exe 用 subprocess 启动。
  带 `_RESOLVE_CACHE` 命中缓存（上限 512 条），避免每次重复扫描 Program Files。
- 注册进 `registry.py`，LLM 规划器自动生成 function definition，手机发「打开 Steam」「启动微信」即可触发。
- 规则回退 `planner.py` 支持「打开X / X打开 / 启动X」短指令；帮助列表新增「打开 <软件名>」。
- `jobs.py` 的 `tool.plan` 改为 `asyncio.to_thread` 执行（launch_app 会扫描文件系统，避免阻塞事件循环）。
- 新增 `server/tests/test_launch_app.py` 17 项（解析分级/计划明细/启动调用/启动失败/规则回退），pytest 58 项全绿。
- 真实环境验证：`resolve_app("steam")` 命中
  `...Start Menu\Programs\Steam\Steam.lnk`；服务重启后健康检查通过。

## 当前状态（里程碑 5）

**里程碑 5（日志轮转 + 开机自启）已完成并全量验证**（中继服务器兜底按用户确认不做）：

- **统一启动入口** `scripts/run_server.py`：前台调试与开机自启共用；`uvicorn.run(log_config=None)`
  让 uvicorn 的 access/error 日志冒泡到根 logger，统一走 main.py 的双 handler。
  pythonw 下 `sys.stdout/stderr` 为 None，入口提前兜底为 `io.StringIO`，避免 print/logging 抛错。
- **日志轮转**：`config.py` 新增 `LOG_FILE` / `LOG_LEVEL`（`SMART_AGENT_LOG_FILE` /
  `SMART_AGENT_LOG_LEVEL` 可覆盖，默认 `logs/smart-agent.log` / INFO）；`main.py` 日志改为
  「控制台 StreamHandler + RotatingFileHandler（5MB × 3 备份）」双输出，`Path` 导入已在 main.py 补上。
- **开机自启**：`scripts/install_autostart.py` 用临时 UTF-16 XML + `schtasks` 注册「Smart Agent」
  登录时计划任务（pythonw.exe 隐藏窗口跑 run_server.py，显式 WorkingDirectory，
  RestartOnFailure 失败 1 分钟后重试 3 次，ExecutionTimeLimit 不限时，LeastPrivilege 无需管理员权限）；
  `scripts/uninstall_autostart.py` 一键删除。
- **实测结果**（2026-08-06）：
  - pytest 41 项全绿；前台 `run_server.py` 起服务后日志同时含 app 日志与 uvicorn access 行。
  - 计划任务实测全流程：`install_autostart.py` 注册 → `schtasks /run` 拉起 → 验证
    pythonw.exe 进程存活 + 8000 端口监听 + `logs/smart-agent.log` 新增 app 日志与
    uvicorn access 行 → `GET /api/health` 200 且 access 行落盘 → `taskkill` 结束进程 +
    `uninstall_autostart.py` 卸载并确认任务已删除，端口释放、无进程残留。

**里程碑 0-1（通信链路）已完成并验证**：配对 → WS 认证 → echo → 心跳，全通过。

**里程碑 2（指令执行 + 审批）已完成并通过沙箱端到端测试**：

- 工具层：`server/app/agents/tools/`（base.py 的 Tool 基类 + RiskLevel + ActionDetail.noop；
  organize_desktop.py 按类型归档，只移动不删除；registry.py 注册表）
- 状态机：`server/app/core/jobs.py`（created→parsing→awaiting_approval→approved/rejected→executing→done/failed；
  JobManager + 审批缓存 + 审计；审批超时自动拒绝）
- 审批记忆：`server/app/core/approval.py`（1h 信任）
- WebSocket：`server/app/api/ws.py` 已接入 command / approval_response；`main.py` 装配 JobManager
- 前端：`server/static/` 支持发送指令、任务记录、审批弹窗（批准/拒绝/仅本次/1h）
- 端到端测试 `scripts/milestone2_demo.py`：四场景 15 项断言全通过（批准/拒绝/未知指令/1h 信任）

**里程碑 3（LLM 意图解析，默认 DeepSeek）已完成核心，两条回退路径已验证**：

- LLM 规划器 `server/app/agents/llm_planner.py`：从工具注册表 `registry.all_tools()` 自动生成
  OpenAI 格式 function definitions（parameters 复用各工具 args_schema，新增工具自动生效）；
  调 OpenAI 兼容端点（默认 DeepSeek `api.deepseek.com`）的 tool calling 解析意图 → `PlanResult`；
  SDK 缺失/网络/超时/非法响应一律返回 None。
- 门面：`planner.plan_command` 改为 async，`SMART_AGENT_PLANNER=rules` 或未配置 key 直接走
  规则引擎；LLM 失败回退 `rules_plan`（原关键词逻辑改名保留）。`jobs.py:_process` 加 await。
- `organize_desktop` 的 directory 参数改为可选（args_schema required 置空），省略时默认
  `config.DESKTOP_DIR`，LLM 无需知道桌面路径；规则路径显式传路径，行为不变。
- 配置：`config.py` 顶部新增 `.env` 读取（仅当环境变量未设置时写入，不覆盖测试注入）；
  新增 `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `LLM_MODEL` / `LLM_TIMEOUT` / `PLANNER_MODE`。
- 端到端测试 `scripts/milestone3_demo.py`：场景A 自然语言整理指令→审批→归档；场景B 超能力
  指令→done+非空回复且不误调工具。复用 milestone2_demo 的 DemoClient。
- 验证结果：rules 模式 15/15 通过；无 key auto 模式 15/15 通过（证明回退生效），服务端日志无
  warning/error。**LLM 真路径已由用户提供 DeepSeek key 后验证通过（milestone3_demo 9/9）**。

**里程碑 4（持久化 + 安全强化 + 取消/并发 + pytest）已完成并全量验证**：

- **持久化**：新增 `server/app/core/store.py`（stdlib sqlite3，零新依赖）落盘四类数据
  （jobs / audit / approval_trust / tokens），每次操作独立开连接 + WAL + busy_timeout。
  任务状态、审计、审批信任、token 重启不丢；`main.py` 装配 Store，lifespan 启动时
  `auth.restore()` + `job_manager.restore()`（非终态任务标记为「服务重启，任务中断」→ failed），
  关闭时 `job_manager.shutdown()` 优雅取消后台任务。
- **安全强化**：
  - `RiskLevel.DANGEROUS` 完整接线：危险工具**必须**审批，1h 信任不豁免；
    `handle_approval` 里 trust="1h" 仅对非 DANGEROUS 工具写信任缓存。
  - 新增 `server/app/safety/classifier.py` 目录黑名单（Windows 系统目录前缀 + 盘符根目录正则），
    在工具执行前硬拦截（`_process` 中 `tool.plan` 之后、审批之前调用 `check_tool`），
    即使手机端批准也直接拒绝，错误信息含「安全拦截」。
  - token 轮换：`POST /api/rotate`（旧 token 换新，旧 token 立即失效，落库）。
- **取消与并发**：新增 `cancel` 协议消息，仅任务发起设备可取消 created/parsing/awaiting_approval
  状态任务（新终态 `cancelled`）；`_execute` 用 `asyncio.Semaphore` 限流工具执行
  （`SMART_AGENT_MAX_CONCURRENT`，默认 3）；`_spawn` 统一追踪后台任务以便 shutdown。
- **前端**：`static/app.js` 增加 `cancelled` 状态文案、审批弹窗「取消」按钮、连接后自动
  `get_recent` 拉历史并去重渲染；`index.html` 加 `apCancel` 按钮。
- **测试**：新增 `server/tests/` pytest 套件（conftest 强制 rules 规划器、FakeHub 假连接），
  41 项全绿，覆盖状态机（批准/拒绝/帮助/空目录/未知）、1h 信任与 DANGEROUS 不豁免、
  取消、黑名单拦截、重启恢复、store 落盘往返、approval 记忆、工具行为、分类器、规则规划器。
  pytest 期间发现并修复 `restore()` 未把中断任务置为 failed 的 bug。
- 端到端验证：rules 回归 milestone2_demo 15/15；milestone4_demo 9/9（黑名单/取消/recent）；
  重启后 `get_recent` 历史完整保留；`/api/rotate` 旧 token 失效 401；LLM 路径 milestone3_demo 9/9；
  各服务端日志 0 warning/error。

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
# 统一入口（前台调试，日志同时落控制台与 logs/smart-agent.log）
.venv/Scripts/python scripts/run_server.py
# 或直接 uvicorn（同样走双 handler，但 uvicorn 的 access/error 需手动加参数才会冒泡）
.venv/Scripts/python -m uvicorn server.app.main:app --host 0.0.0.0 --port 8000
```
配对码打印在控制台，手机访问 `http://<电脑IP>:8000`。防火墙规则已放行 8000 端口。

### 开机自启（里程碑 5）

```bash
# 安装（注册「Smart Agent」登录时计划任务，pythonw 隐藏窗口后台运行）
.venv/Scripts/python scripts/install_autostart.py
# 查看/立即触发测试
schtasks /query /tn "Smart Agent"
schtasks /run /tn "Smart Agent"
# 卸载（删除计划任务）
.venv/Scripts/python scripts/uninstall_autostart.py
```
后台运行无控制台，日志统一落在 `logs/smart-agent.log`（5MB 轮转，保留 3 份备份）。

## 沙箱测试命令备忘

```bash
mkdir -p .sandbox_demo/desktop .sandbox_demo/desktop2
SMART_AGENT_DESKTOP_DIR="D:/Claude Code/smart-agent/.sandbox_demo/desktop" \
  .venv/Scripts/python -m uvicorn server.app.main:app --host 0.0.0.0 --port 8000
# 另开终端，取配对码
.venv/Scripts/python scripts/milestone2_demo.py --code <配对码> --sandbox "D:/Claude Code/smart-agent/.sandbox_demo"
# 里程碑 3：LLM 路径（需 .env 填好 key）
.venv/Scripts/python scripts/milestone3_demo.py --code <配对码> --sandbox "D:/Claude Code/smart-agent/.sandbox_demo"
# 里程碑 4：黑名单/取消/recent（沙箱起服务同上）
.venv/Scripts/python scripts/milestone4_demo.py --code <配对码> --sandbox "D:/Claude Code/smart-agent/.sandbox_demo"
# 强制规则模式回归：起服务前加 SMART_AGENT_PLANNER=rules
# pytest 单元测试
.venv/Scripts/python -m pytest -q
```
`.sandbox_demo/`、`data/` 已加入 .gitignore。

## 下一步（里程碑 5 已完成）

- ✅ Windows 开机自启（计划任务，登录时自动后台启动，pythonw 隐藏窗口）
- ✅ 日志轮转（RotatingFileHandler 5MB × 3）
- ⏭ 中继服务器兜底通道（手机无法装 Tailscale 时）——用户确认不做
- 未来可选：前端审批交互与状态展示打磨、HTTPS、更多工具

## 里程碑 3 待办（已完成）

- DeepSeek key 已填入 `.env`；LLM 真路径验证通过（milestone3_demo 9/9），
  milestone2_demo 15/15 在 LLM 下回归通过。
