/* Campus Commons user client. */
const state = { data: null, view: 'overview', mission: null };
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const arr = value => Array.isArray(value) ? value : [];
const num = value => Number.isFinite(Number(value)) ? Number(value) : null;
const dash = value => value === null || value === undefined || value === '' ? '—' : value;
const fmtDate = value => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return `${date.toLocaleDateString('zh-HK', { month: 'short', day: 'numeric' })} ${date.toLocaleTimeString('zh-HK', { hour: '2-digit', minute: '2-digit' })}`;
};
const fmtRelative = value => {
  if (!value) return '时间待定';
  const delta = new Date(value).getTime() - Date.now();
  if (!Number.isFinite(delta)) return '时间待定';
  if (delta < 0) return '已到时间';
  const hours = Math.round(delta / 36e5);
  return hours < 24 ? `${hours} 小时后` : `${Math.round(hours / 24)} 天后`;
};
const localInput = value => {
  const date = value ? new Date(value) : new Date();
  if (Number.isNaN(date.getTime())) return '';
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};
const iso = value => value ? new Date(value).toISOString() : null;

async function api(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } });
  let body = {};
  try { body = await response.json(); } catch (_) { /* empty response */ }
  if (!response.ok) throw new Error(body.error || body.message || '请求失败，请稍后重试');
  return body;
}
function toast(message, bad = false) {
  const node = $('#toast');
  if (!node) return;
  node.textContent = message;
  node.style.background = bad ? '#9c4e48' : 'var(--deep)';
  node.classList.add('show');
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => node.classList.remove('show'), 3000);
}
function org() { return state.data?.organization || {}; }
function ownResource(resource) { return Number(resource.owner_org_id) === Number(org().id); }
function missionStatus(status) {
  const labels = { open: '申请中', waitlisted: '候补中', allocated: '已获批', frozen: '已获批', in_use: '使用中', completed: '已完成', withdrawn: '已取消', replacement_pending: '待替换' };
  return labels[status] || status || '—';
}
function statusTag(status) { return `<span class="mission-status status-${esc(status || 'unknown')}">${esc(missionStatus(status))}</span>`; }
function resourceStatus(status) {
  const labels = { available: '可申请', offline: '暂不可用', maintenance: '维护中', reserved: '已有预约' };
  return labels[status] || status || '—';
}
function resourceStatusClass(status) { return status === 'available' ? 'green' : status === 'maintenance' ? 'orange' : 'purple'; }
function typeLabel(type) { return ({ equipment: '设备', skill: '技能', space: '场地', people: '人力' }[type] || type || '资源'); }
function statusCounts(missions) { return missions.reduce((result, item) => { result[item.status] = (result[item.status] || 0) + 1; return result; }, {}); }

function navSetup() {
  $$('.nav-item, .mini-link').forEach(button => button.addEventListener('click', () => setView(button.dataset.view)));
}
function setView(view) {
  if (!['overview', 'missions', 'resources', 'profile'].includes(view)) view = 'overview';
  state.view = view;
  $$('.view').forEach(section => section.classList.toggle('active', section.id === `view-${view}`));
  $$('.nav-item').forEach(button => button.classList.toggle('active', button.dataset.view === view));
  const labels = { overview: '总览', missions: 'Mission', resources: '资源池', profile: '组织档案' };
  $('#page-label').textContent = labels[view];
  renderView();
}
function renderView() {
  if (!state.data) return;
  ({ overview: renderOverview, missions: renderMissions, resources: renderResources, profile: renderProfile }[state.view] || renderOverview)();
}

