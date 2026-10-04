/* Campus Commons user client. */
const state = { data: null, view: 'overview', mission: null };
let userSyncTimer = null;
let userSyncBusy = false;
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
  return `${date.toLocaleDateString('en-HK', { month: 'short', day: 'numeric' })} ${date.toLocaleTimeString('en-HK', { hour: '2-digit', minute: '2-digit' })}`;
};
const fmtRelative = value => {
  if (!value) return 'Time not set';
  const delta = new Date(value).getTime() - Date.now();
  if (!Number.isFinite(delta)) return 'Time not set';
  if (delta < 0) return 'Due now';
  const hours = Math.round(delta / 36e5);
  return hours < 24 ? `${hours} hours` : `${Math.round(hours / 24)} days`;
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
  if (!response.ok) throw new Error(body.error || body.message || 'Request failed. Please try again.');
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
  const labels = { open: 'Open', waitlisted: 'Waitlisted', allocated: 'Approved', frozen: 'Approved', in_use: 'In use', completed: 'Completed', withdrawn: 'Cancelled', replacement_pending: 'Replacement pending' };
  return labels[status] || status || '—';
}
function statusTag(status) { return `<span class="mission-status status-${esc(status || 'unknown')}">${esc(missionStatus(status))}</span>`; }
function disputeStatus(status) { return ({ open: 'Pending admin review', awaiting_victim: 'Approved · waiting for requester confirmation', resolved: 'Resolved', rejected: 'Rejected' }[status] || status || 'Processing'); }
function resourceStatus(status) {
  const labels = { available: 'Available', offline: 'Unavailable', maintenance: 'Under maintenance', reserved: 'Reserved', loaned: 'On loan' };
  return labels[status] || status || '—';
}
function resourceStatusClass(status) { return status === 'available' ? 'green' : status === 'maintenance' ? 'orange' : 'purple'; }
function effectiveResourceStatus(resource) { return resource.loaned ? 'loaned' : (resource.status || 'unknown'); }
function typeLabel(type) { return ({ equipment: 'Equipment', skill: 'Skill', space: 'Space', people: 'People' }[type] || type || 'Resource'); }
function statusCounts(missions) { return missions.reduce((result, item) => { result[item.status] = (result[item.status] || 0) + 1; return result; }, {}); }

