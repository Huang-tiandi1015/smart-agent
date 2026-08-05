/* Smart Agent 手机端客户端
 * 职责：配对换 token -> WebSocket 连接 -> 发送指令 / 审批弹窗 -> 任务记录
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const state = {
    ws: null,
    token: localStorage.getItem("sa_token") || "",
    deviceId: localStorage.getItem("sa_device_id") || "",
    reconnectDelay: 2000,
    reconnectTimer: null,
  };
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

    $("btnBind").addEventListener("click", bindDevice);
    $("btnSend").addEventListener("click", sendCommand);
    $("btnUnbind").addEventListener("click", unbind);
    $("cmdInput").addEventListener("keydown", (e) => { if (e.key === "Enter") sendCommand(); });
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
      logLine("info", "请输入 6 位数字配对码");
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
      logLine("info", "配对成功，token 已保存");
      showBound();
      connect();
    } catch (err) {
      logLine("error", "配对失败: " + err.message);
    } finally {
      $("btnBind").disabled = false;
    }
  }

  function unbind() {
    if (state.ws) state.ws.close();
    state.token = "";
    localStorage.removeItem("sa_token");
    $("pairCard").hidden = false;
    $("cmdCard").hidden = true;
    $("logCard").hidden = true;
    hideApproval();
    setStatus("offline", "未连接");
    logLine("info", "已解除绑定");
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
      setStatus("offline", "已断开，重连中…");
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
        logLine("info", `认证成功（设备 ${msg.device_id.slice(0, 8)}…）`);
        send({ type: "get_recent" });
        break;
      case "recent":
        renderRecent(msg.jobs || []);
        break;
      case "echo_reply":
        logLine("received", `回复: ${msg.text}`);
        break;
      case "ping":
        send({ type: "pong" });
        break;
      case "job_status":
        onJobStatus(msg);
        break;
      case "approval_request":
        showApproval(msg);
        logLine("received", `收到审批请求 #${msg.job_id}`);
        break;
      case "error":
        logLine("error", `${msg.code}: ${msg.message}`);
        break;
      default:
        logLine("received", JSON.stringify(msg));
    }
  }

  /* ---------- 指令与任务 ---------- */
  function sendCommand() {
    const input = $("cmdInput");
    const text = input.value.trim();
    if (!text) return;
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
      logLine("error", "未连接，无法发送");
      return;
    }
    send({ type: "command", text });
    logLine("sent", "指令: " + text);
    input.value = "";
  }

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

  const loggedJobIds = new Set(); // 已在日志中出现过的任务，recent 渲染时跳过

  function onJobStatus(msg) {
    loggedJobIds.add(msg.job_id);
    const label = STATUS_TEXT[msg.status] || msg.status;
    const extra = msg.status === "done" ? formatResult(msg.result) : (msg.error || "");
    const line = `#${msg.job_id} ${label}${extra ? " — " + extra : ""}`;
    const kind = msg.status === "done" ? "sent" : (["failed", "rejected", "cancelled"].includes(msg.status) ? "error" : "info");
    logLine(kind, line);

    if (["done", "failed", "rejected", "cancelled"].includes(msg.status) && pendingApproval && pendingApproval.jobId === msg.job_id) {
      hideApproval();
    }
  }

  function renderRecent(jobs) {
    const fresh = jobs.filter((j) => !loggedJobIds.has(j.job_id));
    if (!fresh.length) return;
    logLine("info", `—— 最近 ${fresh.length} 条历史任务 ——`);
    fresh.forEach((j) => {
      loggedJobIds.add(j.job_id);
      const label = STATUS_TEXT[j.status] || j.status;
      const extra = j.status === "done" ? formatResult(j.result) : (j.error || "");
      const line = `#${j.job_id} ${label}${extra ? " — " + extra : ""}`;
      logLine(j.status === "done" ? "sent" : "info", line);
    });
  }

  function formatResult(result) {
    if (!result) return "";
    if (result.reply) return result.reply;
    if (result.message) return result.message;
    if (result.count !== undefined) return `移动 ${result.count} 个文件`;
    return JSON.stringify(result);
  }

  /* ---------- 审批 ---------- */
  function showApproval(req) {
    pendingApproval = { jobId: req.job_id };
    $("apText").textContent = "指令：" + req.text;
    $("apSummary").textContent = req.summary;
    const ul = $("apDetails");
    ul.innerHTML = "";
    (req.details || []).forEach((d) => {
      const li = document.createElement("li");
      li.textContent = d;
      ul.appendChild(li);
    });
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
    logLine("info", "已批准执行");
    hideApproval();
  }

  function deny() {
    if (!pendingApproval) return;
    send({ type: "approval_response", job_id: pendingApproval.jobId, decision: "deny" });
    logLine("info", "已拒绝");
    hideApproval();
  }

  function cancelJob() {
    if (!pendingApproval) return;
    send({ type: "cancel", job_id: pendingApproval.jobId });
    logLine("info", "已取消任务");
    hideApproval();
  }

  /* ---------- UI 辅助 ---------- */
  function setStatus(cls, text) {
    const el = $("status");
    el.textContent = text;
    el.className = "status status--" + cls;
  }

  function logLine(kind, text) {
    const ul = $("log");
    const li = document.createElement("li");
    li.className = kind;
    const meta = new Date().toLocaleTimeString();
    li.innerHTML = `<span class="meta">${meta}</span> ${escapeHtml(text)}`;
    ul.appendChild(li);
    ul.scrollTop = ul.scrollHeight;
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
})();