function renderOverview() {
  const data = state.data;
  const missions = arr(data.missions);
  const resources = arr(data.resources);
  const mine = resources.filter(ownResource);
  const counts = statusCounts(missions);
  const credit = num(org().credit_score);
  const sharedHours = num(org().shared_hours);
  const availableHours = num(org().available_hours);
  const events = arr(data.events).slice(0, 5);
  $('#view-overview').innerHTML = `
    <div class="view-heading"><div><div class="eyebrow">组织工作台 · ${esc(org().short_name || org().name)}</div><h1>让闲置能力，流动起来。</h1><p>这里显示 ${esc(org().short_name || '本组织')} 的 Mission、资源和通知。</p></div><button class="primary-btn" id="new-mission" type="button">+ 提交新 Mission</button></div>
    <div class="stat-grid">
      <div class="stat-card"><div class="stat-top"><span>我的资源</span><span class="stat-icon green" aria-hidden="true">▦</span></div><div class="stat-value">${mine.length}</div><div class="stat-foot">其中 ${mine.filter(r => r.status === 'available').length} 个可申请</div></div>
      <div class="stat-card"><div class="stat-top"><span>我的 Mission</span><span class="stat-icon blue" aria-hidden="true">◎</span></div><div class="stat-value">${missions.length}</div><div class="stat-foot">${counts.allocated || 0} 个已获批</div></div>
      <div class="stat-card"><div class="stat-top"><span>信用分</span><span class="stat-icon purple" aria-hidden="true">◇</span></div><div class="stat-value">${credit === null ? '—' : Math.round(credit)}</div><div class="stat-foot">平台记录的组织信用</div></div>
      <div class="stat-card"><div class="stat-top"><span>共享时长</span><span class="stat-icon orange" aria-hidden="true">◷</span></div><div class="stat-value">${sharedHours === null ? '—' : sharedHours}<small style="font-size:14px;color:#788983">${sharedHours === null ? '' : 'h'}</small></div><div class="stat-foot">可验证时长 ${availableHours === null ? '—' : `${availableHours}h`}</div></div>
    </div>
    <div class="grid-2">
      <div class="panel"><div class="panel-head"><div><h2>我的 Mission</h2><small>只显示本组织提交的申请</small></div><button class="text-link" id="go-missions" type="button">查看全部 →</button></div><div class="mission-list">${missions.length ? missions.slice(0, 5).map(missionRow).join('') : '<div class="empty">还没有 Mission</div>'}</div></div>
      <div class="panel"><div class="panel-head"><div><h2>最近活动</h2><small>与本组织相关的通知</small></div><button class="text-link" id="go-activity" type="button">查看全部 →</button></div><div class="activity-list">${events.length ? events.map(eventRow).join('') : '<div class="empty">暂无通知</div>'}</div></div>
    </div>
    <div class="panel contribution-panel"><div class="panel-head"><div><h2>组织贡献</h2><small>资源共享和 Mission 完成记录</small></div><button class="secondary-btn" id="go-profile" type="button">查看组织档案</button></div><div class="contribution-grid"><div><span>信用分</span><strong>${credit === null ? '—' : `${Math.round(credit)} / 100`}</strong></div><div><span>实际共享</span><strong>${sharedHours === null ? '—' : `${sharedHours}h`}</strong></div><div><span>可验证可用时间</span><strong>${availableHours === null ? '—' : `${availableHours}h`}</strong></div><div><span>成功完成 Mission</span><strong>${dash(org().allocations_won)}</strong></div></div></div>`;
  $('#new-mission').onclick = openMissionModal;
  $('#go-missions').addEventListener('click', () => setView('missions'));
  $('#go-profile').addEventListener('click', () => setView('profile'));
  $('#go-activity').addEventListener('click', openActivityModal);
  $$('.mission-row[data-id]', $('#view-overview')).forEach(row => row.addEventListener('click', () => openMissionDetail(row.dataset.id)));
}
function missionRow(mission) {
  const score = num(mission.fairness?.score);
  return `<button class="mission-row" data-id="${esc(mission.id)}" type="button"><div class="mission-badge">${['allocated', 'frozen', 'in_use', 'completed'].includes(mission.status) ? '✓' : 'M'}</div><div><div class="mission-title">${esc(mission.title)}</div><div class="mission-meta">${fmtRelative(mission.deadline)} · ${arr(mission.plans).length} 个可选方案</div></div>${statusTag(mission.status)}${score === null ? '' : `<span class="score">${Math.round(score * 100)}</span>`}<span class="chevron" aria-hidden="true">›</span></button>`;
}
function eventRow(event) { return `<div class="activity"><div class="activity-line" aria-hidden="true"></div><div><strong>${esc(event.title || '平台通知')}</strong><small>${esc(event.detail || '')}</small><time>${fmtDate(event.created_at)}</time></div></div>`; }

function renderMissions() {
  const missions = arr(state.data.missions);
  const filters = [['all', '全部'], ['open', '申请中'], ['waitlisted', '候补中'], ['allocated', '已获批'], ['in_use', '使用中'], ['completed', '已完成'], ['withdrawn', '已取消']];
  $('#view-missions').innerHTML = `<div class="view-heading"><div><div class="eyebrow">Mission</div><h1>提交和管理你的需求。</h1><p>在申请截止前选择可接受方案；获批后可以开始使用并完成归还。</p></div><button class="primary-btn" id="new-mission" type="button">+ 提交新 Mission</button></div><div class="filter-row">${filters.map(([key, label]) => `<button class="filter-btn ${key === 'all' ? 'active' : ''}" data-filter="${key}" type="button">${label} ${key === 'all' ? missions.length : missions.filter(m => m.status === key).length}</button>`).join('')}</div><div id="mission-cards">${missions.length ? missions.map(missionCard).join('') : '<div class="panel"><div class="empty">还没有 Mission。提交一个需求开始匹配资源。</div></div>'}</div>`;
  $('#new-mission').onclick = openMissionModal;
  $$('.filter-btn').forEach(button => button.addEventListener('click', () => { $$('.filter-btn').forEach(item => item.classList.remove('active')); button.classList.add('active'); const key = button.dataset.filter; $('#mission-cards').innerHTML = missions.filter(m => key === 'all' || m.status === key).map(missionCard).join('') || '<div class="panel"><div class="empty">暂无符合条件的 Mission</div></div>'; bindMissionCards(); }));
  bindMissionCards();
}
function missionCard(mission) {
  const score = num(mission.fairness?.score);
  return `<article class="mission-card"><div class="mission-card-head"><div class="mission-badge">${['allocated', 'frozen', 'in_use', 'completed'].includes(mission.status) ? '✓' : 'M'}</div><div><h3>${esc(mission.title)}</h3><p>${esc(mission.description)}</p><div class="mission-card-meta"><span>◷ ${fmtDate(mission.start_at)}</span><span>⌖ ${esc(mission.location)}</span><span>▣ ${arr(mission.requirements).length} 项要求</span></div></div>${statusTag(mission.status)}</div><div class="mission-card-actions"><span class="tag ${arr(mission.plans).length ? 'green' : ''}">${arr(mission.plans).length} 个可选方案${score === null ? '' : ` · 公平分数 ${Math.round(score * 100)}`}</span><button class="secondary-btn" data-open-mission="${esc(mission.id)}" type="button">查看详情 →</button></div></article>`;
}
function bindMissionCards() { $$('[data-open-mission]').forEach(button => button.addEventListener('click', () => openMissionDetail(button.dataset.openMission))); }