function navSetup() {
  $$('.nav-item, .mini-link').forEach(button => button.addEventListener('click', () => setView(button.dataset.view)));
}
function setView(view) {
  if (!['overview', 'missions', 'resources', 'profile', 'impact'].includes(view)) view = 'overview';
  state.view = view;
  $$('.view').forEach(section => section.classList.toggle('active', section.id === `view-${view}`));
  $$('.nav-item').forEach(button => button.classList.toggle('active', button.dataset.view === view));
  const labels = { overview: 'Overview', missions: 'Mission', resources: 'Resources', profile: 'Organization profile', impact: 'Impact and value' };
  $('#page-label').textContent = labels[view];
  renderView();
}
function renderView() {
  if (!state.data) return;
  ({ overview: renderOverview, missions: renderMissions, resources: renderResources, profile: renderProfile, impact: renderImpact }[state.view] || renderOverview)();
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
    <div class="view-heading"><div><div class="eyebrow">Organization workspace · ${esc(org().short_name || org().name)}</div><h1>Put unused resources to work.</h1><p>This is where you can see ${esc(org().short_name || 'this organization')}'s Missions, resources, and notifications.</p></div><button class="primary-btn" id="new-mission" type="button">+ Submit a Mission</button></div>
    <div class="stat-grid">
      <div class="stat-card"><div class="stat-top"><span>My resources</span><span class="stat-icon green" aria-hidden="true">▦</span></div><div class="stat-value">${mine.length}</div><div class="stat-foot">of which ${mine.filter(r => r.status === 'available').length} available</div></div>
      <div class="stat-card"><div class="stat-top"><span>My Missions</span><span class="stat-icon blue" aria-hidden="true">◎</span></div><div class="stat-value">${missions.length}</div><div class="stat-foot">${counts.allocated || 0} approved</div></div>
      <div class="stat-card"><div class="stat-top"><span>Credit score</span><span class="stat-icon purple" aria-hidden="true">◇</span></div><div class="stat-value">${credit === null ? '—' : Math.round(credit)}</div><div class="stat-foot">Platform-recorded organization credit</div></div>
      <div class="stat-card"><div class="stat-top"><span>Shared hours</span><span class="stat-icon orange" aria-hidden="true">◷</span></div><div class="stat-value">${sharedHours === null ? '—' : sharedHours}<small style="font-size:14px;color:#788983">${sharedHours === null ? '' : 'h'}</small></div><div class="stat-foot">Verified availability ${availableHours === null ? '—' : `${availableHours}h`}</div></div>
    </div>
    <div class="grid-2">
      <div class="panel"><div class="panel-head"><div><h2>My Missions</h2><small>Only Missions submitted by this organization</small></div><button class="text-link" id="go-missions" type="button">View all →</button></div><div class="mission-list">${missions.length ? missions.slice(0, 5).map(missionRow).join('') : '<div class="empty">No Missions yet</div>'}</div></div>
      <div class="panel"><div class="panel-head"><div><h2>Recent activity</h2><small>Notifications for this organization</small></div><button class="text-link" id="go-activity" type="button">View all →</button></div><div class="activity-list">${events.length ? events.map(eventRow).join('') : '<div class="empty">No notifications yet</div>'}</div></div>
    </div>
    <div class="panel contribution-panel"><div class="panel-head"><div><h2>Organization contribution</h2><small>Resource sharing and completed Missions</small></div><button class="secondary-btn" id="go-profile" type="button">View organization profile</button></div><div class="contribution-grid"><div><span>Credit score</span><strong>${credit === null ? '—' : `${Math.round(credit)} / 100`}</strong></div><div><span>Hours shared</span><strong>${sharedHours === null ? '—' : `${sharedHours}h`}</strong></div><div><span>Verified available hours</span><strong>${availableHours === null ? '—' : `${availableHours}h`}</strong></div><div><span>Missions completed</span><strong>${dash(org().allocations_won)}</strong></div></div></div>`;
  $('#new-mission').onclick = openMissionModal;
  $('#go-missions').addEventListener('click', () => setView('missions'));
  $('#go-profile').addEventListener('click', () => setView('profile'));
  $('#go-activity').addEventListener('click', openActivityModal);
  $$('.mission-row[data-id]', $('#view-overview')).forEach(row => row.addEventListener('click', () => openMissionDetail(row.dataset.id)));
}
function missionRow(mission) {
  const score = num(mission.fairness?.score);
  const role = mission.viewer_role === 'provider' ? ' · Lending activity' : '';
  return `<button class="mission-row" data-id="${esc(mission.id)}" type="button"><div class="mission-badge">${['allocated', 'frozen', 'in_use', 'completed'].includes(mission.status) ? '✓' : 'M'}</div><div><div class="mission-title">${esc(mission.title)}</div><div class="mission-meta">${fmtDate(mission.created_at)} · cutoff ${fmtDate(mission.deadline)}${role}</div></div>${statusTag(mission.status)}${score === null ? '' : `<span class="score">${Math.round(score * 100)}</span>`}<span class="chevron" aria-hidden="true">›</span></button>`;
}
function eventRow(event) { return `<div class="activity"><div class="activity-line" aria-hidden="true"></div><div><strong>${esc(event.title || 'Platform notification')}</strong><small>${esc(event.detail || '')}</small><time>${fmtDate(event.created_at)}</time></div></div>`; }

function renderMissions() {
  const missions = arr(state.data.missions);
  const filters = [['all', 'All'], ['open', 'Open'], ['waitlisted', 'Waitlisted'], ['allocated', 'Approved'], ['in_use', 'In use'], ['completed', 'Completed'], ['withdrawn', 'Cancelled']];
  $('#view-missions').innerHTML = `<div class="view-heading"><div><div class="eyebrow">Mission</div><h1>Submit and manage your needs.</h1><p>Choose acceptable options before the deadline. After approval, you can check out and return the resource.</p></div><button class="primary-btn" id="new-mission" type="button">+ Submit a Mission</button></div><div class="filter-row">${filters.map(([key, label]) => `<button class="filter-btn ${key === 'all' ? 'active' : ''}" data-filter="${key}" type="button">${label} ${key === 'all' ? missions.length : missions.filter(m => m.status === key).length}</button>`).join('')}</div><div id="mission-cards">${missions.length ? missions.map(missionCard).join('') : '<div class="panel"><div class="empty">No Missions yet. Submit a request to start matching resources.</div></div>'}</div>`;
  $('#new-mission').onclick = openMissionModal;
  $$('.filter-btn').forEach(button => button.addEventListener('click', () => { $$('.filter-btn').forEach(item => item.classList.remove('active')); button.classList.add('active'); const key = button.dataset.filter; $('#mission-cards').innerHTML = missions.filter(m => key === 'all' || m.status === key).map(missionCard).join('') || '<div class="panel"><div class="empty">No Missions match this filter</div></div>'; bindMissionCards(); }));
  bindMissionCards();
}
function missionCard(mission) {
  const score = num(mission.fairness?.score);
  const roleLabel = mission.viewer_role === 'provider' ? ' · You are lending resources' : '';
  return `<article class="mission-card"><div class="mission-card-head"><div class="mission-badge">${['allocated', 'frozen', 'in_use', 'completed'].includes(mission.status) ? '✓' : 'M'}</div><div><h3>${esc(mission.title)}</h3><p>${esc(mission.description)}</p><div class="mission-card-meta"><span>Submitted ${fmtDate(mission.created_at)}</span><span>Cutoff ${fmtDate(mission.deadline)}</span><span>Use ${fmtDate(mission.start_at)} – ${fmtDate(mission.end_at)}</span><span>⌖ ${esc(mission.location)}</span>${roleLabel}</div></div>${statusTag(mission.status)}</div><div class="mission-card-actions"><span class="tag ${arr(mission.plans).length ? 'green' : ''}">${arr(mission.plans).length} valid options${score === null ? '' : ` · fairness score ${Math.round(score * 100)}`}</span><button class="secondary-btn" data-open-mission="${esc(mission.id)}" type="button">View details →</button></div></article>`;
}
function bindMissionCards() { $$('[data-open-mission]').forEach(button => button.addEventListener('click', () => openMissionDetail(button.dataset.openMission))); }

function resourceSort(resources, mode) {
  const statusOrder = { available: 0, offline: 1, maintenance: 2, reserved: 3 };
  return [...resources].sort((a, b) => {
    if (mode === 'time') return (new Date(a.availability_start || 0) - new Date(b.availability_start || 0)) || String(a.name).localeCompare(String(b.name));
    if (mode === 'location') return String(a.location || '').localeCompare(String(b.location || ''), 'en', { sensitivity: 'base' }) || String(a.name).localeCompare(String(b.name));
    if (mode === 'price') return (num(a.hourly_value) ?? Infinity) - (num(b.hourly_value) ?? Infinity) || String(a.name).localeCompare(String(b.name));
    return (statusOrder[a.status] ?? 9) - (statusOrder[b.status] ?? 9) || String(a.name).localeCompare(String(b.name));
  });
}
function resourceRows(resources) {
  return resources.map(resource => { const effective = effectiveResourceStatus(resource); const loan = arr(resource.active_loans)[0]; return `<tr><td><strong>${esc(resource.name)}</strong><small>${esc(resource.features || resource.capability || '')}</small>${loan ? `<small>Loaned for “${esc(loan.title)}” · ${fmtDate(loan.start_at)} – ${fmtDate(loan.end_at)}</small>` : ''}</td><td><span class="tag blue">${esc(typeLabel(resource.type))}</span></td><td>${esc(resource.owner_name || resource.owner_short_name || '')}</td><td>${fmtDate(resource.availability_start)}<br><span class="subtle">to ${fmtDate(resource.availability_end)}</span></td><td>${esc(resource.location || '—')}</td><td><span class="tag ${resourceStatusClass(effective)}">${esc(resourceStatus(effective))}</span></td><td>${num(resource.hourly_value) === null ? '—' : `$${num(resource.hourly_value)}`} ${ownResource(resource) ? `<button class="edit-resource-link" data-edit-resource="${esc(resource.id)}" type="button">Edit</button>` : ''}</td></tr>`; }).join('');
}
function renderResources() {
  const resources = arr(state.data.resources);
  const own = resources.filter(ownResource);
  $('#view-resources').innerHTML = `<div class="view-heading"><div><div class="eyebrow">Shared resource pool</div><h1>Find resources you can use.</h1><p>Sort by status, availability, location, or price. You can edit resources you publish from your organization profile.</p></div><button class="primary-btn" id="new-resource" type="button">+ Publish resource</button></div><div class="stat-grid"><div class="stat-card"><div class="stat-top"><span>Available resources</span><span class="stat-icon green" aria-hidden="true">▦</span></div><div class="stat-value">${resources.filter(r => r.status === 'available' && !r.loaned).length}</div><div class="stat-foot">Across the shared network</div></div><div class="stat-card"><div class="stat-top"><span>My resources</span><span class="stat-icon blue" aria-hidden="true">◌</span></div><div class="stat-value">${own.length}</div><div class="stat-foot">Manage from your profile</div></div><div class="stat-card"><div class="stat-top"><span>My available resources</span><span class="stat-icon purple" aria-hidden="true">✓</span></div><div class="stat-value">${own.filter(r => r.status === 'available' && !r.loaned).length}</div><div class="stat-foot">Maintained by the owning organization</div></div></div><div class="panel table-panel"><div class="panel-head"><div><h2>Resource directory</h2><small>Browse shared resources; edit controls appear only for your own resources</small></div><label class="sort-label" for="resource-sort">Sort<select id="resource-sort" class="resource-sort"><option value="status">Sort by status</option><option value="time">Availability: earliest first</option><option value="location">Location: A to Z</option><option value="price">Price: low to high</option></select></label></div><div class="table-scroll"><table class="data-table"><thead><tr><th>Resource</th><th>Type</th><th>Provider</th><th>Available time</th><th>Location</th><th>Status</th><th>Value / hour</th></tr></thead><tbody id="resource-table-body">${resourceRows(resourceSort(resources, 'status')) || '<tr><td colspan="7"><div class="empty">No resources</div></td></tr>'}</tbody></table></div></div>`;
  $('#new-resource').addEventListener('click', () => openResourceModal());
  $('#resource-sort').addEventListener('change', event => { $('#resource-table-body').innerHTML = resourceRows(resourceSort(resources, event.target.value)) || '<tr><td colspan="7"><div class="empty">No resources</div></td></tr>'; bindResourceLinks(); });
  bindResourceLinks();
}
function bindResourceLinks() { $$('[data-edit-resource]').forEach(button => button.addEventListener('click', () => openResourceModal(button.dataset.editResource))); }

function historyEntityLabel(type) { return ({ resource: 'Resource', mission: 'Mission', dispute: 'Dispute', organization: 'Organization', platform: 'Platform' }[type] || type || 'Record'); }
function historyActionLabel(action, snapshot) {
  if (action === 'created') return 'Created';
  if (action === 'updated') return 'Updated';
  if (action === 'preferences_updated') return 'Updated option preferences';
  if (action === 'replacement_pending') return 'Waiting for replacement';
  if (action === 'config_updated') return 'Updated platform settings';
  if (action.startsWith('status_')) return `Status: ${missionStatus(action.slice(7))}`;
  if (action === 'resolved') return 'Processed';
  return action || 'Change';
}
function historyLabel(item) {
  const snapshot = item.snapshot || {};
  return snapshot.title || snapshot.name || `${historyEntityLabel(item.entity_type)} #${item.entity_id}`;
}
function historyRows(history) {
  return arr(history).slice(0, 50).map(item => `<tr><td><strong>${esc(historyLabel(item))}</strong><small>${esc(historyEntityLabel(item.entity_type))}</small></td><td>${esc(historyActionLabel(item.action, item.snapshot))}</td><td>${fmtDate(item.created_at)}</td></tr>`).join('');
}

