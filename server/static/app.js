/* Smart Agent 手机端客户端
 * 职责：配对换 token -> WebSocket 连接 -> 发送指令 / 审批弹窗 -> 任务卡片
 * 纯 vanilla，无构建。
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const TERMINAL = ["done", "failed", "rejected", "cancelled"];

  const STATUS_TEXT = {
    created: "已创建",
    parsing: "解析中",
    awaiting_approval: "等待审批",
    approved: "已批准",
    rejected: "已拒绝",
    executing: "执行中",
    done: "已完成",
    failed: "失败",
    cancelled: "已取消",
  };

  // 快捷指令
  const QUICK_COMMANDS = [
    { label: "整理桌面", text: "整理桌面文件" },
    { label: "打开 Steam", text: "打开 Steam" },
    { label: "帮助", text: "帮助" },
  ];

  const HISTORY_KEY = "sa_history";
  const HISTORY_MAX = 8;

  const state = {
    ws: null,
    token: localStorage.getItem("sa_token") || "",
    deviceId: localStorage.getItem("sa_device_id") || "",
    reconnectDelay: 2000,
    reconnectTimer: null,
    wasOnline: false,
  };

  const tasks = new Map(); // job_id -> { el, badge, text, time, body, lastStatus }
  let pendingApproval = null; // { jobId }

  /* ---------- 初始化 ---------- */
  init();

  function init() {
    $("server").value = location.host;
    if (!state.deviceId) {
      state.deviceId = crypto.randomUUID ? crypto.randomUUID() : "dev-" + Math.random().toString(36).slice(2);
      localStorage.setItem("sa_device_id", state.deviceId);
    }
    $("deviceName").value = localStorage.getItem("sa_device_name") || "";

    renderQuickChips();
    renderHistory();

    $("btnBind").addEventListener("click", bindDevice);
    $("btnSend").addEventListener("click", sendCommand);
    $("btnShowCode").addEventListener("click", showPairCode);
    $("codeClose").addEventListener("click", hideCodeModal);
    $("codeModal").addEventListener("click", (e) => { if (e.target === $("codeModal")) hideCodeModal(); });
    $("btnUnbind").addEventListener("click", unbind);
    $("btnClear").addEventListener("click", clearTasks);
    $("btnClearHistory").addEventListener("click", clearHistory);
    $("cmdInput").addEventListener("keydown", (e) => { if (e.key === "Enter") sendCommand(); });
    $("taskList").addEventListener("click", (e) => {
      const head = e.target.closest(".task-head");
      if (head) toggleTask(head.closest(".task"));
    });
    $("apApprove").addEventListener("click", approve);
    $("apDeny").addEventListener("click", deny);
    $("apCancel").addEventListener("click", cancelJob);

    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("sw.js").catch(() => {});
    }

    if (state.token) {
      showBound();
      connect();
    } else {
      setStatus("pending", "等待配对");
    }
  }

  /* ---------- 配对 ---------- */
  async function bindDevice() {
    const code = $("pairCode").value.trim();
    const deviceName = $("deviceName").value.trim() || "默认设备";
    if (!/^\d{6}$/.test(code)) {
      toast("请输入 6 位数字配对码", "error");
      return;
    }
    $("btnBind").disabled = true;
    try {
      const res = await fetch("/api/pair", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, device_id: state.deviceId }),
      });
      if (!res.ok) throw new Error("配对码无效或已过期");
      const data = await res.json();
      state.token = data.token;
      localStorage.setItem("sa_token", state.token);
      localStorage.setItem("sa_device_name", deviceName);
      toast("配对成功", "success");
      showBound();
      connect();
    } catch (err) {
      toast("配对失败: " + err.message, "error");
    } finally {
      $("btnBind").disabled = false;
    }
  }

  async function showPairCode() {
    if (!state.token) {
      toast("未绑定，无法查看配对码", "error");
      return;
    }
    try {
      const res = await fetch("/api/pair-code", {
        headers: { "Authorization": "Bearer " + state.token },
      });
      if (!res.ok) throw new Error("登录状态已失效，请重新绑定");
      const data = await res.json();
      $("codeDisplay").textContent = data.code;
      if (data.fixed) {
        $("codeLabel").textContent = "固定配对码，用于新设备绑定";
        $("codeExpiry").textContent = "长期有效，不限次数";
      } else {
        $("codeLabel").textContent = "用于新设备绑定，请尽快输入";
        const minutes = Math.max(1, Math.ceil(data.expires_in / 60));
        $("codeExpiry").textContent = `约 ${minutes} 分钟内有效，最多可用 3 次`;
      }
      $("codeModal").hidden = false;
    } catch (err) {
      toast("获取失败: " + err.message, "error");
    }
  }

  function hideCodeModal() {
    $("codeModal").hidden = true;
  }

  function unbind() {
    if (state.ws) state.ws.close();
    state.token = "";
    localStorage.removeItem("sa_token");
    $("pairCard").hidden = false;
    $("cmdCard").hidden = true;
    $("logCard").hidden = true;
    hideApproval();
    tasks.clear();
    $("taskList").innerHTML = "";
    updateTaskCount();
    setStatus("offline", "未连接");
    toast("已解除绑定");
  }

  function showBound() {
    $("pairCard").hidden = true;
    $("cmdCard").hidden = false;
    $("logCard").hidden = false;
  }

  /* ---------- WebSocket ---------- */
  function connect() {
    clearTimeout(state.reconnectTimer);
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    state.ws = ws;
    setStatus("pending", "连接中…");

    ws.onopen = () => send({ type: "auth", token: state.token });
    ws.onmessage = (ev) => onMessage(JSON.parse(ev.data));
    ws.onclose = () => {
      setStatus("offline", "重连中…");
      setSendEnabled(false);
      if (state.wasOnline) toast("连接已断开，正在重连", "error");
      state.wasOnline = false;
      state.reconnectTimer = setTimeout(connect, state.reconnectDelay);
    };
    ws.onerror = () => ws.close();
  }

  function send(obj) {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify(obj));
    }
  }

  function onMessage(msg) {
    switch (msg.type) {
      case "authed":
        setStatus("online", "已连接");
        setSendEnabled(true);
        if (!state.wasOnline) toast("已连接到电脑", "success");
        state.wasOnline = true;
        send({ type: "get_recent" });
        break;
      case "recent":
        (msg.jobs || []).forEach((j) => upsertTask(j, { quiet: true }));
        break;
      case "ping":
        send({ type: "pong" });
        break;
      case "job_status":
        onJobStatus(msg);
        break;
      case "approval_request":
        showApproval(msg);
        toast("收到一条审批请求", "warn");
        break;
      case "error":
        toast(`${msg.code}: ${msg.message}`, "error");
        break;
      default:
        toast("未知消息: " + JSON.stringify(msg), "info");
    }
  }

  /* ---------- 指令 ---------- */
  function sendText(text) {
    if (!text) return;
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
      toast("未连接，无法发送", "error");
      return;
    }
    send({ type: "command", text });
    addHistory(text);
  }

  function sendCommand() {
    const input = $("cmdInput");
    sendText(input.value.trim());
    input.value = "";
  }

  function setSendEnabled(enabled) {
    $("btnSend").disabled = !enabled;
  }

  /* ---------- 快捷指令 / 历史 ---------- */
  function renderQuickChips() {
    const box = $("quickChips");
    QUICK_COMMANDS.forEach((c) => {
      const b = document.createElement("button");
      b.className = "chip chip--quick";
      b.textContent = c.label;
      b.addEventListener("click", () => sendText(c.text));
      box.appendChild(b);
    });
  }

  function getHistory() {
    try {
      const arr = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
      return Array.isArray(arr) ? arr : [];
    } catch {
      return [];
    }
  }

  function renderHistory() {
    const arr = getHistory();
    const box = $("historyBox");
    const chips = $("historyChips");
    chips.innerHTML = "";
    box.hidden = arr.length === 0;
    arr.forEach((t) => {
      const b = document.createElement("button");
      b.className = "chip";
      b.textContent = t;
      b.addEventListener("click", () => sendText(t));
      chips.appendChild(b);
    });
  }

  function addHistory(text) {
    const arr = getHistory().filter((x) => x !== text);
    arr.unshift(text);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(arr.slice(0, HISTORY_MAX)));
    renderHistory();
  }

  function clearHistory() {
    localStorage.removeItem(HISTORY_KEY);
    renderHistory();
  }

  /* ---------- 任务卡片 ---------- */
  function onJobStatus(msg) {
    upsertTask(msg);
    if (TERMINAL.includes(msg.status) && pendingApproval && pendingApproval.jobId === msg.job_id) {
      hideApproval();
    }
  }

  function upsertTask(job, opts = {}) {
    const { quiet = false } = opts;
    let entry = tasks.get(job.job_id);
    const isNew = !entry;

    if (isNew) {
      const li = document.createElement("li");
      li.className = "task";
      li.dataset.job = job.job_id;
      const head = document.createElement("div");
      head.className = "task-head";
      const badge = document.createElement("span");
      badge.className = "badge";
      const text = document.createElement("span");
      text.className = "task-text";
      const time = document.createElement("span");
      time.className = "task-time";
      const body = document.createElement("div");
      body.className = "task-body";
      body.hidden = true;
      head.append(badge, text, time);
      li.append(head, body);
      $("taskList").prepend(li);
      entry = { el: li, badge, text, time, body, lastStatus: null, bornAt: Date.now() / 1000 };
      tasks.set(job.job_id, entry);
      if (!quiet) li.classList.add("task--new");
    }

    const prevStatus = entry.lastStatus;
    entry.lastStatus = job.status;
    entry.badge.textContent = STATUS_TEXT[job.status] || job.status;
    entry.badge.className = "badge badge--" + (job.status || "info");
    entry.text.textContent = job.text || "";
    // job_status 不带 created_at，实时任务用首次渲染的本地时间兜底
    entry.time.textContent = fmtTime(job.created_at || entry.bornAt);
    entry.el.classList.toggle("task--active", !TERMINAL.includes(job.status));

    let html = "";
    if (job.tool_name) html += `<p><span class="k">工具</span>${esc(job.tool_name)}</p>`;
    if (job.error) html += `<p class="task-err">${esc(job.error)}</p>`;
    const resultText = formatResult(job.result);
    if (resultText) html += `<p class="task-msg">${esc(resultText)}</p>`;
    entry.body.innerHTML = html;

    // 新到达终态时自动展开，折叠其余
    if (!quiet && prevStatus && TERMINAL.includes(job.status) && !TERMINAL.includes(prevStatus)) {
      tasks.forEach((other) => {
        if (other !== entry) collapseTask(other);
      });
      expandTask(entry);
    }

    updateTaskCount();
  }

  function expandTask(entry) {
    entry.body.hidden = false;
    entry.el.classList.add("task--expanded");
  }

  function collapseTask(entry) {
    entry.body.hidden = true;
    entry.el.classList.remove("task--expanded");
  }

  function toggleTask(li) {
    if (!li) return;
    const entry = tasks.get(li.dataset.job);
    if (!entry) return;
    if (entry.body.hidden) expandTask(entry);
    else collapseTask(entry);
  }

  function clearTasks() {
    tasks.clear();
    $("taskList").innerHTML = "";
    updateTaskCount();
    toast("已清空记录");
  }

  function updateTaskCount() {
    const n = tasks.size;
    $("taskCount").textContent = n;
    $("btnClear").hidden = n === 0;
  }

  function fmtTime(ts) {
    if (!ts) return "";
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function formatResult(result) {
    if (!result) return "";
    if (result.reply) return result.reply;
    if (result.message) return result.message;
    if (result.count !== undefined) return `移动 ${result.count} 个文件`;
    return JSON.stringify(result);
  }

  /* ---------- 审批 ---------- */
  const RISK_TEXT = { safe: "安全操作", sensitive: "敏感操作", dangerous: "危险操作" };

  function showApproval(req) {
    pendingApproval = { jobId: req.job_id };
    $("apText").textContent = "指令：" + (req.text || "");
    $("apSummary").textContent = req.summary || "";
    const ul = $("apDetails");
    ul.innerHTML = "";
    (req.details || []).forEach((d) => {
      const li = document.createElement("li");
      li.textContent = d;
      ul.appendChild(li);
    });
    const risk = req.risk || "sensitive";
    $("approvalModal").querySelector(".modal-box").dataset.risk = risk;
    $("apRiskTag").textContent = RISK_TEXT[risk] || risk;
    // DANGEROUS 无 1h 信任选项（服务端不豁免）
    $("apTrust").hidden = risk === "dangerous";
    $("approvalModal").hidden = false;
  }

  function hideApproval() {
    $("approvalModal").hidden = true;
    pendingApproval = null;
  }

  function approve() {
    if (!pendingApproval) return;
    const trust = document.querySelector('input[name="trust"]:checked').value;
    send({ type: "approval_response", job_id: pendingApproval.jobId, decision: "approve", trust });
    toast("已批准执行");
    hideApproval();
  }

  function deny() {
    if (!pendingApproval) return;
    send({ type: "approval_response", job_id: pendingApproval.jobId, decision: "deny" });
    toast("已拒绝");
    hideApproval();
  }

  function cancelJob() {
    if (!pendingApproval) return;
    send({ type: "cancel", job_id: pendingApproval.jobId });
    toast("已取消任务");
    hideApproval();
  }

  /* ---------- UI 辅助 ---------- */
  function setStatus(cls, text) {
    const el = $("status");
    el.className = "status status--" + cls;
    $("statusText").textContent = text;
  }

  function toast(text, kind = "info") {
    const box = $("toastBox");
    const el = document.createElement("div");
    el.className = "toast toast--" + kind;
    el.textContent = text;
    box.appendChild(el);
    requestAnimationFrame(() => el.classList.add("toast--show"));
    setTimeout(() => {
      el.classList.remove("toast--show");
      setTimeout(() => el.remove(), 300);
    }, 2600);
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
})();