function resourceSort(resources, mode) {
  const statusOrder = { available: 0, offline: 1, maintenance: 2, reserved: 3 };
  return [...resources].sort((a, b) => {
    if (mode === 'time') return (new Date(a.availability_start || 0) - new Date(b.availability_start || 0)) || String(a.name).localeCompare(String(b.name));
    if (mode === 'location') return String(a.location || '').localeCompare(String(b.location || ''), 'zh-Hans', { sensitivity: 'base' }) || String(a.name).localeCompare(String(b.name));
    if (mode === 'price') return (num(a.hourly_value) ?? Infinity) - (num(b.hourly_value) ?? Infinity) || String(a.name).localeCompare(String(b.name));
    return (statusOrder[a.status] ?? 9) - (statusOrder[b.status] ?? 9) || String(a.name).localeCompare(String(b.name));
  });
}
function resourceRows(resources) {
  return resources.map(resource => `<tr><td><strong>${esc(resource.name)}</strong><small>${esc(resource.features || resource.capability || '')}</small></td><td><span class="tag blue">${esc(typeLabel(resource.type))}</span></td><td>${esc(resource.owner_name || resource.owner_short_name || '')}</td><td>${fmtDate(resource.availability_start)}<br><span class="subtle">至 ${fmtDate(resource.availability_end)}</span></td><td>${esc(resource.location || '—')}</td><td><span class="tag ${resourceStatusClass(resource.status)}">${esc(resourceStatus(resource.status))}</span></td><td>${num(resource.hourly_value) === null ? '—' : `$${num(resource.hourly_value)}`} ${ownResource(resource) ? `<button class="edit-resource-link" data-edit-resource="${esc(resource.id)}" type="button">编辑</button>` : ''}</td></tr>`).join('');
}
function renderResources() {
  const resources = arr(state.data.resources);
  const own = resources.filter(ownResource);
  $('#view-resources').innerHTML = `<div class="view-heading"><div><div class="eyebrow">共享资源池</div><h1>找到可以使用的资源。</h1><p>按状态、可用时间、位置或价格排序。你上架的资源可以在组织档案中编辑。</p></div><button class="primary-btn" id="new-resource" type="button">+ 开放资源</button></div><div class="stat-grid"><div class="stat-card"><div class="stat-top"><span>可申请资源</span><span class="stat-icon green" aria-hidden="true">▦</span></div><div class="stat-value">${resources.filter(r => r.status === 'available').length}</div><div class="stat-foot">来自共享网络</div></div><div class="stat-card"><div class="stat-top"><span>我的资源</span><span class="stat-icon blue" aria-hidden="true">◌</span></div><div class="stat-value">${own.length}</div><div class="stat-foot">可在组织档案管理</div></div><div class="stat-card"><div class="stat-top"><span>我的可用资源</span><span class="stat-icon purple" aria-hidden="true">✓</span></div><div class="stat-value">${own.filter(r => r.status === 'available').length}</div><div class="stat-foot">状态由组织维护</div></div></div><div class="panel table-panel"><div class="panel-head"><div><h2>资源目录</h2><small>公共资源可浏览；只有自己的资源显示编辑入口</small></div><label class="sort-label" for="resource-sort">排序<select id="resource-sort" class="resource-sort"><option value="status">状态排序</option><option value="time">可用时间：早 → 晚</option><option value="location">位置：A → Z</option><option value="price">价格：低 → 高</option></select></label></div><div class="table-scroll"><table class="data-table"><thead><tr><th>资源</th><th>类型</th><th>提供组织</th><th>可用时间</th><th>位置</th><th>状态</th><th>价值 / h</th></tr></thead><tbody id="resource-table-body">${resourceRows(resourceSort(resources, 'status')) || '<tr><td colspan="7"><div class="empty">暂无资源</div></td></tr>'}</tbody></table></div></div>`;
  $('#new-resource').addEventListener('click', () => openResourceModal());
  $('#resource-sort').addEventListener('change', event => { $('#resource-table-body').innerHTML = resourceRows(resourceSort(resources, event.target.value)) || '<tr><td colspan="7"><div class="empty">暂无资源</div></td></tr>'; bindResourceLinks(); });
  bindResourceLinks();
}
function bindResourceLinks() { $$('[data-edit-resource]').forEach(button => button.addEventListener('click', () => openResourceModal(button.dataset.editResource))); }