function money(value) { return value === null || value === undefined ? '—' : `${Number(value).toLocaleString('en-HK', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`; }
function renderImpact() {
  const metrics = state.data?.metrics || {};
  const impact = metrics.platform_impact || metrics.impact || {};
  const own = metrics.impact || {};
  const utilization = Math.round(Number(impact.utilization || 0) * 100);
  $('#view-impact').innerHTML = `<div class="view-heading"><div><div class="eyebrow">Platform value</div><h1>Shared resources create measurable value.</h1><p>Every approved booking turns idle capacity into time and money saved for the campus network.</p></div></div><div class="impact-hero"><div><span class="impact-label">Estimated external cost avoided</span><strong>HKD ${money(impact.cost_avoided)}</strong><small>Compared with renting or sourcing equivalent resources externally.</small></div><div><span class="impact-label">Coordination time saved</span><strong>${Number(impact.coordination_hours_saved || 0).toFixed(1)} h</strong><small>Estimated search, comparison, messaging and handoff time replaced by the platform.</small></div></div><div class="stat-grid impact-stats"><div class="stat-card"><div class="stat-top"><span>Shared hours delivered</span><span class="stat-icon green">◷</span></div><div class="stat-value">${Number(impact.shared_hours || 0).toFixed(1)}<small>h</small></div><div class="stat-foot">Across active and completed bookings</div></div><div class="stat-card"><div class="stat-top"><span>Missions supported</span><span class="stat-icon blue">◎</span></div><div class="stat-value">${impact.missions_supported || 0}</div><div class="stat-foot">With ${impact.bookings || 0} resource booking(s)</div></div><div class="stat-card"><div class="stat-top"><span>Pool utilization</span><span class="stat-icon purple">↗</span></div><div class="stat-value">${utilization}%</div><div class="stat-foot">Shared hours ÷ published availability</div></div><div class="stat-card"><div class="stat-top"><span>Your contribution</span><span class="stat-icon orange">C</span></div><div class="stat-value">${Number(own.shared_hours || 0).toFixed(1)}<small>h</small></div><div class="stat-foot">${money(own.cost_avoided)} HKD value from your organization</div></div></div><div class="grid-2 impact-grid"><div class="panel impact-panel"><div class="panel-head"><div><h2>How the estimate is calculated</h2><small>Transparent assumptions for judges and users</small></div></div><div class="impact-method"><div><strong>Cost avoided</strong><span>Booking hours × external replacement/rental reference price</span></div><div><strong>Time saved</strong><span>1.5 coordination hours per booking + 0.5 hour per Mission</span></div><div><strong>Utilization</strong><span>Shared booking hours ÷ published resource availability hours</span></div></div></div><div class="panel impact-panel"><div class="panel-head"><div><h2>Why this matters</h2><small>Value created by the shared network</small></div></div><ul class="impact-list"><li>Organizations avoid duplicate purchases and external rental searches.</li><li>Idle equipment, spaces and skills become productive capacity.</li><li>Fair allocation gives access to scarce resources while keeping the result explainable.</li><li>Providers receive contribution history, credit and verified sharing records.</li></ul></div></div><div class="impact-note">${esc(impact.calculation_note || 'Figures update after each allocation batch and booking status change.')}</div>`;
}

