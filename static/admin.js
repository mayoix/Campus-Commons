/* Administrator-only console. The public app never imports this file. */
(() => {
  function initAdmin() {
    const state = { data: null, tab: "dashboard" };
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  const fmtDate = (value) => value ? new Date(value).toLocaleString("zh-CN", {month:"numeric", day:"numeric", hour:"2-digit", minute:"2-digit"}) : "—";
  const fmtStatus = (status) => ({open:"开放",waitlisted:"候补",allocated:"已分配",in_use:"使用中",completed:"已完成",withdrawn:"已撤回",available:"可用",offline:"下架",maintenance:"维护中",reserved:"已占用"}[status] || status || "—");
  function toast(message, error = false) { const node = $("admin-toast"); node.textContent = message; node.style.background = error ? "#a53b3b" : "#16312b"; node.classList.add("show"); setTimeout(() => node.classList.remove("show"), 2600); }
  async function api(path, options = {}) {
    const response = await fetch(path, { credentials: "same-origin", headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
    const text = await response.text(); let body = {}; try { body = text ? JSON.parse(text) : {}; } catch (_) { body = { raw: text }; }
    if (!response.ok) { const error = new Error(body.error || `请求失败（${response.status}）`); error.status = response.status; throw error; }
    return body;
  }
  async function load() { state.data = await api("/api/admin/bootstrap"); $("admin-login").hidden = true; $("admin-app").hidden = false; $("admin-logout").hidden = false; $("admin-session-label").textContent = `管理员 · ${fmtDate(new Date().toISOString())}`; render(); }
  function table(headers, rows) { return `<div class="table-wrap"><table class="admin-table"><thead><tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows || `<tr><td colspan="${headers.length}" class="muted">暂无数据</td></tr>`}</tbody></table></div>`; }
  function statusPill(status) { const cls = ["withdrawn","offline","maintenance"].includes(status) ? " red" : ["waitlisted","reserved","in_use"].includes(status) ? " orange" : ""; return `<span class="pill${cls}">${esc(fmtStatus(status))}</span>`; }
  function render() { if (!state.data) return; renderDashboard(); renderMissions(); renderResources(); renderOrganizations(); renderDemo(); renderDisputes(); showTab(state.tab); }
  function renderDashboard() {
    const d = state.data, m = d.metrics || {}, config = d.config || {};
    $("tab-dashboard").innerHTML = `<h1>管理端总览</h1><p>管理资源、组织与平台分配逻辑；用户端只接收结果通知。</p>
      <div class="stat-grid"><div class="stat-card"><small>组织</small><strong>${d.organizations?.length ?? 0}</strong></div><div class="stat-card"><small>资源</small><strong>${d.resources?.length ?? 0}</strong></div><div class="stat-card"><small>Mission</small><strong>${d.missions?.length ?? 0}</strong></div><div class="stat-card"><small>候补 / 冲突</small><strong>${(d.missions || []).filter(x=>x.status === "waitlisted").length} / ${(d.disputes || []).filter(x=>x.status === "open").length}</strong></div></div>
      <div class="grid-two"><div class="panel"><h2>分配调度</h2><p>截止时间到达后，批次才会冻结候选方案；资源冲突会进入候补，避免提交 Mission 后立即分配。</p><div class="toolbar"><button class="primary" data-action="run-batch">运行到期批次</button><span class="muted">调度器：${config.scheduler_enabled ? "已开启" : "手动模式"}</span></div></div><div class="panel"><h2>最近管理事件</h2>${(d.events || []).slice(0,6).map(e=>`<p><b>${esc(e.title)}</b><br><span class="muted">${esc(e.detail)} · ${fmtDate(e.created_at)}</span></p>`).join("") || '<p class="muted">暂无事件</p>'}</div></div>`;
    bindActions();
  }
  function renderMissions() {
    const rows = (state.data.missions || []).map(m => `<tr><td><b>${esc(m.title)}</b><br><span class="muted">${esc(m.requester?.short_name || m.requester_org_id)} · ${esc(m.location)}</span></td><td>${statusPill(m.status)}</td><td>${fmtDate(m.start_at)}<br><span class="muted">截止 ${fmtDate(m.deadline)}</span></td><td>${m.allocated_plan_id ? esc(m.allocated_plan_id) : "—"}</td><td><div class="row-actions">${m.status === "allocated" ? `<button data-action="mission-action" data-id="${m.id}" data-kind="checkout">开始使用</button>` : ""}${m.status === "in_use" ? `<button data-action="mission-action" data-id="${m.id}" data-kind="complete">完成归还</button>` : ""}${["open","waitlisted"].includes(m.status) ? `<button data-action="mission-action" data-id="${m.id}" data-kind="withdraw">撤回</button>` : ""}</div></td></tr>`);
    $("tab-missions").innerHTML = `<h1>Mission 与分配</h1><p>这里可以观察截止、冲突、候补和替代方案；用户端只看到最终批准结果。</p><div class="toolbar"><button class="primary" data-action="run-batch">运行到期批次</button><button data-action="refresh">刷新</button></div>${table(["Mission","状态","时间","结果","管理"], rows)}`;
    bindActions();
  }
  function renderResources() {
    const rows = (state.data.resources || []).map(r => `<tr><td><b>${esc(r.name)}</b><br><span class="muted">${esc(r.type)} · ${esc(r.location)}</span></td><td>${esc(r.owner_name || r.owner_org_id)}</td><td>${statusPill(r.status)}</td><td>${esc(r.hourly_value)} / 小时<br><span class="muted">容量 ${esc(r.capacity)}</span></td><td><select data-resource-status="${r.id}"><option value="available" ${r.status === "available" ? "selected" : ""}>可用</option><option value="offline" ${r.status === "offline" ? "selected" : ""}>下架</option><option value="maintenance" ${r.status === "maintenance" ? "selected" : ""}>维护中</option></select></td></tr>`);
    $("tab-resources").innerHTML = `<h1>资源管理</h1><p>管理员可以修正资源状态，资源拥有组织仍可在用户端编辑自己的资源内容。</p>${table(["资源","所属组织","状态","价值","调整状态"], rows)}`;
    document.querySelectorAll("[data-resource-status]").forEach(select => select.addEventListener("change", async () => { try { await api(`/api/admin/resources/${select.dataset.resourceStatus}`, { method:"PATCH", body:JSON.stringify({status:select.value}) }); toast("资源状态已更新"); await load(); } catch (e) { toast(e.message, true); } }));
  }
  function renderOrganizations() {
    const rows = (state.data.organizations || []).map(o => `<tr><td><b>${esc(o.short_name || o.name)}</b><br><span class="muted">${esc(o.kind)}</span></td><td>${esc(o.credit_score)}</td><td>${esc(o.shared_hours)} / ${esc(o.available_hours)}</td><td>${esc(o.allocations_won)} / ${esc(o.allocations_lost)}</td><td><button data-action="credit" data-id="${o.id}">调整信用</button></td></tr>`);
    $("tab-organizations").innerHTML = `<h1>组织管理</h1><p>查看贡献度、信用和分配历史，公平计算的内部权重只在此管理端保留。</p>${table(["组织","信用","共享 / 可用时长","赢得 / 失去","管理"], rows)}`;
    bindActions();
  }
  function renderDemo() {
    const config = state.data.config || {}, weights = config.weights || {};
    $("tab-demo").innerHTML = `<h1>测试 Demo</h1><p>使用隔离的样例 Mission 与资源，演示上传、冲突、候补、违约和替换方案，不污染正式业务数据。</p><div class="grid-two"><div class="panel"><h2>完整流程</h2><ol><li>创建样例资源和两个时间冲突的 Mission。</li><li>截止后按偏好与 fairness 排序尝试分配。</li><li>模拟资源提供方违约，生成替代方案待确认。</li><li>输出过程报告与结果。</li></ol><button class="primary" data-action="run-demo">运行隔离 Demo</button></div><div class="panel"><h2>调度设置</h2><div class="form-grid"><label>调度器<select id="scheduler-enabled"><option value="0" ${!config.scheduler_enabled ? "selected" : ""}>手动</option><option value="1" ${config.scheduler_enabled ? "selected" : ""}>自动</option></select></label><label>间隔（秒）<input id="scheduler-interval" type="number" min="30" value="${esc(config.interval_seconds || 300)}" /></label></div><h3>公平策略（管理端可见）</h3><div class="weight-grid">${Object.entries(weights).map(([key,val])=>`<label>${esc(key)}<input data-weight="${esc(key)}" type="number" min="0" max="1" step=".01" value="${esc(val)}" /></label>`).join("")}</div><button data-action="save-config" class="primary" style="margin-top:12px">保存设置</button></div></div><div class="panel" style="margin-top:16px"><h2>最近一次 Demo 报告</h2><div id="demo-report" class="demo-report">${esc(state.data.demo_runs?.[0]?.report || "尚未运行")}</div></div>`;
    bindActions();
  }
  function renderDisputes() {
    const rows = (state.data.disputes || []).map(d => `<tr><td>#${d.id}<br><span class="muted">Mission ${d.mission_id}</span></td><td>${esc(d.category)}<br>${esc(d.description)}</td><td>${statusPill(d.status)}</td><td>${d.status === "open" ? `<button data-action="resolve" data-id="${d.id}">标记已处理</button>` : esc(d.resolution_description || "已处理")}</td></tr>`);
    $("tab-disputes").innerHTML = `<h1>冲突与争议</h1><p>处理资源状态冲突、违约记录和用户提交的争议。</p>${table(["编号","内容","状态","处理"], rows)}`;
    bindActions();
  }
  function showTab(name) { state.tab = name; document.querySelectorAll(".admin-tab-panel").forEach(p => p.hidden = p.id !== `tab-${name}`); document.querySelectorAll(".admin-tab").forEach(b => b.classList.toggle("active", b.dataset.tab === name)); }
  function bindActions() {
    document.querySelectorAll("[data-action]").forEach((button) => { if (button.dataset.bound) return; button.dataset.bound = "1"; button.addEventListener("click", async () => {
      const action = button.dataset.action;
      try {
        if (action === "refresh") return load();
        if (action === "run-batch") { await api("/api/admin/allocation/run", {method:"POST", body:JSON.stringify({})}); toast("到期批次已运行"); return load(); }
        if (action === "run-demo") { button.disabled = true; const result = await api("/api/admin/demo/run", {method:"POST",body:JSON.stringify({})}); toast("隔离 Demo 已完成"); await load(); if (result.report) $("demo-report").textContent = typeof result.report === "string" ? result.report : JSON.stringify(result.report, null, 2); return; }
        if (action === "save-config") { const weights = {}; document.querySelectorAll("[data-weight]").forEach(i => weights[i.dataset.weight] = Number(i.value)); await api("/api/admin/config", {method:"PATCH",body:JSON.stringify({scheduler_enabled:Number($("scheduler-enabled").value),interval_seconds:Number($("scheduler-interval").value),weights})}); toast("调度设置已保存"); return load(); }
        if (action === "mission-action") { await api(`/api/admin/missions/${button.dataset.id}/${button.dataset.kind}`, {method:"POST",body:JSON.stringify({})}); toast("Mission 状态已更新"); return load(); }
        if (action === "resolve") { const note = window.prompt("处理说明", "已核实并完成替代安排"); if (note === null) return; await api(`/api/admin/disputes/${button.dataset.id}/resolve`, {method:"POST",body:JSON.stringify({resolution_description:note})}); toast("争议已处理"); return load(); }
        if (action === "credit") { const value = window.prompt("新的信用分（0-100）"); if (value === null) return; await api(`/api/admin/organizations/${button.dataset.id}`, {method:"PATCH",body:JSON.stringify({credit_score:Number(value)})}); toast("组织信用已更新"); return load(); }
      } catch (e) { toast(e.message, true); }
    }); });
  }
  document.querySelectorAll(".admin-tab").forEach(btn => btn.addEventListener("click", () => showTab(btn.dataset.tab)));
  $("login-form").addEventListener("submit", async (event) => { event.preventDefault(); $("login-error").textContent = ""; try { await api("/api/admin/login", {method:"POST", body:JSON.stringify({password:$("admin-password").value})}); await load(); } catch (e) { $("login-error").textContent = e.message; } });
  $("admin-close")?.addEventListener("click", () => {
    if (typeof window.closeAdminConsole === "function") window.closeAdminConsole();
    else window.location.href = "/";
  });
  $("admin-logout").addEventListener("click", async () => { try { await api("/api/admin/logout", {method:"POST",body:"{}"}); } finally { if (typeof window.closeAdminConsole === "function") window.closeAdminConsole(); else window.location.href = "/"; } });
  api("/api/admin/bootstrap").then(load).catch(() => {});
  }
  window.initAdminConsole = initAdmin;
  if (document.getElementById("admin-login")) initAdmin();
})();