function renderProfile() {
  const mine = arr(state.data.resources).filter(ownResource);
  const credit = num(org().credit_score);
  $('#view-profile').innerHTML = `<div class="view-heading"><div><div class="eyebrow">组织档案</div><h1>${esc(org().name || org().short_name || '我的组织')}</h1><p>${esc(org().kind || '共享网络成员')} · 这里管理本组织已上架的资源。</p></div><button class="primary-btn" id="profile-new-resource" type="button">+ 开放资源</button></div><div class="profile-grid profile-page-stats"><div class="profile-stat"><strong>${credit === null ? '—' : Math.round(credit)}</strong><small>信用分 / 100</small></div><div class="profile-stat"><strong>${dash(org().shared_hours)}${org().shared_hours === undefined ? '' : 'h'}</strong><small>实际共享时长</small></div><div class="profile-stat"><strong>${dash(org().available_hours)}${org().available_hours === undefined ? '' : 'h'}</strong><small>可验证可用时长</small></div><div class="profile-stat"><strong>${dash(org().allocations_won)}</strong><small>成功完成 Mission</small></div></div><div class="panel table-panel profile-resources"><div class="panel-head"><div><h2>我的资源</h2><small>修改名称、能力、时间、状态等信息</small></div><span class="tag blue">${mine.length} 项</span></div><div class="table-scroll"><table class="data-table"><thead><tr><th>资源</th><th>类型</th><th>能力 / 特征</th><th>时间</th><th>状态</th><th>操作</th></tr></thead><tbody>${mine.length ? mine.map(profileResourceRow).join('') : '<tr><td colspan="6"><div class="empty">还没有上架资源</div></td></tr>'}</tbody></table></div></div>`;
  $('#profile-new-resource').addEventListener('click', () => openResourceModal());
  $$('[data-edit-resource]', $('#view-profile')).forEach(button => button.addEventListener('click', () => openResourceModal(button.dataset.editResource)));
}
function profileResourceRow(resource) { return `<tr><td><strong>${esc(resource.name)}</strong><small>${esc(resource.location || '—')}</small></td><td>${esc(typeLabel(resource.type))}</td><td>${esc(resource.capability || '—')}<small>${esc(resource.features || '')}</small></td><td>${fmtDate(resource.availability_start)}<br><span class="subtle">至 ${fmtDate(resource.availability_end)}</span></td><td><span class="tag ${resourceStatusClass(resource.status)}">${esc(resourceStatus(resource.status))}</span></td><td><button class="secondary-btn compact" data-edit-resource="${esc(resource.id)}" type="button">编辑</button></td></tr>`; }

function openMissionModal() {
  $('#modal').innerHTML = `<div class="modal-head"><h2>提交 Mission</h2><button class="close-btn" data-close type="button" aria-label="关闭">×</button></div><p class="modal-intro">用几句话描述需求，系统会生成可接受方案。申请截止时间由平台按使用开始时间自动设置。</p><form id="mission-form"><div class="field"><label for="mission-title">标题</label><input id="mission-title" name="title" required placeholder="例如：Student product shoot" /></div><div class="field"><label for="mission-description">需要什么</label><textarea id="mission-description" name="description" required placeholder="例如：需要相机、灯光和小型场地"></textarea></div><div class="form-grid"><div class="field"><label for="mission-location">地点</label><input id="mission-location" name="location" required placeholder="Main Building" /></div><div class="field"><label for="mission-start">开始使用</label><input id="mission-start" type="datetime-local" name="start_at" required /></div><div class="field"><label for="mission-end">结束使用</label><input id="mission-end" type="datetime-local" name="end_at" required /></div></div><div class="form-actions"><button class="secondary-btn" data-close type="button">取消</button><button class="primary-btn" type="submit">提交申请 →</button></div></form>`;
  openModal();
  $('#mission-form').addEventListener('submit', submitMission);
}
async function submitMission(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  const payload = { title: form.get('title'), description: form.get('description'), location: form.get('location'), start_at: iso(form.get('start_at')), end_at: iso(form.get('end_at')) };
  try { const result = await api('/api/missions', { method: 'POST', body: JSON.stringify(payload) }); closeModal(); await refresh(); setView('missions'); toast('Mission 已提交，等待申请窗口截止'); if (result.mission?.id) openMissionDetail(result.mission.id); } catch (error) { toast(error.message, true); }
}