function renderProfile() {
  const mine = arr(state.data.resources).filter(ownResource);
  const credit = num(org().credit_score);
  const history = arr(state.data.history);
  $('#view-profile').innerHTML = `<div class="view-heading"><div><div class="eyebrow">Organization profile</div><h1>${esc(org().name || org().short_name || 'My organization')}</h1><p>${esc(org().kind || 'Shared network member')} · Manage resources published by this organization.</p></div><button class="primary-btn" id="profile-new-resource" type="button">+ Publish resource</button></div><div class="profile-grid profile-page-stats"><div class="profile-stat"><strong>${credit === null ? '—' : Math.round(credit)}</strong><small>Credit score / 100</small></div><div class="profile-stat"><strong>${dash(org().shared_hours)}${org().shared_hours === undefined ? '' : 'h'}</strong><small>Hours shared</small></div><div class="profile-stat"><strong>${dash(org().available_hours)}${org().available_hours === undefined ? '' : 'h'}</strong><small>Verified available hours</small></div><div class="profile-stat"><strong>${dash(org().allocations_won)}</strong><small>Missions completed</small></div></div><div class="panel table-panel profile-resources"><div class="panel-head"><div><h2>My resources</h2><small>Edit the name, capabilities, schedule, and status</small></div><span class="tag blue">${mine.length} items</span></div><div class="table-scroll"><table class="data-table"><thead><tr><th>Resource</th><th>Type</th><th>Capabilities / details</th><th>Time</th><th>Status</th><th>Actions</th></tr></thead><tbody>${mine.length ? mine.map(profileResourceRow).join('') : '<tr><td colspan="6"><div class="empty">No published resources yet</div></td></tr>'}</tbody></table></div></div><div class="panel table-panel history-panel"><div class="panel-head"><div><h2>History</h2><small>Resources and Missions created or updated by this organization are kept in the database</small></div><span class="tag blue">${history.length} records</span></div><div class="table-scroll"><table class="data-table"><thead><tr><th>Item</th><th>Change</th><th>Time</th></tr></thead><tbody>${historyRows(history) || '<tr><td colspan="3"><div class="empty">No history yet</div></td></tr>'}</tbody></table></div></div>`;
  $('#profile-new-resource').addEventListener('click', () => openResourceModal());
  $$('[data-edit-resource]', $('#view-profile')).forEach(button => button.addEventListener('click', () => openResourceModal(button.dataset.editResource)));
}
function profileResourceRow(resource) { const effective = effectiveResourceStatus(resource); const loan = arr(resource.active_loans)[0]; return `<tr><td><strong>${esc(resource.name)}</strong><small>${esc(resource.location || '—')}</small>${loan ? `<small>Loaned for “${esc(loan.title)}” · ${fmtDate(loan.start_at)} – ${fmtDate(loan.end_at)}</small>` : ''}</td><td>${esc(typeLabel(resource.type))}</td><td>${esc(resource.capability || '—')}<small>${esc(resource.features || '')}</small></td><td>${fmtDate(resource.availability_start)}<br><span class="subtle">to ${fmtDate(resource.availability_end)}</span></td><td><span class="tag ${resourceStatusClass(effective)}">${esc(resourceStatus(effective))}</span></td><td><button class="secondary-btn compact" data-edit-resource="${esc(resource.id)}" type="button">Edit</button></td></tr>`; }

function openMissionModal() {
  $('#modal').innerHTML = `<div class="modal-head"><h2>Submit a Mission</h2><button class="close-btn" data-close type="button" aria-label="Close">×</button></div><p class="modal-intro">Briefly describe what you need. The platform will suggest options and set the deadline automatically.</p><form id="mission-form"><div class="field"><label for="mission-title">Title</label><input id="mission-title" name="title" required placeholder="For example: Student product shoot" /></div><div class="field"><label for="mission-description">What do you need?</label><textarea id="mission-description" name="description" required placeholder="For example: a camera, lights, and a small studio"></textarea></div><div class="field full"><label>Resource types needed</label><small class="field-help">Select every type the Mission requires so matching can reject unrelated resources.</small><div class="check-row"><label><input type="checkbox" name="resource_types" value="equipment"> Equipment</label><label><input type="checkbox" name="resource_types" value="space"> Space</label><label><input type="checkbox" name="resource_types" value="skill"> Skill</label><label><input type="checkbox" name="resource_types" value="people"> People</label></div></div><div class="form-grid"><div class="field"><label for="mission-location">Location</label><input id="mission-location" name="location" required placeholder="Main Building" /></div><div class="field"><label for="mission-start">Start time</label><input id="mission-start" type="datetime-local" name="start_at" required /></div><div class="field"><label for="mission-end">End time</label><input id="mission-end" type="datetime-local" name="end_at" required /></div></div><div class="form-actions"><button class="secondary-btn" data-close type="button">Cancel</button><button class="primary-btn" type="submit">Submit request →</button></div></form>`;
  openModal();
  $('#mission-form').addEventListener('submit', submitMission);
}
async function submitMission(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  const payload = { title: form.get('title'), description: form.get('description'), location: form.get('location'), start_at: iso(form.get('start_at')), end_at: iso(form.get('end_at')), resource_types: form.getAll('resource_types') };
  try { const result = await api('/api/missions', { method: 'POST', body: JSON.stringify(payload) }); closeModal(); await refresh(); setView('missions'); toast('Mission submitted. Waiting for the application deadline.'); if (result.mission?.id) openMissionDetail(result.mission.id); } catch (error) { toast(error.message, true); }
}

