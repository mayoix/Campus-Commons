/* Administrator-only console. The public app never imports this file. */
(() => {
  function initAdmin() {
    const state = { data: null, tab: "dashboard" };
  let syncTimer = null;
  let syncBusy = false;
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  const fmtDate = (value) => value ? new Date(value).toLocaleString("en-HK", {month:"numeric", day:"numeric", hour:"2-digit", minute:"2-digit"}) : "—";
  const fmtStatus = (status) => ({open:"Open",waitlisted:"Waitlisted",allocated:"Allocated",in_use:"In use",completed:"Completed",withdrawn:"Withdrawn",available:"Available",offline:"Offline",maintenance:"Under maintenance",reserved:"Reserved",awaiting_victim:"Waiting for requester confirmation",resolved:"Resolved",rejected:"Rejected"}[status] || status || "—");
  function toast(message, error = false) { const node = $("admin-toast"); node.textContent = message; node.style.background = error ? "#a53b3b" : "#16312b"; node.classList.add("show"); setTimeout(() => node.classList.remove("show"), 2600); }
  async function api(path, options = {}) {
    const response = await fetch(path, { credentials: "same-origin", headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
    const text = await response.text(); let body = {}; try { body = text ? JSON.parse(text) : {}; } catch (_) { body = { raw: text }; }
    if (!response.ok) { const error = new Error(body.error || `Request failed (${response.status})`); error.status = response.status; throw error; }
    return body;
  }
  async function load() { state.data = await api("/api/admin/bootstrap"); $("admin-login").hidden = true; $("admin-app").hidden = false; $("admin-logout").hidden = false; $("admin-session-label").textContent = `Admin · ${fmtDate(new Date().toISOString())}`; render(); startSync(); }
  async function sync() {
    if (!state.data || document.hidden || syncBusy || player.playing || $("demo-stage")?.classList.contains("demo-presentation")) return;
    syncBusy = true;
    try {
      const version = await api("/api/version");
      if (version.version !== state.data.version) { state.data = await api("/api/admin/bootstrap"); render(); }
    } catch (_) {
      // Keep the management console usable during a transient polling failure.
    } finally { syncBusy = false; }
  }
  function startSync() { if (!syncTimer) syncTimer = window.setInterval(sync, 5000); }
  window.stopAdminSync = () => { stopDemo(); if (syncTimer) window.clearInterval(syncTimer); syncTimer = null; };
  function table(headers, rows) { return `<div class="table-wrap"><table class="admin-table"><thead><tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows || `<tr><td colspan="${headers.length}" class="muted">No data</td></tr>`}</tbody></table></div>`; }
  function statusPill(status) { const cls = ["withdrawn","offline","maintenance","rejected"].includes(status) ? " red" : ["waitlisted","reserved","in_use","awaiting_victim"].includes(status) ? " orange" : ""; return `<span class="pill${cls}">${esc(fmtStatus(status))}</span>`; }
  function render() { if (!state.data) return; renderDashboard(); renderMissions(); renderResources(); renderOrganizations(); renderDemo(); renderDisputes(); renderHistory(); showTab(state.tab); }
  function renderDashboard() {
    const d = state.data, m = d.metrics || {}, config = d.config || {};
    $("tab-dashboard").innerHTML = `<h1>Admin console overview</h1><p>Manage resources, organizations, and platform allocation logic; users only receive results.</p>
      <div class="stat-grid"><div class="stat-card"><small>Organizations</small><strong>${d.organizations?.length ?? 0}</strong></div><div class="stat-card"><small>Resources</small><strong>${d.resources?.length ?? 0}</strong></div><div class="stat-card"><small>Missions</small><strong>${d.missions?.length ?? 0}</strong></div><div class="stat-card"><small>Waitlisted / disputes</small><strong>${(d.missions || []).filter(x=>x.status === "waitlisted").length} / ${(d.disputes || []).filter(x=>x.status === "open").length}</strong></div></div>
      <div class="grid-two"><div class="panel"><h2>Allocation scheduler</h2><p>A batch freezes options only after the deadline. Resource conflicts go to a waitlist instead of being allocated immediately.</p><div class="toolbar"><button class="primary" data-action="run-batch">Run allocation batch</button><span class="muted">Scheduler: ${config.scheduler_enabled ? "Enabled" : "Manual"}</span></div></div><div class="panel"><h2>Recent admin events</h2>${(d.events || []).slice(0,6).map(e=>`<p><b>${esc(e.title)}</b><br><span class="muted">${esc(e.detail)} · ${fmtDate(e.created_at)}</span></p>`).join("") || '<p class="muted">No events yet</p>'}</div></div><div class="panel cloud-status-panel"><h2>Data connection</h2><p>Business database: ${d.cloud?.database_shared ? `<span class="pill">Supabase Postgres · Connected</span>` : '<span class="pill orange">Local SQLite</span>'}</p><p>Dispute evidence: ${d.cloud?.evidence_configured ? `<span class="pill">Supabase Storage · ${esc(d.cloud.evidence_bucket || 'campus-evidence')}</span>` : '<span class="pill orange">Cloud evidence storage is not configured</span>'}</p><small class="muted">The user app and admin console use the same business database. Backend: ${esc(d.cloud?.database_backend || 'unknown')}</small></div>`;
    bindActions();
  }
  function renderMissions() {
    const rows = (state.data.missions || []).map(m => {
      const requirements = (m.requirements || []).map(req => `${req.label || req.type || "Resource"} (${req.type || "—"})`).join(" · ") || "No typed requirements";
      const allocated = (m.allocated_resources || []);
      const bookings = (state.data.bookings || []).filter(b => Number(b.mission_id) === Number(m.id));
      const candidateHtml = (m.plans || []).length ? `<div class="admin-resource-lines candidate-plans">${(m.plans || []).map(plan => `<div><b>${esc(plan.label || plan.id)} · match ${Math.round(Number(plan.match_score || 0) * 100)}%</b><span>${(plan.items || []).map(item => `${esc(item.resource || "Resource")} · ${esc(item.type || "")} · ${esc(item.owner || item.owner_org_id || "—")}`).join("<br>")}</span></div>`).join("")}</div>` : `<span class="muted">No candidate plans</span>`;
      const allocationHtml = allocated.length
        ? `<div class="admin-resource-lines">${allocated.map(item => `<div><b>${esc(item.resource || item.name || "Resource")}</b><span>${esc(item.type || "")} · provider ${esc(item.owner || item.owner_org_id || "—")} · ${esc(fmtStatus(item.booking_status || "active"))}</span></div>`).join("")}</div>`
        : m.status === "waitlisted" ? `<span class="muted">No feasible plan after conflict/capacity checks</span>${candidateHtml}` : m.status === "open" ? candidateHtml : `<span class="muted">No approved resources</span>`;
      const conflict = m.status === "waitlisted" ? '<span class="pill orange">Conflict / capacity waitlist</span>' : m.status === "allocated" || m.status === "in_use" || m.status === "completed" ? `<span class="pill">${bookings.length} booking(s) recorded</span>` : '<span class="muted">No batch decision yet</span>';
      return `<tr><td><div class="mission-admin-summary"><b>${esc(m.title)}</b><span>${esc(m.description || "")}</span><small>Requester: ${esc(m.requester?.short_name || m.requester_org_id || "—")} · Location: ${esc(m.location || "—")}</small><small>Needs: ${esc(requirements)}</small></div></td><td>${statusPill(m.status)}<br>${conflict}</td><td><div class="mission-admin-meta"><span><b>Submitted</b>${fmtDate(m.created_at)}</span><span><b>Cutoff</b>${fmtDate(m.deadline)}</span><span><b>Use interval</b>${fmtDate(m.start_at)} → ${fmtDate(m.end_at)}</span></div></td><td><div><b>${m.allocated_plan_id ? `Approved ${esc(m.allocated_plan_id)}` : "Allocation pending"}</b>${allocationHtml}</div></td><td><div class="row-actions">${m.status === "allocated" ? `<button data-action="mission-action" data-id="${m.id}" data-kind="checkout">Start using</button><button data-action="mission-action" data-id="${m.id}" data-kind="no-show">Record provider no-show</button>` : ""}${m.status === "in_use" ? `<button data-action="mission-action" data-id="${m.id}" data-kind="complete">Confirm return</button><button data-action="mission-action" data-id="${m.id}" data-kind="no-show">Record provider no-show</button>` : ""}${["open","waitlisted"].includes(m.status) ? `<button data-action="mission-action" data-id="${m.id}" data-kind="withdraw">Withdraw</button>` : ""}</div></td></tr>`;
    });
    $("tab-missions").innerHTML = `<h1>Missions and allocation</h1><p>Every Mission shows its submission time, cutoff, use interval, typed requirements, candidate plans, approved resources, providers, and booking state.</p><div class="toolbar"><button class="primary" data-action="run-batch">Run allocation batch</button><button data-action="refresh">Refresh</button></div>${table(["Mission details","Status / conflict","Schedule","Allocation details","Actions"], rows)}`;
    bindActions();
  }
  function renderResources() {
    const now = Date.now();
    const rows = (state.data.resources || []).map(r => {
      const used = (state.data.bookings || []).filter(b => Number(b.resource_id) === Number(r.id) && b.status === "active" && new Date(b.start_at).getTime() <= now && new Date(b.end_at).getTime() > now).reduce((sum, b) => sum + Number(b.quantity || 0), 0);
      const withinWindow = new Date(r.availability_start).getTime() <= now && new Date(r.availability_end).getTime() > now;
      const remaining = r.status === "available" && withinWindow ? Math.max(0, Number(r.capacity || 0) - used) : 0;
      return `<tr><td><b>${esc(r.name)}</b><br><span class="muted">${esc(r.type)} · ${esc(r.location)}</span></td><td>${esc(r.owner_name || r.owner_org_id)}</td><td>${statusPill(r.status)}</td><td>${esc(r.hourly_value)} / hour<br><b>Available now: ${esc(remaining)} / ${esc(r.capacity)}</b><br><span class="muted">In use now: ${esc(used)} · total capacity ${esc(r.capacity)}</span></td><td><select data-resource-status="${r.id}"><option value="available" ${r.status === "available" ? "selected" : ""}>Available</option><option value="offline" ${r.status === "offline" ? "selected" : ""}>Offline</option><option value="maintenance" ${r.status === "maintenance" ? "selected" : ""}>Under maintenance</option></select></td></tr>`; });
    $("tab-resources").innerHTML = `<h1>Resource management</h1><p>Admins can correct resource status. Resource owners can still edit their own resources in the user app.</p>${table(["Resource","Owner organization","Status","Value","Update status"], rows)}`;
    document.querySelectorAll("[data-resource-status]").forEach(select => select.addEventListener("change", async () => { try { await api(`/api/admin/resources/${select.dataset.resourceStatus}`, { method:"PATCH", body:JSON.stringify({status:select.value}) }); toast("Resource status updated"); await load(); } catch (e) { toast(e.message, true); } }));
  }
  function renderOrganizations() {
    const rows = (state.data.organizations || []).map(o => `<tr><td><b>${esc(o.short_name || o.name)}</b><br><span class="muted">${esc(o.kind)}</span></td><td>${esc(o.credit_score)}<br>${o.suspended ? '<span class="pill red">Account frozen</span>' : '<span class="pill">Normal</span>'}</td><td>${esc(o.shared_hours)} / ${esc(o.available_hours)}</td><td>${esc(o.allocations_won)} / ${esc(o.allocations_lost)}</td><td><button data-action="credit" data-id="${o.id}">Adjust credit</button></td></tr>`);
    $("tab-organizations").innerHTML = `<h1>Organization management</h1><p>Review contribution, credit, freeze status, and allocation history. A provider is unfrozen after the affected organization confirms a compensation dispute is resolved.</p>${table(["Organization / Account status","Credit","Shared / available hours","Won / lost","Actions"], rows)}`;
    bindActions();
  }
  function renderDemo() {
    const config = state.data.config || {}, weights = config.weights || {};
    const saved = state.data.demo_runs?.[0];
    const latest = saved ? {...parseDemoReport(saved.report), demo_run_id:saved.id} : null;
    const buttons = [["all","Run all scenarios"],["conflict","Conflict and fairness"],["withdrawal","Withdrawal and release"],["replacement","No-show and replacement"],["preference","Option preferences"]];
    $("tab-demo").innerHTML = `<h1>Demo studio</h1><p>Watch requests turn into decisions. These isolated teaching scenarios explain the policy without changing live bookings.</p><div class="demo-scenario-toolbar">${buttons.map(([key,label]) => `<button data-action="run-demo" data-scenario="${key}">${label}</button>`).join('')}</div><div id="demo-stage" class="demo-player"></div><details class="panel demo-written"><summary>Written report and scenario checkpoints</summary><div id="demo-report">${latest ? renderDemoReport(latest) : 'Run a scenario to create a report.'}</div></details><details class="panel demo-written"><summary>Scheduler and policy settings</summary><div class="form-grid"><label>Scheduler<select id="scheduler-enabled"><option value="0" ${!config.scheduler_enabled ? 'selected' : ''}>Manual</option><option value="1" ${config.scheduler_enabled ? 'selected' : ''}>Automatic</option></select></label><label>Interval (seconds)<input id="scheduler-interval" type="number" min="30" value="${esc(config.interval_seconds || 300)}" /></label></div><div class="weight-grid">${Object.entries(weights).map(([key,val]) => `<label>${esc(key)}<input data-weight="${esc(key)}" type="number" min="0" max="1" step=".01" value="${esc(val)}" /></label>`).join('')}</div><button data-action="save-config" class="primary">Save settings</button></details>`;
    setDemoReport(latest);
    bindActions();
  }
  function parseDemoReport(raw) {
    if (!raw) return null;
    if (typeof raw === "object") return raw;
    try { return JSON.parse(raw); } catch (_) { return { legacy: String(raw) }; }
  }
  const player = { report: null, scenario: 0, step: 0, playing: false, delay: 5000 };
  let demoTimer = null;
  function stopDemo() { if (demoTimer) clearInterval(demoTimer); demoTimer = null; player.playing = false; }
  function setDemoReport(report) {
    if (report && report.demo_run_id !== player.report?.demo_run_id) {
      stopDemo(); player.report = report; player.scenario = 0; player.step = 0;
    }
    paintDemo();
  }
  function moveDemo(delta) {
    const scenarios = player.report?.scenarios || [];
    const count = scenarios[player.scenario]?.timeline?.length || 0;
    if (delta > 0 && player.step >= count - 1) {
      if (player.scenario < scenarios.length - 1) { player.scenario++; player.step = 0; }
      else stopDemo();
    } else if (delta < 0 && player.step === 0 && player.scenario > 0) {
      player.scenario--; player.step = scenarios[player.scenario].timeline.length - 1;
    } else player.step = Math.max(0, Math.min(count - 1, player.step + delta));
    paintDemo();
  }
  function playDemo() {
    stopDemo(); player.playing = true;
    demoTimer = setInterval(() => moveDemo(1), player.delay);
    paintDemo();
  }
  function paintDemo() {
    const root = $("demo-stage");
    if (!root) return;
    const report = player.report, scenarios = report?.scenarios || [], scenario = scenarios[player.scenario];
    if (!scenario?.frames?.length) {
      root.innerHTML = '<div class="demo-empty"><h2>See the allocation happen</h2><p>Run a scenario above to create a visual replay. Older reports remain available in the written report.</p></div>';
      return;
    }
    const step = scenario.timeline[player.step], frame = scenario.frames[player.step];
    const final = player.scenario === scenarios.length - 1 && player.step === scenario.timeline.length - 1;
    const labels = {urgency:"Urgency", contribution:"Contribution", credit:"Credit", access_fairness:"Access fairness", alternative_scarcity:"Scarcity"};
    const tone = value => /withdrawn|released|unavailable/i.test(value) ? 'released' : /wait|conflict|pending|proposed|occupied|infeasible|ranking/i.test(value) ? 'waiting' : /allocated|booked|available/i.test(value) ? 'good' : 'neutral';
    const scoreCards = (scenario.fairness || []).map(candidate => {
      const rows = Object.entries(report.weights || {}).map(([key, weight]) => {
        const input = Number(candidate.components?.[key] || 0), contribution = input * Number(weight) * 100;
        return `<div class="demo-score-row"><span>${esc(labels[key] || key)}</span><span>${input.toFixed(2)} × ${Number(weight).toFixed(2)}</span><b>${contribution.toFixed(1)}</b><i style="--part:${Math.max(0,Math.min(100,contribution))}%"></i></div>`;
      }).join('');
      return `<article class="demo-score-card"><header><b>${esc(candidate.label)}</b><strong>${(Number(candidate.score)*100).toFixed(1)}<small>/100</small></strong></header>${rows}<footer>Weighted total = sum of the five contributions</footer></article>`;
    }).join('');
    root.innerHTML = `<div class="demo-player-top"><div><span class="demo-kicker">ILLUSTRATIVE SCENARIO · POLICY SNAPSHOT</span><h2>${esc(scenario.title)}</h2></div><button class="ghost" data-player="present">${root.classList.contains('demo-presentation') ? 'Exit recording view' : 'Recording view'}</button></div>
      <div class="demo-player-controls"><select aria-label="Choose demo scenario" data-player-scenario>${scenarios.map((s,i) => `<option value="${i}" ${i === player.scenario ? 'selected' : ''}>${esc(s.title)}</option>`).join('')}</select><button class="ghost" data-player="reset">↺ Restart</button><button class="ghost" data-player="back" ${player.scenario === 0 && player.step === 0 ? 'disabled' : ''}>← Back</button><button class="primary" data-player="play">${player.playing ? 'Pause' : '▶ Play'}</button><button class="ghost" data-player="next" ${final ? 'disabled' : ''}>Next →</button><select aria-label="Playback speed" data-player-speed>${[3000,5000,8000].map(ms => `<option value="${ms}" ${player.delay === ms ? 'selected' : ''}>${ms/1000}s / step</option>`).join('')}</select></div>
      <div class="demo-progress">${scenario.timeline.map((s,i) => `<button aria-label="Step ${i+1}: ${esc(s.label)}" aria-current="${i === player.step ? 'step' : 'false'}" data-player-step="${i}" class="${i === player.step ? 'active' : i < player.step ? 'done' : ''}"><span>${i+1}</span>${esc(s.label)}</button>`).join('')}</div>
      <div class="demo-live-heading" aria-live="polite"><div class="demo-clock">${esc(step.time)}<small>Scenario clock</small></div><div><span class="demo-kicker">STEP ${player.step+1} OF ${scenario.timeline.length} · ${esc(step.kind)}</span><h3>${esc(step.label)}</h3><p>${esc(step.detail)}</p></div></div>
      <div class="demo-board"><section><h3>Mission queue</h3>${frame.missions.length ? frame.missions.map(m => `<article class="demo-entity ${tone(m.status)}"><small>${esc(m.id)}</small><b>${esc(m.name)}</b><span class="demo-entity-status">${esc(m.status)}</span></article>`).join('') : '<div class="demo-entity neutral"><b>No requests yet</b><span>Publish the resource first</span></div>'}</section><section class="demo-routing"><h3>Allocation logic</h3>${frame.links.map(link => `<div class="demo-route ${tone(link.status)}"><b>${esc(link.mission)}</b><span>→</span><b>${esc(frame.resources[link.resource]?.name)}</b><small>${esc(link.status)}</small></div>`).join('') || '<div class="demo-rule">Resources enter the pool before requests are submitted.</div>'}<div class="demo-rule"><small>RULE IN EFFECT</small>${esc(frame.rule)}</div>${frame.credit_delta ? `<div class="demo-credit">Provider credit change <strong>${frame.credit_delta}</strong></div>` : ''}</section><section><h3>Resource pool</h3>${frame.resources.map(r => `<article class="demo-entity ${tone(r.status)}"><small>CAPACITY ${r.capacity} · ${r.booked_by || /unavailable|occupied/i.test(r.status) ? '0' : '1'} FREE SLOT</small><b>${esc(r.name)}</b><span class="demo-entity-status">${esc(r.status)}</span><div class="demo-capacity"><i class="${r.booked_by ? 'booked' : /unavailable|occupied/i.test(r.status) ? 'blocked' : ''}"></i><span>${r.booked_by ? `Booking: ${esc(r.booked_by)}` : /unavailable|occupied/i.test(r.status) ? 'Not assignable' : 'No booking yet'}</span></div></article>`).join('')}</section></div>
      ${frame.show_scores ? `<section class="demo-live-scores"><h3>Why this order? <small>Input × weight × 100 = points</small></h3><div class="fairness-grid">${scoreCards}</div></section>` : `<div class="demo-score-placeholder">${scenario.key === 'replacement' ? 'The original booking is released. A proposed replacement is not a booking until the requester confirms.' : 'Fairness is evaluated during the batch. Before the cutoff, requests remain open.'}</div>`}
      <div class="demo-narration"><span>${player.step === scenario.timeline.length-1 ? 'OUTCOME' : 'WHAT CHANGED'}</span><strong>${esc(player.step === scenario.timeline.length-1 ? scenario.outcome : step.detail)}</strong></div>`;
    root.querySelectorAll('[data-player]').forEach(button => button.addEventListener('click', () => {
      const action = button.dataset.player;
      if (action === 'present') { root.classList.toggle('demo-presentation'); paintDemo(); }
      if (action === 'play') { if (player.playing) { stopDemo(); paintDemo(); } else { if (final) { player.scenario=0; player.step=0; } playDemo(); } }
      if (action === 'back' || action === 'next') { stopDemo(); moveDemo(action === 'back' ? -1 : 1); }
      if (action === 'reset') { stopDemo(); player.step=0; paintDemo(); }
    }));
    root.querySelector('[data-player-scenario]').addEventListener('change', event => { stopDemo(); player.scenario=Number(event.target.value); player.step=0; paintDemo(); });
    root.querySelector('[data-player-speed]').addEventListener('change', event => { player.delay=Number(event.target.value); if (player.playing) playDemo(); else paintDemo(); });
    root.querySelectorAll('[data-player-step]').forEach(button => button.addEventListener('click', () => { stopDemo(); player.step=Number(button.dataset.playerStep); paintDemo(); }));
  }
  function evidenceSource(item) {
    const source = item?.endpoint || item?.url || item?.data || "";
    if (/^(https?:\/\/|\/api\/)/i.test(source)) return source;
    if (/^data:(image\/(png|jpe?g|gif|webp)|application\/pdf|video\/[a-z0-9.+-]+);base64,/i.test(source)) return source;
    return "";
  }
  function showDisputeDetail(disputeId) {
    const dispute = (state.data.disputes || []).find(item => String(item.id) === String(disputeId));
    if (!dispute) return;
    document.querySelectorAll(".admin-detail-backdrop").forEach(node => node.remove());
    const evidence = Array.isArray(dispute.evidence) ? dispute.evidence : [];
    const evidenceHtml = evidence.length ? evidence.map((item, index) => { const source = evidenceSource(item); const label = esc(item.name || `Evidence ${index + 1}`); const media = source && /^image\//i.test(item.type || '') ? `<img src="${esc(source)}" alt="${label}" class="evidence-preview" />` : source && /^video\//i.test(item.type || '') ? `<video class="evidence-preview" controls src="${esc(source)}"></video>` : ''; return `<div class="evidence-card">${media}<div class="evidence-card-foot"><b>${label}</b><span>${esc(item.type || 'File')} · ${esc(item.size || 0)} bytes</span>${source ? `<a class="evidence-open" href="${esc(source)}" target="_blank" rel="noopener" download="${label}">${media ? 'Open / download' : 'View file'}</a>` : '<span class="muted">File content unavailable</span>'}</div></div>`; }).join('') : '<div class="demo-empty">No evidence uploaded</div>';
    const backdrop = document.createElement('div');
    backdrop.className = 'admin-detail-backdrop';
    backdrop.innerHTML = `<div class="admin-detail-dialog" role="dialog" aria-modal="true"><div class="admin-detail-head"><div><span class="eyebrow">Dispute details #${esc(dispute.id)}</span><h2>${esc(dispute.category || 'Dispute')}</h2></div><button class="ghost" type="button" data-close-dispute-detail>Close</button></div><div class="admin-detail-meta"><div><small>Mission</small><strong>#${esc(dispute.mission_id)}</strong></div><div><small>Affected organization</small><strong>${esc(dispute.reporter?.short_name || dispute.reporter_org_id || '—')}</strong></div><div><small>Provider at fault</small><strong>${esc(dispute.accused?.short_name || dispute.accused_org_id || 'Unknown')}</strong></div><div><small>Status</small><strong>${esc(fmtStatus(dispute.status))}</strong></div><div><small>Compensation</small><strong>${Number(dispute.compensation_amount || 0) > 0 ? `HKD ${Number(dispute.compensation_amount).toFixed(2)}` : 'Not requested'}</strong></div><div><small>Credit</small><strong>${dispute.accused ? `${esc(dispute.accused.credit_score)} points · ${dispute.accused.suspended ? 'Account frozen' : 'Normal'}` : '—'}</strong></div></div><div class="admin-detail-copy"><h3>Dispute details</h3><p>${esc(dispute.description || '—')}</p>${dispute.resolution_description ? `<h3>Resolution record</h3><p>${esc(dispute.resolution_description)}</p>` : ''}</div><h3>Evidence file</h3><div class="evidence-grid">${evidenceHtml}</div></div>`;
    document.body.appendChild(backdrop);
    backdrop.addEventListener('click', event => { if (event.target === backdrop || event.target.closest('[data-close-dispute-detail]')) backdrop.remove(); });
  }
  function demoKindClass(kind) { return ({input:"input",batch:"batch",decision:"decision",exception:"exception",result:"result"}[kind] || "input"); }
  function renderDemoReport(report) {
    if (report.legacy) return `<pre class="demo-report">${esc(report.legacy)}</pre>`;
    const scenarios = report.scenarios || [];
    return scenarios.map((scenario) => `<article class="demo-scenario"><div class="demo-scenario-head"><div><span class="demo-kicker">${esc(scenario.key || 'scenario')}</span><h2>${esc(scenario.title)}</h2><p>${esc(scenario.purpose)}</p></div><span class="pill">${esc(scenario.outcome || 'Completed')}</span></div><div class="demo-meta"><div><small>Participants</small><strong>${(scenario.actors || []).map(esc).join(' · ')}</strong></div><div><small>Batch clock</small><strong>Submitted ${esc(scenario.batch?.submitted_at)} → Deadline ${esc(scenario.batch?.cutoff_at)} → Executed ${esc(scenario.batch?.executed_at)}</strong></div></div><div class="demo-section"><h3>Process timeline</h3><div class="demo-timeline">${(scenario.timeline || []).map((step, index) => `<div class="demo-step"><div class="demo-step-marker ${demoKindClass(step.kind)}">${index + 1}</div><div class="demo-step-body"><div class="demo-step-top"><b>${esc(step.label)}</b><span>${esc(step.time)}</span></div><p>${esc(step.detail)}</p><span class="demo-state ${demoKindClass(step.kind)}">${esc(step.status)}</span></div></div>`).join('')}</div></div><div class="demo-section"><div class="demo-section-title"><h3>Fairness scoring process</h3><span class="demo-formula">${esc(report.formula || 'Calculated from the policy snapshot')}</span></div><div class="fairness-grid">${(scenario.fairness || []).map(candidate => `<div class="fairness-card"><div class="fairness-card-top"><b>${esc(candidate.label)}</b><strong>${Math.round(Number(candidate.score || 0) * 100)}<small>/100</small></strong></div><div class="score-track"><i style="width:${Math.max(0,Math.min(100,Number(candidate.score || 0) * 100))}%"></i></div><div class="fairness-components">${Object.entries(candidate.components || {}).map(([key,val]) => `<span><em>${esc(key)}</em>${esc(val)}</span>`).join('')}</div><div class="fairness-result ${candidate.result === 'winner' || candidate.result === 'allocated' ? 'good' : 'waiting'}">${candidate.result === 'winner' || candidate.result === 'allocated' ? '✓ ' : '↳ '}${esc(candidate.result)} · ${esc(candidate.reason)}</div></div>`).join('')}</div></div><div class="demo-section demo-assertions"><h3>Scenario checkpoints</h3><div>${(scenario.assertions || []).map(item => `<span>✓ ${esc(item)}</span>`).join('')}</div></div></article>`).join('');
  }
  function renderDisputes() {
    const rows = (state.data.disputes || []).map(d => { const evidence = Array.isArray(d.evidence) ? d.evidence : []; const amount = Number(d.compensation_amount || 0); const accused = d.accused?.short_name || d.accused_org_id || "Unknown"; const detailButton = `<button data-action="dispute-detail" data-id="${d.id}">View details</button>`; const action = d.status === "open" ? `<div class="row-actions">${detailButton}<button data-action="dispute-review" data-kind="upheld" data-id="${d.id}">Uphold and reduce credit</button><button data-action="dispute-review" data-kind="rejected" data-id="${d.id}">Reject</button></div>` : d.status === "awaiting_victim" ? `<div class="row-actions">${detailButton}<span class="muted">Frozen; waiting for the affected organization to mark it resolved</span></div>` : `<div class="row-actions">${detailButton}<span class="muted">${esc(d.resolution_description || "Process complete")}</span></div>`; const evidenceNames = evidence.map(item => esc(item.name)).join(', '); return `<tr><td>#${d.id}<br><span class="muted">Mission ${d.mission_id}</span></td><td><b>${esc(d.category)}</b><br>${esc(d.description)}<br><span class="muted">Affected organization: ${esc(d.reporter?.short_name || d.reporter_org_id)} · Provider at fault: ${esc(accused)}</span></td><td>${amount > 0 ? `<b>HKD ${amount.toFixed(2)}</b><br>` : ''}${evidence.length ? `<span class="pill">${evidence.length} evidence file(s)</span><br><span class="muted">${evidenceNames}</span>` : '<span class="muted">No compensation requested</span>'}</td><td>${statusPill(d.status)}<br><span class="muted">${esc(d.compensation_status || '')}</span></td><td>${action}</td></tr>`; });
    $("tab-disputes").innerHTML = `<h1>Conflicts and disputes</h1><p>Admins review the evidence first. Upholding provider fault reduces credit automatically; compensation approval freezes the provider until the affected organization confirms resolution.</p>${table(["ID","Dispute details","Compensation / evidence","Status","Action"], rows)}`;
    bindActions();
  }
  function renderHistory() {
    const rows = (state.data.history || []).map(item => {
      const snapshot = item.snapshot || {};
      const entity = ({resource:"Resource",mission:"Mission",dispute:"Dispute",organization:"Organization",platform:"Platform"}[item.entity_type] || item.entity_type || "Record");
      const label = snapshot.title || snapshot.name || `${entity} #${item.entity_id}`;
      const action = item.action === "created" ? "Created" : item.action === "updated" ? "Updated" : item.action === "preferences_updated" ? "Updated option preferences" : item.action === "replacement_pending" ? "Waiting for replacement" : item.action === "resolved" ? "Processed" : item.action.startsWith("status_") ? `Status: ${fmtStatus(item.action.slice(7))}` : item.action || "Change";
      return `<tr><td><b>${esc(label)}</b><br><span class="muted">${esc(entity)} #${esc(item.entity_id)}</span></td><td>${esc(action)}</td><td>${esc(snapshot.status || "—")}</td><td>${fmtDate(item.created_at)}</td></tr>`;
    }).join("");
    $("tab-history").innerHTML = `<h1>Persistent history</h1><p>All resource, Mission, dispute, and platform changes are written to the same business database, which both apps read.</p><div class="toolbar"><button data-action="refresh">Refresh</button></div>${table(["Item","Change","Current status","Time"], rows)}`;
    bindActions();
  }
  function showTab(name) { if (name !== "demo") stopDemo(); state.tab = name; document.querySelectorAll(".admin-tab-panel").forEach(p => p.hidden = p.id !== `tab-${name}`); document.querySelectorAll(".admin-tab").forEach(b => b.classList.toggle("active", b.dataset.tab === name)); }
  function bindActions() {
    document.querySelectorAll("[data-action]").forEach((button) => { if (button.dataset.bound) return; button.dataset.bound = "1"; button.addEventListener("click", async () => {
      const action = button.dataset.action;
      try {
        if (action === "refresh") return load();
        if (action === "run-batch") { await api("/api/admin/allocation/run", {method:"POST", body:JSON.stringify({force:true})}); toast("Due batch completed"); return load(); }
        if (action === "run-demo") { button.disabled = true; const result = await api("/api/admin/demo/run", {method:"POST",body:JSON.stringify({scenario: button.dataset.scenario || "all"})}); toast("Explainable demo completed"); await load(); if (result.report) { setDemoReport(result.report); playDemo(); } return; }
        if (action === "dispute-detail") { showDisputeDetail(button.dataset.id); return; }
        if (action === "save-config") { const weights = {}; document.querySelectorAll("[data-weight]").forEach(i => weights[i.dataset.weight] = Number(i.value)); await api("/api/admin/config", {method:"PATCH",body:JSON.stringify({scheduler_enabled:Number($("scheduler-enabled").value),interval_seconds:Number($("scheduler-interval").value),weights})}); toast("Scheduler settings saved"); return load(); }
        if (action === "mission-action") { const payload = {}; if (button.dataset.kind === "no-show") { const mission = (state.data.missions || []).find(item => String(item.id) === String(button.dataset.id)); const providerIds = []; const plan = (mission?.plans || []).find(item => item.id === mission.allocated_plan_id) || (mission?.plans || [])[0]; (plan?.items || []).forEach(item => { const resource = (state.data.resources || []).find(candidate => Number(candidate.id) === Number(item.resource_id)); const ownerId = resource?.owner_org_id ?? item.owner_org_id; if (ownerId && !providerIds.includes(Number(ownerId))) providerIds.push(Number(ownerId)); }); if (providerIds.length > 1) { const selected = window.prompt(`Enter the provider organization ID at fault (options: ${providerIds.join(', ')})`, String(providerIds[0])); if (selected === null) return; payload.provider_org_id = Number(selected); } else if (providerIds.length === 1) payload.provider_org_id = providerIds[0]; } await api(`/api/admin/missions/${button.dataset.id}/${button.dataset.kind}`, {method:"POST",body:JSON.stringify(payload)}); toast(button.dataset.kind === "no-show" ? "Provider credit reduced and no-show recorded" : "Mission status updated"); return load(); }
        if (action === "dispute-review") { const note = window.prompt(button.dataset.kind === "upheld" ? "Resolution note after upholding the dispute" : "Reason for rejection", button.dataset.kind === "upheld" ? "Evidence reviewed; provider fault confirmed" : "Evidence is insufficient to uphold this dispute"); if (note === null) return; await api(`/api/admin/disputes/${button.dataset.id}/resolve`, {method:"POST",body:JSON.stringify({outcome:button.dataset.kind,resolution_description:note})}); toast(button.dataset.kind === "upheld" ? "Provider credit reduced and dispute status updated" : "Dispute rejected"); return load(); }
        if (action === "credit") { const value = window.prompt("New credit score (0–100)"); if (value === null) return; await api(`/api/admin/organizations/${button.dataset.id}`, {method:"PATCH",body:JSON.stringify({credit_score:Number(value)})}); toast("Organization credit updated"); return load(); }
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