function resourceForm(resource) {
  const editing = Boolean(resource);
  const base = new Date(Date.now() + 24 * 36e5);
  const end = new Date(Date.now() + 72 * 36e5);
  const value = key => resource?.[key] ?? '';
  return `<div class="modal-head"><h2>${editing ? '编辑我的资源' : '开放资源'}</h2><button class="close-btn" data-close type="button" aria-label="关闭">×</button></div><p class="modal-intro">${editing ? '更新本组织已上架资源的内容或状态。已有预约的资源可能需要管理员处理。' : '发布资源的临时使用权，所有权仍属于你的组织。'}</p><form id="resource-form" data-resource-id="${editing ? esc(resource.id) : ''}"><div class="form-grid"><div class="field full"><label for="resource-name">资源名称</label><input id="resource-name" name="name" required value="${esc(value('name'))}" placeholder="例如：Portable lighting set" /></div><div class="field"><label for="resource-type">类型</label><select id="resource-type" name="type"><option value="equipment" ${value('type') === 'equipment' ? 'selected' : ''}>设备</option><option value="skill" ${value('type') === 'skill' ? 'selected' : ''}>技能</option><option value="space" ${value('type') === 'space' ? 'selected' : ''}>场地</option><option value="people" ${value('type') === 'people' ? 'selected' : ''}>人力</option></select></div><div class="field"><label for="resource-capability">能力关键词</label><input id="resource-capability" name="capability" required value="${esc(value('capability'))}" placeholder="camera, 4K video" /></div><div class="field full"><label for="resource-features">具体特征</label><input id="resource-features" name="features" value="${esc(value('features'))}" placeholder="规格、语言、座位数或使用条件" /></div><div class="field"><label for="resource-location">位置</label><input id="resource-location" name="location" required value="${esc(value('location'))}" placeholder="Main Building" /></div><div class="field"><label for="resource-capacity">容量</label><input id="resource-capacity" type="number" min="1" step="1" name="capacity" value="${esc(value('capacity') || 1)}" /></div><div class="field"><label for="resource-condition">状态描述</label><input id="resource-condition" name="condition" value="${esc(value('condition'))}" placeholder="Good" /></div><div class="field"><label for="resource-value">参考价值 / 小时（HKD）</label><input id="resource-value" type="number" min="0" step="0.01" name="hourly_value" value="${esc(value('hourly_value') || 0)}" /></div><div class="field"><label for="resource-start">可用开始</label><input id="resource-start" type="datetime-local" name="availability_start" required value="${localInput(value('availability_start') || base)}" /></div><div class="field"><label for="resource-end">可用结束</label><input id="resource-end" type="datetime-local" name="availability_end" required value="${localInput(value('availability_end') || end)}" /></div>${editing ? `<div class="field"><label for="resource-status">资源状态</label><select id="resource-status" name="status"><option value="available" ${value('status') === 'available' ? 'selected' : ''}>可申请</option><option value="offline" ${value('status') === 'offline' ? 'selected' : ''}>暂不可用</option><option value="maintenance" ${value('status') === 'maintenance' ? 'selected' : ''}>维护中</option></select></div>` : ''}</div><div class="form-actions"><button class="secondary-btn" data-close type="button">取消</button><button class="primary-btn" type="submit">${editing ? '保存修改' : '发布资源'}</button></div></form>`;
}
async function openResourceModal(resourceId) {
  let resource = null;
  if (resourceId) resource = arr(state.data.resources).find(item => String(item.id) === String(resourceId));
  if (resource && !ownResource(resource)) { toast('只能编辑本组织的资源', true); return; }
  $('#modal').innerHTML = resourceForm(resource);
  openModal();
  $('#resource-form').addEventListener('submit', submitResource);
}
async function submitResource(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  const payload = Object.fromEntries(form.entries());
  payload.capacity = Number(payload.capacity || 1);
  payload.hourly_value = Number(payload.hourly_value || 0);
  payload.availability_start = iso(payload.availability_start);
  payload.availability_end = iso(payload.availability_end);
  const id = event.target.dataset.resourceId;
  try { await api(id ? `/api/resources/${id}` : '/api/resources', { method: id ? 'PATCH' : 'POST', body: JSON.stringify(payload) }); closeModal(); await refresh(); toast(id ? '资源信息已更新' : '资源已发布'); setView(state.view === 'profile' ? 'profile' : 'resources'); } catch (error) { toast(error.message, true); }
}