function resourceForm(resource) {
  const editing = Boolean(resource);
  const base = new Date(Date.now() + 24 * 36e5);
  const end = new Date(Date.now() + 72 * 36e5);
  const value = key => resource?.[key] ?? '';
  const savedSource = value('cost_source');
  const sourceOptions = [['Public listing','Public listing'],['Campus rate','Campus rate'],['Published campus rate','Published campus rate'],['External market quote','External market quote'],['Previous transaction','Previous transaction'],['Organization estimate','Organization estimate'],['Other','Other']];
  const sourceValue = sourceOptions.some(([, option]) => option === savedSource) ? savedSource : (savedSource ? 'Other' : 'Organization estimate');
  return `<div class="modal-head"><h2>${editing ? 'Edit my resource' : 'Publish resource'}</h2><button class="close-btn" data-close type="button" aria-label="Close">×</button></div><p class="modal-intro">${editing ? 'Update the content or status of a resource published by this organization. Resources with bookings may need admin review.' : 'Share temporary access to this resource while ownership stays with your organization.'}</p><form id="resource-form" data-resource-id="${editing ? esc(resource.id) : ''}"><div class="form-grid"><div class="field full"><label for="resource-name">Resource name</label><input id="resource-name" name="name" required value="${esc(value('name'))}" placeholder="For example: Portable lighting set" /></div><div class="field"><label for="resource-type">Type</label><select id="resource-type" name="type"><option value="equipment" ${value('type') === 'equipment' ? 'selected' : ''}>Equipment</option><option value="skill" ${value('type') === 'skill' ? 'selected' : ''}>Skill</option><option value="space" ${value('type') === 'space' ? 'selected' : ''}>Space</option><option value="people" ${value('type') === 'people' ? 'selected' : ''}>People</option></select></div><div class="field"><label for="resource-capability">Capability keywords</label><input id="resource-capability" name="capability" required value="${esc(value('capability'))}" placeholder="camera, 4K video" /></div><div class="field full"><label for="resource-features">Details</label><input id="resource-features" name="features" value="${esc(value('features'))}" placeholder="Specifications, languages, seats, or usage conditions" /></div><div class="field"><label for="resource-location">Location</label><input id="resource-location" name="location" required value="${esc(value('location'))}" placeholder="Main Building" /></div><div class="field"><label for="resource-capacity">Capacity</label><input id="resource-capacity" type="number" min="1" step="1" name="capacity" value="${esc(value('capacity') || 1)}" /></div><div class="field"><label for="resource-condition">Condition</label><input id="resource-condition" name="condition" value="${esc(value('condition'))}" placeholder="Good" /></div><div class="field"><label for="resource-value">Reference value / hour (HKD)</label><input id="resource-value" type="number" min="0" step="0.01" name="hourly_value" value="${esc(value('hourly_value') || 0)}" /></div><div class="field full"><label for="resource-external-cost">External replacement cost (HKD / hour)</label><small class="field-help">The estimated hourly amount to rent or buy an equivalent resource elsewhere if the platform cannot match one.</small><input id="resource-external-cost" type="number" min="0" step="0.01" name="external_hourly_cost" value="${esc(value('external_hourly_cost') || value('hourly_value') || 0)}" /></div><div class="field"><label for="resource-cost-source">Cost reference</label><select id="resource-cost-source" name="cost_source"><option value="Public listing" ${sourceValue === 'Public listing' ? 'selected' : ''}>Public listing</option><option value="Campus rate" ${sourceValue === 'Campus rate' ? 'selected' : ''}>Campus rate</option><option value="Published campus rate" ${sourceValue === 'Published campus rate' ? 'selected' : ''}>Published campus rate</option><option value="External market quote" ${sourceValue === 'External market quote' ? 'selected' : ''}>External market quote</option><option value="Previous transaction" ${sourceValue === 'Previous transaction' ? 'selected' : ''}>Previous transaction</option><option value="Organization estimate" ${sourceValue === 'Organization estimate' ? 'selected' : ''}>Organization estimate</option><option value="Other" ${sourceValue === 'Other' ? 'selected' : ''}>Other</option></select></div><div class="field" id="resource-cost-other-wrap" ${sourceValue !== 'Other' ? 'hidden' : ''}><label for="resource-cost-other">Describe the other source</label><input id="resource-cost-other" name="cost_source_other" value="${sourceValue === 'Other' ? esc(savedSource) : ''}" placeholder="For example: supplier email quote" /></div><div class="field"><label for="resource-start">Available from</label><input id="resource-start" type="datetime-local" name="availability_start" required value="${localInput(value('availability_start') || base)}" /></div><div class="field"><label for="resource-end">Available until</label><input id="resource-end" type="datetime-local" name="availability_end" required value="${localInput(value('availability_end') || end)}" /></div>${editing ? `<div class="field"><label for="resource-status">Resource status</label><select id="resource-status" name="status"><option value="available" ${value('status') === 'available' ? 'selected' : ''}>Available</option><option value="offline" ${value('status') === 'offline' ? 'selected' : ''}>Unavailable</option><option value="maintenance" ${value('status') === 'maintenance' ? 'selected' : ''}>Under maintenance</option></select></div>` : ''}</div><div class="form-actions"><button class="secondary-btn" data-close type="button">Cancel</button><button class="primary-btn" type="submit">${editing ? 'Save changes' : 'Publish resource'}</button></div></form>`;
}
async function openResourceModal(resourceId) {
  let resource = null;
  if (resourceId) resource = arr(state.data.resources).find(item => String(item.id) === String(resourceId));
  if (resource && !ownResource(resource)) { toast('You can only edit resources owned by this organization', true); return; }
  $('#modal').innerHTML = resourceForm(resource);
  openModal();
  const sourceSelect = $('#resource-cost-source');
  const otherWrap = $('#resource-cost-other-wrap');
  if (sourceSelect && otherWrap) sourceSelect.addEventListener('change', () => { otherWrap.hidden = sourceSelect.value !== 'Other'; });
  $('#resource-form').addEventListener('submit', submitResource);
}
async function submitResource(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  const payload = Object.fromEntries(form.entries());
  payload.capacity = Number(payload.capacity || 1);
  payload.hourly_value = Number(payload.hourly_value || 0);
  payload.external_hourly_cost = Number(payload.external_hourly_cost || payload.hourly_value || 0);
  payload.cost_source = payload.cost_source === 'Other' ? (payload.cost_source_other || 'Other') : payload.cost_source;
  delete payload.cost_source_other;
  payload.availability_start = iso(payload.availability_start);
  payload.availability_end = iso(payload.availability_end);
  const id = event.target.dataset.resourceId;
  try { await api(id ? `/api/resources/${id}` : '/api/resources', { method: id ? 'PATCH' : 'POST', body: JSON.stringify(payload) }); closeModal(); await refresh(); toast(id ? 'Resource updated' : 'Resource published'); setView(state.view === 'profile' ? 'profile' : 'resources'); } catch (error) { toast(error.message, true); }
}

