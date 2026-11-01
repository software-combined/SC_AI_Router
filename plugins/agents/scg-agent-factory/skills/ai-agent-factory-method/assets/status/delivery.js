import { validate, counts, flags, gaps, accepted, released, delivery, humanRequests, liveEnvironment, environments, assetPath, webLink, recorded } from './delivery-model.mjs';
const $ = id => document.getElementById(id);
const embedded = window.self !== window.top;
document.documentElement.classList.toggle('embedded', embedded);
/** Embedded copies replace the hash only, so the host page's Back button is unaffected. */
function setHash(hash, push) { try { history[push && !embedded ? 'pushState' : 'replaceState'](null, '', hash); return push && !embedded; } catch { return false; } }
const node = (tag, text, cls) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (cls) el.className = cls; return el; };
const missing = value => value || 'Not recorded';
const VIEWS = { overview: 'overview', input: 'input', all: 'all' };
const TITLES = { input: 'Needs your input', all: 'All work' };
const CHIPS = [['all', 'All'], ['done', 'Done'], ['progress', 'In progress'], ['action', 'Needs attention'], ['todo', 'Not started'], ['unknown', 'Not recorded'], ['deferred', 'Deferred']];
const TAG_CLASS = { done: 'tag-done', progress: 'tag-progress', action: 'tag-action', todo: 'tag-todo', unknown: 'tag-todo', deferred: 'tag-deferred' };
const EXPLAIN = { 'Done ✓': 'People can use this, and a named person confirmed it works as agreed.', 'Live, user check due': 'People can use this now. Their check of the agreed result is still missing.', 'Availability unconfirmed': 'The work is reported live, but the supporting record is missing.', 'Ready to publish': 'The work is prepared. It is not yet available to the intended people.', 'On test version': 'This is available for testing. It is not yet available to the intended people.', 'Being reviewed': 'The work is built. The team is reviewing it.', 'In progress': 'The team is building this.', 'Not started': 'The work is planned and has not started.', 'Status not recorded': 'The source does not record whether this work has started.', Deferred: 'This is outside the current plan and its progress counts.' };
const numberOf = (n, singular, plural = `${singular}s`) => `${n} ${n === 1 ? singular : plural}`;
const kinds = list => { const checks = list.filter(r => r.f.kind === 'acceptance').length; return checks ? `${numberOf(list.length - checks, 'feature')} and ${numberOf(checks, 'user check')}` : numberOf(list.length, 'feature'); };
let payload;
let data, rows = [], view = 'overview', chip = 'all', opener = null, pushedDetail = false, returnFocus = '', openId = '';
let theme;
try { theme = localStorage.getItem('feature-tracker-theme'); } catch {}
if (!['light', 'dark'].includes(theme)) theme = matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
function applyTheme(value) { document.documentElement.dataset.theme = value; $('theme-toggle').textContent = value === 'dark' ? 'Light mode' : 'Dark mode'; }
applyTheme(theme);
$('theme-toggle').addEventListener('click', () => {
  theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  applyTheme(theme);
  try { localStorage.setItem('feature-tracker-theme', theme); } catch {}
});
function date(value) {
  if (!value) return 'Not recorded';
  const d = new Date(value.length === 10 ? `${value}T12:00:00+11:00` : value);
  return Number.isNaN(d.getTime()) ? 'Not recorded' : new Intl.DateTimeFormat('en-AU', { timeZone: 'Australia/Sydney', day: '2-digit', month: '2-digit', year: 'numeric', ...(value.length > 10 ? { hour: '2-digit', minute: '2-digit', timeZoneName: 'short' } : {}) }).format(d);
}
function link(label, url) { const href = webLink(url); if (!href) return node('span', label); const a = node('a', label); a.href = href; a.target = '_blank'; a.rel = 'noopener'; return a; }
function links(items) { const box = node('span', undefined, 'links'); box.append(...(items?.length ? items.map(e => e.reference ? node('span', `${e.label}: ${e.reference}`) : link(e.label, e.url)) : [node('span', 'Not recorded')])); return box; }
function withEvidence(text, items) { const box = node('span'); box.append(node('span', text), links(items)); return box; }
function tag(text, cls) { return node('span', text, `tag ${cls}`); }
function tags(row) { const box = node('p', undefined, 'tags'); box.append(tag(row.d.tag, TAG_CLASS[row.d.group])); if (row.d.warning) box.append(tag(row.d.warning, 'tag-warning')); return box; }
function envLabel(environment) { return environment === liveEnvironment(data.project) ? 'Live' : 'Test version'; }
function section(title, ...content) { const box = node('section', undefined, 'detail-section'); box.append(node('h3', title), ...content); return box; }
function ready(value) {
  document.querySelectorAll('[role="tab"]').forEach(t => { t.disabled = !value; if (!value) { t.setAttribute('aria-selected', 'false'); t.tabIndex = -1; } });
  if (!value) { $('overview').hidden = true; $('list').hidden = true; }
}
function selectView(next, focus = false) {
  if (!data) return;
  view = next;
  const tabId = `tab-${hashFor(next)}`;
  document.querySelectorAll('[role="tab"]').forEach(t => { const on = t.id === tabId; t.setAttribute('aria-selected', String(on)); t.tabIndex = on ? 0 : -1; });
  $('overview').hidden = next !== 'overview'; $('list').hidden = next === 'overview';
  $('list').setAttribute('aria-labelledby', tabId);
  if (next !== 'overview') renderList();
  $(tabId).scrollIntoView({ block: 'nearest', inline: 'nearest' });
  if (focus) $(tabId).focus();
}
function hashFor(next) { return Object.keys(VIEWS).find(k => VIEWS[k] === next); }
function viewOf(tab) { return VIEWS[tab.id.slice(4)]; }
function go(next, focus = false) { if (view !== next) for (const id of ['search', 'phase', 'owner']) $(id).value = ''; selectView(next, focus); setHash(`#${hashFor(next)}`, true); }
function route() {
  if (!data) return;
  let hash = location.hash.slice(1); try { hash = decodeURIComponent(hash); } catch {}
  const row = rows.find(r => hash === `feature-${r.f.id}`);
  if (row) { if (view === 'overview') selectView('all'); openDetail(row, false); return; }
  if ($('detail').open) { pushedDetail = false; $('detail').close(); }
  const restore = returnFocus; returnFocus = '';
  if (restore) setTimeout(() => $(restore)?.focus(), 0);
  if (hash.startsWith('task-')) { $('search').value = hash.slice(5); chip = 'all'; selectView('all'); return; }
  if (hash === 'guide') { selectView('overview'); $('help').showModal(); return; }
  const oldGroups = { 'in-progress': 'progress', 'needs-action': 'action', done: 'done' };
  if (oldGroups[hash]) { chip = oldGroups[hash]; selectView('all'); return; }
  selectView(VIEWS[hash] || (['features', 'tasks'].includes(hash) ? 'all' : 'overview'));
}
function options(select, field, values) {
  const current = select.value, unique = [...new Set(values)].sort((a, b) => a.localeCompare(b, 'en', { numeric: true }));
  select.replaceChildren(node('option', field === 'phase' ? 'All stages' : 'All owners'), ...unique.map(v => { const o = node('option', v); o.value = v; return o; }));
  select.firstChild.value = ''; select.value = unique.includes(current) ? current : '';
  $(`${field}-field`).hidden = unique.length < 2;
}
function showGroup(group) { chip = group; for (const id of ['search', 'phase', 'owner']) $(id).value = ''; go('all', true); }
function requestList(row) {
  return humanRequests(row.f).map((d, index) => {
    const item = node('li'), button = node('button', d.text, 'request-question'); button.type = 'button';
    button.id = `request-${row.f.id}-${index}`;
    button.addEventListener('click', () => openDetail(row));
    item.append(node('p', `${d.owner} · ${row.f.title}`, 'muted'), button);
    if (d.context) item.append(node('p', d.context));
    if (d.options?.length) item.append(node('p', `Options: ${d.options.join(' / ')}`, 'muted'));
    return item;
  });
}
function overview() {
  const p = data.project, n = counts(data), active = rows.filter(r => r.f.scope === 'active');
  const count = group => active.filter(r => r.f.kind === 'implementation' && r.d.group === group).length;
  document.title = p.title; $('title').textContent = p.title;
  $('outcome').textContent = p.outcome || ''; $('outcome').hidden = !p.outcome;
  const live = n.releases[liveEnvironment(p)];
  $('availability').textContent = p.availability || (live.released ? `${live.released} of ${n.total} features confirmed available to use.` : live.unknown === n.total ? 'Live availability is not recorded.' : 'No complete live release is recorded.');
  $('availability').hidden = !n.total && !p.availability;
  $('checked').textContent = `Last checked: ${date(p.checked)}`;
  $('updated').textContent = `Page updated: ${date(payload.generatedAt)}`;
  const source = webLink(p.source?.url); if (source) { $('source').href = source; $('source').hidden = false; }
  const stale = !p.template && p.staleDays > 0 && (!p.checked || !Number.isFinite(Date.parse(p.checked)) || Date.now() - Date.parse(p.checked) > p.staleDays * 86400000);
  $('notice').textContent = [p.template ? 'Example only. This is not a live project.' : '', p.notice, stale ? `The evidence needs a fresh check. The agreed review window is ${p.staleDays} days.` : ''].filter(Boolean).join(' '); $('notice').hidden = !$('notice').textContent;
  const requests = active.flatMap(requestList);
  $('requests').replaceChildren(...(requests.length ? requests.slice(0, 3) : [node('li', 'Nothing needs your input right now.', 'muted')]));
  if (requests.length > 3) { const li = node('li'), b = node('button', `View all ${requests.length} questions`); b.addEventListener('click', () => go('input', true)); li.append(b); $('requests').append(li); }
  for (const el of document.querySelectorAll('[data-count]')) el.textContent = el.dataset.count === 'all' ? rows.length : requests.length;
  $('tiles').replaceChildren(...[['done', 'Done ✓'], ['progress', 'In progress'], ['action', 'Needs attention'], ['todo', 'Not started']].map(([group, label]) => {
    const b = node('button', undefined, `tile tile-${group}`); b.type = 'button';
    b.append(node('span', `${count(group)} / ${n.total}`, 'tile-number'), node('span', label, 'tile-label'));
    b.addEventListener('click', () => showGroup(group)); return b;
  }));
  $('tile-note').textContent = [count('unknown') ? `${numberOf(count('unknown'), 'feature')} with no recorded status.` : '', n.acceptanceRecords ? `${numberOf(n.acceptanceRecords, 'user check')} counted separately.` : '', n.excluded ? `${numberOf(n.excluded, 'item')} outside the current plan.` : ''].filter(Boolean).join(' '); $('tile-note').hidden = !$('tile-note').textContent;
  const team = active.filter(r => ['progress', 'action', 'unknown'].includes(r.d.group) && !humanRequests(r.f).length);
  $('reasons').replaceChildren(...(team.length ? team.slice(0, 3).map(r => {
    const li = node('li'), b = node('button', undefined, 'reason'); b.type = 'button'; b.id = `team-${r.f.id}`;
    b.append(node('span', r.f.title), node('small', r.f.nextAction || EXPLAIN[r.d.tag], 'muted'));
    b.addEventListener('click', () => openDetail(r)); li.append(b); return li;
  }) : [node('li', 'No active team work is recorded.', 'muted')]));
  $('changes').replaceChildren(...(data.changes || []).slice(0, 3).map(c => { const li = node('li'); li.append(node('time', date(c.date)), node('span', c.text)); return li; }));
  $('changes-panel').hidden = !data.changes?.length;
  const lines = [`Built and saved in shared source: ${n.merged} of ${n.total} features.`,
    ...Object.entries(n.releases).map(([env, c]) => `${envLabel(env)}: ${c.released} of ${n.total} features available.${c.sourceReported ? ` ${c.sourceReported} reported available without complete evidence.` : ''}${c.unknown ? ` ${c.unknown} availability records missing.` : ''}`),
    `User checked on the live version: ${n.accepted} of ${n.total} features.`, p.availability, p.sourceMapping].filter(Boolean);
  $('breakdown').replaceChildren(...lines.map(l => node('li', l)));
}
function visible() {
  const q = $('search').value.trim().toLowerCase(), phase = $('phase').value, owner = $('owner').value;
  const group = view === 'input' ? 'all' : chip;
  const list = rows.filter(r => (view !== 'input' || humanRequests(r.f).length) && (group === 'all' || r.d.group === group) &&
    (!phase || r.f.phase === phase) && (!owner || missing(r.f.owner) === owner) &&
    [r.f.id, r.f.title, r.f.outcome, r.f.owner, r.f.nextAction, ...(r.f.tasks || [])].join(' ').toLowerCase().includes(q));
  return group === 'action' ? list.sort((a, b) => Number(!!b.d.warning) - Number(!!a.d.warning)) : list;
}
function card(row) {
  const li = node('li'), b = node('button', undefined, 'card'); b.type = 'button'; b.id = `card-${row.f.id}`;
  const facts = node('dl'); facts.append(node('dt', 'Owner'), node('dd', missing(row.f.owner), row.f.owner ? '' : 'unknown'), node('dt', 'Next step'), node('dd', missing(row.f.nextAction), row.f.nextAction ? '' : 'unknown'));
  b.append(tags(row), node('h3', row.f.title)); if (row.f.outcome) b.append(node('p', row.f.outcome, 'outcome'));
  if (view === 'input') b.append(node('p', humanRequests(row.f).map(d => `${d.owner}: ${d.text}`).join(' '), 'input-question'));
  b.append(facts);
  b.addEventListener('click', () => openDetail(row));
  li.append(b); return li;
}
function renderList() {
  $('list-title').textContent = TITLES[view];
  $('chips').hidden = view !== 'all';
  $('chips').replaceChildren(...CHIPS.map(([value, label]) => { const b = node('button', label, 'chip'); b.type = 'button'; b.dataset.chip = value; b.setAttribute('aria-pressed', String(chip === value)); b.addEventListener('click', () => { chip = value; renderList(); $('chips').querySelector(`[data-chip="${value}"]`).focus(); }); return b; }));
  const list = visible();
  $('cards').replaceChildren(...list.map(card)); $('empty').hidden = list.length > 0;
  $('list-count').textContent = kinds(list);
}
function shot(s, f) {
  const src = payload.images?.[assetPath(s.src)]; if (!src) return null;
  const fig = node('figure'), button = node('button', undefined, 'shot'), img = node('img');
  button.type = 'button'; button.setAttribute('aria-label', `Open full size: ${s.alt || s.caption || s.title || f.title}`);
  img.src = src; img.alt = s.alt || s.caption || f.title; img.loading = 'lazy'; button.append(img);
  const caption = node('figcaption'); caption.append(node('strong', s.title || f.title), node('small', [missing(s.environment), date(s.captured), s.criterion ? `Shows ${s.criterion}` : ''].filter(Boolean).join(' · ')));
  const fullCaption = [s.caption, missing(s.environment), date(s.captured), missing(s.data), `Revision: ${missing(s.revision)}`].filter(Boolean).join(' · ');
  button.addEventListener('click', () => { $('picture-image').src = src; $('picture-image').alt = img.alt; $('picture-caption').textContent = fullCaption; $('picture').showModal(); });
  fig.append(button, caption); return fig;
}
function steps(f) {
  const live = liveEnvironment(data.project), ol = node('ol', undefined, 'steps');
  const add = (label, ok, text) => { const li = node('li', undefined, ok ? 'step-ok' : ''); li.append(node('span', ok ? '✓' : '', 'step-mark'), node('strong', label), node('span', text)); ol.append(li); };
  add('Built', f.build === 'Merged', f.build === 'Merged' ? 'Saved in shared source' : ({ Building: 'In progress', 'In review': 'Being reviewed' }[f.build] || f.build));
  for (const environment of environments(data.project)) {
    const r = f.releases.find(x => x.environment === environment), ok = released(r);
    add(envLabel(environment), ok, ok ? 'Available' : r?.state === 'Released' ? 'Availability unconfirmed' : r?.state === 'Not released' ? 'Not yet available' : missing(r?.state));
  }
  const ok = accepted(f) && f.acceptance.environment === live;
  add('User check', ok, ok ? `Checked by ${f.acceptance.owner}` : accepted(f) ? 'Checked on the test version only' : f.acceptance.state === 'Accepted' ? 'The user check record is incomplete' : missing(f.acceptance.state));
  return ol;
}
function openDetail(row, push = true) {
  const f = row.f, d = row.d; openId = f.id;
  if (push) { opener = document.activeElement; pushedDetail = setHash(`#feature-${encodeURIComponent(f.id)}`, true); }
  $('detail-tags').replaceWith(Object.assign(tags(row), { id: 'detail-tags' }));
  $('detail-title').textContent = f.title;
  const body = [];
  const what = [node('p', f.outcome || 'Outcome not recorded.')];
  const scope = [f.inScope && `Includes: ${f.inScope}`, f.outOfScope && `Excludes: ${f.outOfScope}`, f.successMeasure && `Success: ${f.successMeasure}`, f.scopeReason].filter(Boolean);
  if (scope.length) what.push(node('p', scope.join(' '), 'muted'));
  body.push(section('What this gives you', ...what));
  const status = [node('p', EXPLAIN[d.tag] || '')];
  if (f.blocker) status.push(node('p', `Blocked: ${f.blocker}`, 'warning'));
  if (d.warning === 'Overdue') {
    if (f.target) status.push(node('p', `Target date: ${date(f.target)}.`, 'warning'));
    for (const x of (f.decisions || []).filter(x => !recorded(x.result) && x.due)) status.push(node('p', `Decision due ${date(x.due)}: ${x.text}`, 'warning'));
  }
  if (d.warning === 'Reopened') status.push(node('p', 'A check found a problem, so this was reopened.', 'warning'));
  if (d.warning === 'Evidence missing') status.push(node('p', 'The supporting record needs to be completed before this can count as done.', 'warning'));
  body.push(section('Can I use it?', ...status));
  if (humanRequests(f).length) { const ul = node('ul', undefined, 'requests'); ul.append(...humanRequests(f).map(x => { const li = node('li'); li.append(node('strong', x.text), node('p', `Owner: ${x.owner}`)); if (x.context) li.append(node('p', x.context)); if (x.options?.length) li.append(node('p', `Options: ${x.options.join(' / ')}`)); return li; })); body.push(section('Needs your input', ul, node('p', 'The named owner replies in the project chat.', 'muted'))); }
  const who = node('dl', undefined, 'facts');
  who.append(node('dt', 'Owner'), node('dd', missing(f.owner)), node('dt', 'Next step'), node('dd', missing(f.nextAction)));
  if (f.nextActionOwner && f.nextActionOwner !== f.owner) who.append(node('dt', 'Next step by'), node('dd', f.nextActionOwner));
  if (f.target) who.append(node('dt', 'Agreed date'), node('dd', date(f.target)));
  body.push(section('Who is handling it?', who));
  body.push(section('Progress', steps(f)));
  const criteria = node('ul', undefined, 'plain');
  criteria.append(...(f.criteria?.length ? f.criteria.map(c => { const li = node('li'); li.append(node('span', c.text || c.id), node('small', ` ${c.state || 'Not recorded'}`, 'muted')); return li; }) : [node('li', 'Not recorded.', 'muted')]));
  body.push(section('What must work', criteria));
  const pictures = (f.screenshots || []).map(s => shot(s, f)).filter(Boolean);
  if (pictures.length) { const box = node('div', undefined, 'shots'); box.append(...pictures); body.push(section('Screenshots', box)); }
  const taskDetails = [];
  if (f.tasks?.length) {
    const ul = node('ul', undefined, 'plain');
    ul.append(...f.tasks.map(id => { const t = data.tasks.find(x => x.id === id); return node('li', t ? `${t.id}: ${t.title} · ${missing(t.state)}` : id); }));
    taskDetails.push(section('Build tasks', ul));
  }
  const proof = node('details', undefined, 'proof'), table = node('table'), tbody = node('tbody');
  proof.append(node('summary', 'Technical details'));
  const rowsOf = [['Record', node('span', [f.id, f.phase, f.priority].filter(Boolean).join(' · '))], ['Other owners', node('span', [f.productOwner, f.developmentOwner, f.releaseOwner].filter(Boolean).join(' · ') || 'Not recorded')], ['Pull requests and source', links(f.evidence)], ['Commits', links(f.commits)], ['Automated tests', links(f.checks)],
    ...f.releases.map(r => [`Release: ${r.environment}`, withEvidence(`${r.state}. Audience: ${missing(r.audience)}. Revision: ${missing(r.revision)}. `, r.evidence)]),
    ['User check record', withEvidence(`${f.acceptance.state}. By: ${missing(f.acceptance.owner)}. Date: ${date(f.acceptance.acceptedAt)}. Environment: ${missing(f.acceptance.environment)}. Revision: ${missing(f.acceptance.revision)}. `, f.acceptance.evidence)],
    ['Requirement evidence', links((f.criteria || []).flatMap(c => c.evidence || []))],
    ['Decisions', node('span', (f.decisions || []).map(x => `${x.text} · ${missing(x.owner)} · ${date(x.due)}${x.result ? ` · ${x.result}` : ''}`).join('. ') || 'None recorded')],
    ['Dependencies', node('span', (f.dependencies || []).map(x => typeof x === 'object' ? `${x.id} · ${missing(x.state)}` : x).join('. ') || 'None recorded')],
    ['Source state', node('span', missing(f.sourceState))], ['Source note', node('span', f.note || 'None')],
    ['Missing details', node('span', gaps(f).join(', ') || 'None')], ['Checks raised', node('span', flags(f, data.project).join(' · ') || 'None')]];
  for (const [label, content] of rowsOf) { const tr = node('tr'), th = node('th', label); th.scope = 'row'; const td = node('td'); td.append(content); tr.append(th, td); tbody.append(tr); }
  table.append(tbody); proof.append(...taskDetails, table); body.push(proof);
  $('detail-body').replaceChildren(...body); $('detail').scrollTop = 0;
  if (!$('detail').open) $('detail').showModal();
  $('close-detail').focus();
}
function closeDetail() {
  if ($('detail').open) $('detail').close();
}
$('detail').addEventListener('close', () => {
  const id = opener?.id || ($(`card-${openId}`) ? `card-${openId}` : `tab-${hashFor(view)}`); opener = null;
  if (location.hash.startsWith('#feature-') && pushedDetail) { pushedDetail = false; returnFocus = id; history.back(); return; }
  if (location.hash.startsWith('#feature-')) setHash(`#${hashFor(view)}`, false);
  pushedDetail = false;
  if (id) setTimeout(() => $(id)?.focus(), 0);
});
$('detail').addEventListener('click', event => { if (event.target === $('detail')) closeDetail(); });
function load() {
  data = null; ready(false); $('error').hidden = true;
  try {
    payload = JSON.parse($('status-data').textContent);
    data = validate(payload.records);
    render();
  } catch (error) { data = null; ready(false); $('tiles').replaceChildren(); $('cards').replaceChildren(); $('error-detail').textContent = error.message; $('error').hidden = false; }
}
function render() {
  rows = data.features.map(f => ({ f, d: delivery(f, data.project) }));
  options($('phase'), 'phase', rows.map(r => r.f.phase).filter(Boolean));
  options($('owner'), 'owner', rows.map(r => missing(r.f.owner)));
  overview(); ready(true); route();
}
for (const id of ['search', 'phase', 'owner']) $(id).addEventListener(id === 'search' ? 'input' : 'change', () => data && renderList());
document.querySelectorAll('[role="tab"]').forEach(t => {
  t.addEventListener('click', () => go(viewOf(t)));
  t.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault(); const tabs = [...document.querySelectorAll('[role="tab"]')], index = tabs.indexOf(t);
    const next = tabs[event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
    go(viewOf(next), true);
  });
});
window.addEventListener('hashchange', route);
document.querySelector('.skip').addEventListener('click', event => { event.preventDefault(); chip = 'all'; go('all'); $('search').focus(); });
$('help-open').addEventListener('click', () => $('help').showModal());
$('close-help').addEventListener('click', () => $('help').close());
$('close-detail').addEventListener('click', closeDetail);
$('close-picture').addEventListener('click', () => $('picture').close());
load();