function planCards(mission, preferences) {
  const plans = arr(mission.plans);
  if (!plans.length) return '<div class="empty">目前没有满足条件的完整方案，请调整需求或时间。</div>';
  return plans.map(plan => `<div class="plan-card ${preferences.includes(plan.id) ? 'selected' : ''}" data-plan-card="${esc(plan.id)}"><div class="plan-top"><input type="checkbox" value="${esc(plan.id)}" ${preferences.includes(plan.id) ? 'checked' : ''} aria-label="接受 ${esc(plan.label || plan.id)}" /><strong>${esc(plan.label || '方案')} · ${arr(plan.items).length} 项资源</strong><span class="plan-score">${num(plan.match_score) === null ? '—' : `${Math.round(plan.match_score * 100)}%`}</span></div><div class="plan-items">${arr(plan.items).map(item => `<span class="plan-item">${esc(item.resource || item.name || '')} · ${esc(item.owner || '')}</span>`).join('')}</div>${plan.tradeoff ? `<div class="plan-note">${esc(plan.tradeoff)}</div>` : ''}<div class="plan-order"><button type="button" data-plan-up="${esc(plan.id)}" aria-label="方案上移">↑</button><button type="button" data-plan-down="${esc(plan.id)}" aria-label="方案下移">↓</button><small>按卡片顺序保存优先级</small></div></div>`).join('');
}
async function openMissionDetail(id) {
  try {
    const response = await api(`/api/missions/${id}`);
    const mission = response.mission || response;
    state.mission = mission;
    const preferences = arr(mission.preferences);
    const waiting = ['open', 'waitlisted'].includes(mission.status);
    const score = num(mission.fairness?.score);
    $('#modal').innerHTML = `<div class="modal-head"><h2>${esc(mission.title)}</h2><button class="close-btn" data-close type="button" aria-label="关闭">×</button></div><div class="mission-detail"><div class="panel detail-panel" style="box-shadow:none"><div class="eyebrow">Mission 详情</div><p class="lead">${esc(mission.description)}</p><div class="req-list">${arr(mission.requirements).map(requirement => `<span class="req-chip">✓ ${esc(requirement.label || requirement.text || requirement.name || '')}</span>`).join('')}</div><div class="mission-detail-meta">${statusTag(mission.status)} <span>地点：${esc(mission.location || '—')}</span><span>使用：${fmtDate(mission.start_at)} – ${fmtDate(mission.end_at)}</span><span>申请截止：${fmtDate(mission.deadline)}</span></div>${waiting ? `<h3 class="detail-subtitle">可接受方案</h3><p class="modal-intro">选择方案并用箭头调整优先顺序，申请截止前可以修改。</p><div id="plans">${planCards(mission, preferences)}</div><div class="form-actions"><button class="secondary-btn" id="save-prefs" type="button">保存方案偏好</button></div>` : `<div class="approval-notice"><strong>${esc(missionStatus(mission.status))}</strong><span>平台会在状态变化时通知本组织。</span></div>`}</div><div><div class="panel detail-panel" style="box-shadow:none"><div class="eyebrow">当前状态</div><div class="score-box"><div class="score-label">Fairness Score</div><div class="score-big">${score === null ? '—' : `${Math.round(score * 100)} / 100`}</div></div>${['allocated', 'frozen'].includes(mission.status) ? '<p class="approved-copy">Mission / 资源 / 场地已获批，可在使用时间到达后开始使用。</p>' : ''}${mission.status === 'in_use' ? '<p class="approved-copy">正在使用中。完成归还后请确认完成。</p>' : ''}<div class="detail-actions">${mission.status === 'allocated' || mission.status === 'frozen' ? '<button class="secondary-btn" id="checkout" type="button">开始使用</button>' : ''}${mission.status === 'in_use' ? '<button class="primary-btn" id="complete" type="button">完成归还</button>' : ''}${['open', 'waitlisted', 'allocated', 'frozen'].includes(mission.status) ? '<button class="secondary-btn" id="withdraw" type="button">取消 Mission</button>' : ''}${['allocated', 'frozen', 'in_use', 'completed'].includes(mission.status) ? '<button class="text-link" id="dispute" type="button">发起争议</button>' : ''}</div></div></div></div>`;
    openModal();
    $$('#plans input[type="checkbox"]').forEach(input => input.addEventListener('change', () => input.closest('.plan-card').classList.toggle('selected', input.checked)));
    $$('[data-plan-up]').forEach(button => button.addEventListener('click', () => movePlan(button.dataset.planUp, -1)));
    $$('[data-plan-down]').forEach(button => button.addEventListener('click', () => movePlan(button.dataset.planDown, 1)));
    $('#save-prefs')?.addEventListener('click', () => savePreferences(id));
    $('#checkout')?.addEventListener('click', () => missionAction(id, 'checkout', '已开始使用'));
    $('#complete')?.addEventListener('click', () => missionAction(id, 'complete', '已确认归还，Mission 已完成'));
    $('#withdraw')?.addEventListener('click', () => missionAction(id, 'withdraw', 'Mission 已取消'));
    $('#dispute')?.addEventListener('click', () => openDisputeModal(id));
  } catch (error) { toast(error.message, true); }
}
function movePlan(id, direction) {
  const card = $(`[data-plan-card="${CSS.escape(String(id))}"]`);
  if (!card) return;
  const sibling = direction < 0 ? card.previousElementSibling : card.nextElementSibling;
  if (sibling) direction < 0 ? sibling.before(card) : sibling.after(card);
}
async function savePreferences(id) {
  const preferences = $$('#plans input[type="checkbox"]:checked').map(input => input.value);
  try { await api(`/api/missions/${id}/preferences`, { method: 'POST', body: JSON.stringify({ preferences }) }); toast('方案偏好已保存'); await refresh(); openMissionDetail(id); } catch (error) { toast(error.message, true); }
}
async function missionAction(id, action, message) {
  try { await api(`/api/missions/${id}/${action}`, { method: 'POST', body: '{}' }); closeModal(); await refresh(); toast(message); } catch (error) { toast(error.message, true); }
}
function openDisputeModal(id) {
  $('#modal').innerHTML = `<div class="modal-head"><h2>发起资源争议</h2><button class="close-btn" data-close type="button" aria-label="关闭">×</button></div><p class="modal-intro">描述设备或场地在使用前后的实际情况，平台会记录时间和 Mission。</p><form id="dispute-form"><div class="field"><label for="dispute-category">争议类型</label><select id="dispute-category" name="category"><option value="condition">设备状态不一致</option><option value="no-show">未交付 / No-show</option><option value="damage">损坏或遗失</option><option value="other">其他</option></select></div><div class="field"><label for="dispute-description">描述</label><textarea id="dispute-description" name="description" required placeholder="请描述发生了什么"></textarea></div><div class="form-actions"><button class="secondary-btn" data-close type="button">取消</button><button class="primary-btn" type="submit">提交争议</button></div></form>`;
  openModal();
  $('#dispute-form').addEventListener('submit', async event => { event.preventDefault(); try { const payload = Object.fromEntries(new FormData(event.target).entries()); await api(`/api/missions/${id}/disputes`, { method: 'POST', body: JSON.stringify(payload) }); closeModal(); await refresh(); toast('争议已提交'); } catch (error) { toast(error.message, true); } });
}