function planCards(mission, preferences) {
  const plans = arr(mission.plans);
  if (!plans.length) return '<div class="empty">No complete option matches these requirements. Try changing the request or time.</div>';
  return plans.map(plan => `<div class="plan-card ${preferences.includes(plan.id) ? 'selected' : ''}" data-plan-card="${esc(plan.id)}"><div class="plan-top"><input type="checkbox" value="${esc(plan.id)}" ${preferences.includes(plan.id) ? 'checked' : ''} aria-label="Accept ${esc(plan.label || plan.id)}" /><strong>${esc(plan.label || 'Option')} · ${arr(plan.items).length} resources</strong><span class="plan-score">${num(plan.match_score) === null ? '—' : `${Math.round(plan.match_score * 100)}%`}</span></div><div class="plan-items">${arr(plan.items).map(item => `<span class="plan-item">${esc(item.resource || item.name || '')} · ${esc(item.owner || '')}</span>`).join('')}</div>${plan.tradeoff ? `<div class="plan-note">${esc(plan.tradeoff)}</div>` : ''}<div class="plan-order"><button type="button" data-plan-up="${esc(plan.id)}" aria-label="Move option up">↑</button><button type="button" data-plan-down="${esc(plan.id)}" aria-label="Move option down">↓</button><small>Options are saved in card order</small></div></div>`).join('');
}
async function openMissionDetail(id) {
  try {
    const response = await api(`/api/missions/${id}`);
    const mission = response.mission || response;
    state.mission = mission;
    const preferences = arr(mission.preferences);
    const waiting = ['open', 'waitlisted'].includes(mission.status);
    const score = num(mission.fairness?.score);
    const disputes = arr(mission.disputes);
    const disputePanel = disputes.length ? `<div class="dispute-list">${disputes.map(dispute => `<div class="dispute-item"><div><strong>Dispute #${esc(dispute.id)}</strong> <span class="mission-status status-${esc(dispute.status || 'unknown')}">${esc(disputeStatus(dispute.status))}</span><p>${esc(dispute.description)}</p><small>${dispute.compensation_amount > 0 ? `Compensation request HKD ${Number(dispute.compensation_amount).toFixed(2)} · ` : ''}${arr(dispute.evidence).length} evidence file(s) · ${esc(disputeStatus(dispute.status))}</small></div>${dispute.status === 'awaiting_victim' ? `<button class="primary-btn compact" data-resolve-dispute="${esc(dispute.id)}" type="button">Mark as resolved</button>` : ''}</div>`).join('')}</div>` : '';
    const allocatedResources = arr(mission.allocated_resources);
    const allocationPanel = allocatedResources.length ? `<div class="allocation-panel"><h3 class="detail-subtitle">Approved resources</h3><p class="modal-intro">These exact resources are reserved for the scheduled use period.</p><div class="allocation-list">${allocatedResources.map(item => `<div class="allocation-item"><strong>${esc(item.resource)}</strong><span>${esc(typeLabel(item.type))} · ${esc(item.owner || '')}</span><span>${esc(item.location || '—')} · ${fmtDate(item.booking_start)} – ${fmtDate(item.booking_end)}</span><span class="tag green">${esc(item.booking_status || 'active')}</span></div>`).join('')}</div></div>` : '';
    const actions = mission.viewer_role === 'provider' ? '' : `${mission.status === 'allocated' || mission.status === 'frozen' ? '<button class="secondary-btn" id="checkout" type="button">Start using</button>' : ''}${mission.status === 'in_use' ? '<button class="primary-btn" id="complete" type="button">Confirm return</button>' : ''}${['open', 'waitlisted', 'allocated', 'frozen'].includes(mission.status) ? '<button class="secondary-btn" id="withdraw" type="button">Cancel Mission</button>' : ''}${['allocated', 'frozen', 'in_use', 'completed'].includes(mission.status) ? '<button class="text-link" id="dispute" type="button">Report a dispute</button>' : ''}`;
    $('#modal').innerHTML = `<div class="modal-head"><h2>${esc(mission.title)}</h2><button class="close-btn" data-close type="button" aria-label="Close">×</button></div><div class="mission-detail"><div class="panel detail-panel" style="box-shadow:none"><div class="eyebrow">Mission details</div><p class="lead">${esc(mission.description)}</p><div class="req-list">${arr(mission.requirements).map(requirement => `<span class="req-chip">✓ ${esc(requirement.label || requirement.text || requirement.name || '')}</span>`).join('')}</div><div class="mission-detail-meta">${statusTag(mission.status)} <span>Location: ${esc(mission.location || '—')}</span><span>Use: ${fmtDate(mission.start_at)} – ${fmtDate(mission.end_at)}</span><span>Submitted: ${fmtDate(mission.created_at)}</span><span>Cutoff: ${fmtDate(mission.deadline)}</span></div>${waiting ? `<h3 class="detail-subtitle">Acceptable options</h3><p class="modal-intro">Select options and use the arrows to set your priority. You can edit this before the deadline.</p><div id="plans">${planCards(mission, preferences)}</div><div class="form-actions"><button class="secondary-btn" id="save-prefs" type="button">Save option preferences</button></div>` : `<div class="approval-notice"><strong>${esc(missionStatus(mission.status))}</strong><span>${mission.viewer_role === 'provider' ? 'Your organization is lending the approved resources shown below.' : 'Your organization will be notified when the status changes.'}</span></div>`}${allocationPanel}${disputePanel}</div><div><div class="panel detail-panel" style="box-shadow:none"><div class="eyebrow">Current status</div><div class="score-box"><div class="score-label">Fairness Score</div><div class="score-big">${score === null ? '—' : `${Math.round(score * 100)} / 100`}</div></div>${['allocated', 'frozen'].includes(mission.status) ? '<p class="approved-copy">The Mission and requested resources are approved. You can start when the scheduled time arrives.</p>' : ''}${mission.status === 'in_use' ? '<p class="approved-copy">This Mission is in use. Confirm completion after returning the resources.</p>' : ''}<div class="detail-actions">${actions}</div></div></div></div>`;
    openModal();
    $$('#plans input[type="checkbox"]').forEach(input => input.addEventListener('change', () => input.closest('.plan-card').classList.toggle('selected', input.checked)));
    $$('[data-plan-up]').forEach(button => button.addEventListener('click', () => movePlan(button.dataset.planUp, -1)));
    $$('[data-plan-down]').forEach(button => button.addEventListener('click', () => movePlan(button.dataset.planDown, 1)));
    $('#save-prefs')?.addEventListener('click', () => savePreferences(id));
    $('#checkout')?.addEventListener('click', () => missionAction(id, 'checkout', 'Use started'));
    $('#complete')?.addEventListener('click', () => missionAction(id, 'complete', 'Return confirmed; Mission completed'));
    $('#withdraw')?.addEventListener('click', () => missionAction(id, 'withdraw', 'Mission cancelled'));
    $('#dispute')?.addEventListener('click', () => openDisputeModal(id));
    $$('[data-resolve-dispute]').forEach(button => button.addEventListener('click', async () => { try { await api(`/api/disputes/${button.dataset.resolveDispute}/resolve`, { method: 'POST', body: JSON.stringify({ resolution_note: 'The affected organization confirms the compensation and handling are complete' }) }); toast('Dispute resolved. The platform is lifting the provider freeze.'); await refresh(); openMissionDetail(id); } catch (error) { toast(error.message, true); } }));
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
  try { await api(`/api/missions/${id}/preferences`, { method: 'POST', body: JSON.stringify({ preferences }) }); toast('Option preferences saved'); await refresh(); openMissionDetail(id); } catch (error) { toast(error.message, true); }
}
async function missionAction(id, action, message) {
  try { await api(`/api/missions/${id}/${action}`, { method: 'POST', body: '{}' }); closeModal(); await refresh(); toast(message); } catch (error) { toast(error.message, true); }
}
function openDisputeModal(id) {
  const mission = state.mission || arr(state.data?.missions).find(item => String(item.id) === String(id)) || {};
  const plan = arr(mission.plans).find(item => item.id === mission.allocated_plan_id) || arr(mission.plans)[0];
  const providers = [];
  arr(plan?.items).forEach(item => { const resource = arr(state.data?.resources).find(candidate => Number(candidate.id) === Number(item.resource_id)); const ownerId = resource?.owner_org_id ?? item.owner_org_id; const ownerName = resource?.owner_name || item.owner || `Organization #${ownerId}`; if (ownerId && !providers.some(provider => Number(provider.id) === Number(ownerId))) providers.push({ id: ownerId, name: ownerName }); });
  const accusedField = providers.length > 1 ? `<div class="field"><label for="dispute-accused">Resource provider involved</label><select id="dispute-accused" name="accused_org_id" required>${providers.map(provider => `<option value="${esc(provider.id)}">${esc(provider.name)}</option>`).join('')}</select></div>` : providers.length === 1 ? `<input type="hidden" name="accused_org_id" value="${esc(providers[0].id)}" />` : '';
  $('#modal').innerHTML = `<div class="modal-head"><h2>Report a resource dispute</h2><button class="close-btn" data-close type="button" aria-label="Close">×</button></div><p class="modal-intro">Describe what happened before and after use. For monetary compensation, enter the amount and upload evidence. If approved, the provider is frozen until you confirm the issue is resolved.</p><form id="dispute-form">${accusedField}<div class="field"><label for="dispute-category">Dispute type</label><select id="dispute-category" name="category"><option value="condition">Resource condition differs</option><option value="no-show">Not delivered / no-show</option><option value="damage">Damaged or lost</option><option value="other">Other</option></select></div><div class="field"><label for="dispute-description">Description</label><textarea id="dispute-description" name="description" required placeholder="Describe what happened"></textarea></div><div class="field"><label for="dispute-amount">Compensation amount (HKD, optional)</label><small class="field-help">The compensation review and account freeze process starts only when you enter an amount.</small><input id="dispute-amount" name="compensation_amount" type="number" min="0" step="0.01" placeholder="For example: 850" /></div><div class="field"><label for="dispute-evidence">Upload evidence (required for compensation)</label><input id="dispute-evidence" name="evidence_files" type="file" multiple accept="image/*,video/*,application/pdf,.doc,.docx" /><small class="field-help">Upload photos, videos, PDFs, or documents. Up to 5 files, 10 MB each.</small></div><div class="form-actions"><button class="secondary-btn" data-close type="button">Cancel</button><button class="primary-btn" type="submit">Submit dispute</button></div></form>`;
  openModal();
  $('#dispute-form').addEventListener('submit', async event => { event.preventDefault(); try { const form = event.target; const payload = Object.fromEntries(new FormData(form).entries()); payload.compensation_amount = Number(payload.compensation_amount || 0); const files = [...($('#dispute-evidence')?.files || [])]; if (files.length > 5) throw new Error("Upload at most 5 evidence files"); if (files.some(file => file.size > 10 * 1024 * 1024)) throw new Error("Each evidence file must be at most 10 MB"); payload.evidence = await Promise.all(files.slice(0, 5).map(file => new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve({ name: file.name, type: file.type, size: file.size, data: reader.result }); reader.onerror = reject; reader.readAsDataURL(file); }))); delete payload.evidence_files; await api(`/api/missions/${id}/disputes`, { method: 'POST', body: JSON.stringify(payload) }); closeModal(); await refresh(); toast('Dispute submitted. Waiting for admin review.'); openMissionDetail(id); } catch (error) { toast(error.message, true); } });
}