function openProfileModal() { setView('profile'); }
function searchResults(query) {
  const text = query.trim().toLowerCase();
  if (!text) return '<div class="empty" style="padding:22px 0">输入资源或 Mission 名称</div>';
  const missions = arr(state.data.missions).filter(item => `${item.title} ${item.description}`.toLowerCase().includes(text));
  const resources = arr(state.data.resources).filter(item => `${item.name} ${item.capability} ${item.features} ${item.location}`.toLowerCase().includes(text));
  const result = [...missions.map(item => `<button class="search-result" data-search-mission="${esc(item.id)}" type="button"><span class="tag purple">Mission</span><div><strong>${esc(item.title)}</strong><small>${esc(missionStatus(item.status))}</small></div><span>›</span></button>`), ...resources.map(item => `<button class="search-result" data-search-resource="${esc(item.id)}" type="button"><span class="tag blue">资源</span><div><strong>${esc(item.name)}</strong><small>${esc(item.owner_name || '')} · ${esc(item.location || '')}</small></div><span>›</span></button>` )];
  return result.slice(0, 10).join('') || '<div class="empty" style="padding:22px 0">没有匹配结果</div>';
}
function openGlobalSearch() {
  $('#modal').innerHTML = `<div class="modal-head"><h2>搜索</h2><button class="close-btn" data-close type="button" aria-label="关闭">×</button></div><div class="field"><label for="global-search-input">搜索资源或我的 Mission</label><input id="global-search-input" autofocus placeholder="例如：camera、studio、demo" /></div><div id="search-results" style="margin-top:14px"></div>`;
  openModal();
  const input = $('#global-search-input');
  const update = () => { $('#search-results').innerHTML = searchResults(input.value); $$('[data-search-mission]').forEach(button => button.addEventListener('click', () => { closeModal(); openMissionDetail(button.dataset.searchMission); })); $$('[data-search-resource]').forEach(button => button.addEventListener('click', () => { closeModal(); openResourceInfo(button.dataset.searchResource); })); };
  input.addEventListener('input', update); update(); input.focus();
}
function openResourceInfo(id) {
  const resource = arr(state.data.resources).find(item => String(item.id) === String(id));
  if (!resource) return toast('资源已不可用', true);
  const canEdit = ownResource(resource);
  $('#modal').innerHTML = `<div class="modal-head"><h2>${esc(resource.name)}</h2><button class="close-btn" data-close type="button" aria-label="关闭">×</button></div><div class="resource-info"><p>${esc(resource.features || resource.capability || '暂无描述')}</p><dl><dt>提供组织</dt><dd>${esc(resource.owner_name || '')}</dd><dt>位置</dt><dd>${esc(resource.location || '—')}</dd><dt>可用时间</dt><dd>${fmtDate(resource.availability_start)} – ${fmtDate(resource.availability_end)}</dd><dt>状态</dt><dd>${esc(resourceStatus(resource.status))}</dd></dl></div><div class="form-actions">${canEdit ? `<button class="primary-btn" id="resource-info-edit" type="button">编辑我的资源</button>` : ''}<button class="secondary-btn" data-close type="button">关闭</button></div>`;
  openModal();
  $('#resource-info-edit')?.addEventListener('click', () => openResourceModal(id));
}
function openActivityModal() {
  const events = arr(state.data.events);
  $('#modal').innerHTML = `<div class="modal-head"><h2>最近活动</h2><button class="close-btn" data-close type="button" aria-label="关闭">×</button></div><p class="modal-intro">这里只显示与 ${esc(org().short_name || '本组织')} 相关的通知。</p><div class="activity-list" style="padding:0">${events.length ? events.map(eventRow).join('') : '<div class="empty">暂无通知</div>'}</div>`;
  openModal();
}
function openOrgMenu() {
  const current = document.querySelector('.org-menu');
  if (current) { current.remove(); return; }
  const organizations = arr(state.data.organizations);
  const menu = document.createElement('div');
  menu.className = 'org-menu';
  menu.setAttribute('role', 'menu');
  menu.innerHTML = `${organizations.map(item => `<button type="button" data-org="${esc(item.id)}"><span class="avatar">${esc((item.short_name || item.name || '—')[0])}</span><div><strong>${esc(item.short_name || item.name)}</strong><small>本地演示组织会话</small></div></button>`).join('') || '<div class="empty">暂无可切换组织</div>'}`;
  document.body.appendChild(menu);
  $$('[data-org]', menu).forEach(button => button.addEventListener('click', async () => { try { await api('/api/switch-user', { method: 'POST', body: JSON.stringify({ organization_id: Number(button.dataset.org) }) }); menu.remove(); await refresh(); toast(`已切换到 ${state.data.organization.short_name || state.data.organization.name}`); } catch (error) { toast(error.message, true); } }));
}
function openModal() { const backdrop = $('#modal-backdrop'); backdrop.classList.add('open'); backdrop.setAttribute('aria-hidden', 'false'); $$('[data-close]').forEach(button => button.addEventListener('click', closeModal)); }
function closeModal() { const backdrop = $('#modal-backdrop'); backdrop.classList.remove('open'); backdrop.setAttribute('aria-hidden', 'true'); }
let adminHost = null;
async function openAdminConsole() {
  if (adminHost) return;
  try {
    const response = await fetch('/static/admin.html', { credentials: 'same-origin' });
    if (!response.ok) throw new Error('管理端界面加载失败');
    const html = await response.text();
    const parsed = new DOMParser().parseFromString(html, 'text/html');
    const shell = parsed.querySelector('.admin-shell');
    if (!shell) throw new Error('管理端界面无效');
    adminHost = document.createElement('div');
    adminHost.className = 'admin-modal-host';
    adminHost.setAttribute('role', 'dialog');
    adminHost.setAttribute('aria-label', '管理端');
    adminHost.innerHTML = shell.outerHTML;
    document.body.appendChild(adminHost);
    if (!document.querySelector('link[data-admin-css]')) {
      const style = document.createElement('link'); style.rel = 'stylesheet'; style.href = '/static/admin.css'; style.dataset.adminCss = '1'; document.head.appendChild(style);
    }
    window.closeAdminConsole = () => { adminHost?.remove(); adminHost = null; delete window.closeAdminConsole; };
    const script = document.createElement('script'); script.src = '/static/admin.js?overlay=20261003'; adminHost.appendChild(script);
  } catch (error) { toast(error.message, true); }
}
async function refresh() {
  state.data = await api('/api/bootstrap');
  $('#org-name').textContent = state.data.organization?.short_name || state.data.organization?.name || '当前组织';
  $('#org-avatar').textContent = (state.data.organization?.short_name || state.data.organization?.name || '—')[0];
  renderView();
}
function boot() {
  navSetup();
  document.addEventListener('click', event => { if (event.target.closest('#new-mission')) { event.preventDefault(); openMissionModal(); } });
  let brandClicks = 0; let brandTimer;
  $('.brand-mark')?.addEventListener('click', () => { brandClicks += 1; window.clearTimeout(brandTimer); brandTimer = window.setTimeout(() => { brandClicks = 0; }, 1500); if (brandClicks >= 5) { brandClicks = 0; openAdminConsole(); } });
  $('#switch-org').addEventListener('click', openOrgMenu);
  $('#workspace-profile').addEventListener('click', openProfileModal);
  $('#global-search').addEventListener('click', openGlobalSearch);
  $('#activity-toggle').addEventListener('click', openActivityModal);
  window.addEventListener('keydown', event => { if (event.altKey && event.shiftKey && event.key.toLowerCase() === 'a') { event.preventDefault(); openAdminConsole(); } });
  $('#open-resource').addEventListener('click', () => openResourceModal());
  $('#modal-backdrop').addEventListener('click', event => { if (event.target.id === 'modal-backdrop') closeModal(); });
  refresh().catch(error => toast(error.message, true));
}
boot();