function openProfileModal() { setView('profile'); }
function searchResults(query) {
  const text = query.trim().toLowerCase();
  if (!text) return '<div class="empty" style="padding:22px 0">Enter a resource or Mission name</div>';
  const missions = arr(state.data.missions).filter(item => `${item.title} ${item.description}`.toLowerCase().includes(text));
  const resources = arr(state.data.resources).filter(item => `${item.name} ${item.capability} ${item.features} ${item.location}`.toLowerCase().includes(text));
  const result = [...missions.map(item => `<button class="search-result" data-search-mission="${esc(item.id)}" type="button"><span class="tag purple">Mission</span><div><strong>${esc(item.title)}</strong><small>${esc(missionStatus(item.status))}</small></div><span>›</span></button>`), ...resources.map(item => `<button class="search-result" data-search-resource="${esc(item.id)}" type="button"><span class="tag blue">Resource</span><div><strong>${esc(item.name)}</strong><small>${esc(item.owner_name || '')} · ${esc(item.location || '')}</small></div><span>›</span></button>` )];
  return result.slice(0, 10).join('') || '<div class="empty" style="padding:22px 0">No matches found</div>';
}
function openGlobalSearch() {
  $('#modal').innerHTML = `<div class="modal-head"><h2>Search</h2><button class="close-btn" data-close type="button" aria-label="Close">×</button></div><div class="field"><label for="global-search-input">Search resources or my Missions</label><input id="global-search-input" autofocus placeholder="For example: camera, studio, or demo" /></div><div id="search-results" style="margin-top:14px"></div>`;
  openModal();
  const input = $('#global-search-input');
  const update = () => { $('#search-results').innerHTML = searchResults(input.value); $$('[data-search-mission]').forEach(button => button.addEventListener('click', () => { closeModal(); openMissionDetail(button.dataset.searchMission); })); $$('[data-search-resource]').forEach(button => button.addEventListener('click', () => { closeModal(); openResourceInfo(button.dataset.searchResource); })); };
  input.addEventListener('input', update); update(); input.focus();
}
function openResourceInfo(id) {
  const resource = arr(state.data.resources).find(item => String(item.id) === String(id));
  if (!resource) return toast('Resource is no longer available', true);
  const canEdit = ownResource(resource);
  $('#modal').innerHTML = `<div class="modal-head"><h2>${esc(resource.name)}</h2><button class="close-btn" data-close type="button" aria-label="Close">×</button></div><div class="resource-info"><p>${esc(resource.features || resource.capability || 'No description')}</p><dl><dt>Provider</dt><dd>${esc(resource.owner_name || '')}</dd><dt>Location</dt><dd>${esc(resource.location || '—')}</dd><dt>Available time</dt><dd>${fmtDate(resource.availability_start)} – ${fmtDate(resource.availability_end)}</dd><dt>Status</dt><dd>${esc(resourceStatus(resource.status))}</dd></dl></div><div class="form-actions">${canEdit ? `<button class="primary-btn" id="resource-info-edit" type="button">Edit my resource</button>` : ''}<button class="secondary-btn" data-close type="button">Close</button></div>`;
  openModal();
  $('#resource-info-edit')?.addEventListener('click', () => openResourceModal(id));
}
function openActivityModal() {
  const events = arr(state.data.events);
  $('#modal').innerHTML = `<div class="modal-head"><h2>Recent activity</h2><button class="close-btn" data-close type="button" aria-label="Close">×</button></div><p class="modal-intro">Only notifications related to ${esc(org().short_name || 'this organization')} are shown here.</p><div class="activity-list" style="padding:0">${events.length ? events.map(eventRow).join('') : '<div class="empty">No notifications yet</div>'}</div>`;
  openModal();
}
function openHelpModal() {
  $('#modal').innerHTML = `<div class="modal-head"><h2>Resource and Mission guide</h2><button class="close-btn" data-close type="button" aria-label="Close">×</button></div><div class="help-guide"><div class="help-guide-item"><span class="help-guide-icon">1</span><div><strong>1. Publish resources first</strong><p>In Resources, click “Publish resource” and add its type, capabilities, schedule, location, and status. You can edit published resources from your profile.</p></div></div><div class="help-guide-item"><span class="help-guide-icon">2</span><div><strong>2. Submit a Mission</strong><p>Describe the need, location, and time. After the deadline, the platform resolves conflicts and produces an allocation.</p></div></div><div class="help-guide-item"><span class="help-guide-icon">3</span><div><strong>3. Check the result</strong><p>When a Mission, piece of equipment, or space is approved, the result appears in the Mission details and organization notifications.</p></div></div></div><div class="form-actions"><button class="primary-btn" data-close type="button">Got it</button></div>`;
  openModal();
}
function openOrgMenu() {
  const current = document.querySelector('.org-menu');
  if (current) { current.remove(); return; }
  const organizations = arr(state.data.organizations);
  const menu = document.createElement('div');
  menu.className = 'org-menu';
  menu.setAttribute('role', 'menu');
  menu.innerHTML = `${organizations.map(item => `<button type="button" data-org="${esc(item.id)}"><span class="avatar">${esc((item.short_name || item.name || '—')[0])}</span><div><strong>${esc(item.short_name || item.name)}</strong><small>Local demo organization session</small></div></button>`).join('') || '<div class="empty">No organizations available</div>'}`;
  document.body.appendChild(menu);
  $$('[data-org]', menu).forEach(button => button.addEventListener('click', async () => { try { await api('/api/switch-user', { method: 'POST', body: JSON.stringify({ organization_id: Number(button.dataset.org) }) }); menu.remove(); await refresh(); toast(`Switched to ${state.data.organization.short_name || state.data.organization.name}`); } catch (error) { toast(error.message, true); } }));
}
function openModal() { const backdrop = $('#modal-backdrop'); backdrop.classList.add('open'); backdrop.setAttribute('aria-hidden', 'false'); $$('[data-close]').forEach(button => button.addEventListener('click', closeModal)); }
function closeModal() { const backdrop = $('#modal-backdrop'); backdrop.classList.remove('open'); backdrop.setAttribute('aria-hidden', 'true'); }
let adminHost = null;
async function openAdminConsole() {
  if (adminHost) return;
  try {
    const response = await fetch('/static/admin.html', { credentials: 'same-origin' });
    if (!response.ok) throw new Error('Could not load the admin console');
    const html = await response.text();
    const parsed = new DOMParser().parseFromString(html, 'text/html');
    const shell = parsed.querySelector('.admin-shell');
    if (!shell) throw new Error('The admin console is invalid');
    adminHost = document.createElement('div');
    adminHost.className = 'admin-modal-host';
    adminHost.setAttribute('role', 'dialog');
    adminHost.setAttribute('aria-label', 'admin console');
    adminHost.innerHTML = shell.outerHTML;
    document.body.appendChild(adminHost);
    if (!document.querySelector('link[data-admin-css]')) {
      const style = document.createElement('link'); style.rel = 'stylesheet'; style.href = '/static/admin.css?v=20261004perf1'; style.dataset.adminCss = '1'; document.head.appendChild(style);
    }
    window.closeAdminConsole = () => { window.stopAdminSync?.(); adminHost?.remove(); adminHost = null; delete window.closeAdminConsole; };
    const script = document.createElement('script'); script.src = '/static/admin.js?overlay=20261004perf1'; adminHost.appendChild(script);
  } catch (error) { toast(error.message, true); }
}
async function refresh() {
  state.data = await api('/api/bootstrap');
  $('#org-name').textContent = state.data.organization?.short_name || state.data.organization?.name || 'my organization';
  $('#org-avatar').textContent = (state.data.organization?.short_name || state.data.organization?.name || '—')[0];
  renderView();
  startUserSync();
}
async function syncUserData() {
  if (!state.data || userSyncBusy || document.hidden || adminHost) return;
  userSyncBusy = true;
  try {
    const version = await api('/api/version');
    if (version.version !== state.data.version) {
      const next = await api('/api/bootstrap');
      state.data = next;
      $('#org-name').textContent = next.organization?.short_name || next.organization?.name || 'my organization';
      $('#org-avatar').textContent = (next.organization?.short_name || next.organization?.name || '—')[0];
      renderView();
    }
  } catch (_) {
    // A temporary polling failure should not interrupt the user flow.
  } finally {
    userSyncBusy = false;
  }
}
function startUserSync() {
  if (!userSyncTimer) userSyncTimer = window.setInterval(syncUserData, 5000);
}
function boot() {
  navSetup();
  document.addEventListener('click', event => { if (event.target.closest('#new-mission')) { event.preventDefault(); openMissionModal(); } });
  let brandClicks = 0; let brandTimer;
  $('.brand-mark')?.addEventListener('click', () => { brandClicks += 1; window.clearTimeout(brandTimer); brandTimer = window.setTimeout(() => { brandClicks = 0; }, 1500); if (brandClicks >= 5) { brandClicks = 0; openAdminConsole(); } });
  $('#switch-org').addEventListener('click', openOrgMenu);
  $('#workspace-profile').addEventListener('click', openProfileModal);
  $('#help-guide').addEventListener('click', openHelpModal);
  $('#global-search').addEventListener('click', openGlobalSearch);
  $('#activity-toggle').addEventListener('click', openActivityModal);
  window.addEventListener('keydown', event => { if (event.altKey && event.shiftKey && event.key.toLowerCase() === 'a') { event.preventDefault(); openAdminConsole(); } });
  $('#open-resource').addEventListener('click', () => openResourceModal());
  $('#modal-backdrop').addEventListener('click', event => { if (event.target.id === 'modal-backdrop') closeModal(); });
  refresh().catch(error => toast(error.message, true));
}
boot();
