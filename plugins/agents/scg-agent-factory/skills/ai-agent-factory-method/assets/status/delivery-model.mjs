export const BUILD = ['Not recorded', 'Planned', 'Building', 'In review', 'Merged'];
export const RELEASE = ['Not recorded', 'Not released', 'Partial', 'Released', 'Rolled back'];
export const ACCEPTANCE = ['Not recorded', 'Pending', 'Accepted', 'Reopened'];
export function assetPath(value) {
  return typeof value === 'string' && /^(?:img|screenshots)\/[a-zA-Z0-9_-]+\.(?:png|jpg|jpeg|webp)$/i.test(value) ? value : null;
}
export function webLink(value) {
  try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password ? url.href : null; } catch { return null; }
}
export function validate(data) {
  if (data?.schemaVersion !== 1 || !data?.project?.title || !Array.isArray(data.features) || !Array.isArray(data.tasks)) throw new Error('Invalid tracker data');
  if (data.project.template !== undefined && typeof data.project.template !== 'boolean') throw new Error('Template mode must be true or false');
  const ids = new Set();
  for (const f of data.features) {
    if (!f.id || ids.has(f.id) || !f.title || !BUILD.includes(f.build) || !Array.isArray(f.releases) || !ACCEPTANCE.includes(f.acceptance?.state)) throw new Error('Invalid feature');
    const environments = new Set();
    for (const r of f.releases) { if (!r.environment || environments.has(r.environment) || !RELEASE.includes(r.state)) throw new Error('Invalid release'); environments.add(r.environment); }
    if (!['active', 'deferred', 'replaced'].includes(f.scope) || !['implementation', 'acceptance'].includes(f.kind)) throw new Error('Invalid scope');
    if (!data.project.template && (f.sample || /^\[Example:/i.test(f.title))) throw new Error('Replace example records before reporting real work');
    if (f.decisions && (!Array.isArray(f.decisions) || f.decisions.some(d => !d || typeof d !== 'object'))) throw new Error('Invalid decisions');
    ids.add(f.id);
  }
  return data;
}
export const recorded = value => typeof value === 'string' && !!value.trim() && value.trim().toLowerCase() !== 'not recorded' && !/^\s*\[.*\]\s*$/.test(value);
const timestamp = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(value) && Number.isFinite(Date.parse(value));
const evidence = items => Array.isArray(items) && items.some(e => {
  const url = webLink(e?.url);
  return recorded(e?.label) && (recorded(e?.reference) || (url && !/(^|\.)(example\.(com|org|net)|[^.]+\.(example|test|invalid))$/.test(new URL(url).hostname)));
});
export const humanRequests = f => f.scope === 'active' ? (f.decisions || []).filter(d => d.audience === 'human' && !recorded(d.result) && recorded(d.text) && recorded(d.owner)) : [];
export function released(release) {
  return release?.state === 'Released' && recorded(release.environment) && recorded(release.audience) &&
    recorded(release.revision) && evidence(release.evidence);
}
export function accepted(f) {
  const release = f.releases.find(r => r.environment === f.acceptance.environment);
  return f.acceptance.state === 'Accepted' && recorded(f.acceptance.owner) && timestamp(f.acceptance.acceptedAt) && evidence(f.acceptance.evidence) &&
    !!f.criteria?.length && f.criteria.every(c => recorded(c.id) && recorded(c.text) && c.state === 'Passed' && evidence(c.evidence)) &&
    released(release) && f.acceptance.revision === release.revision;
}
const sydneyDay = now => new Intl.DateTimeFormat('en-CA', { timeZone: 'Australia/Sydney', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(now));
export function flags(f, project, now = Date.now(), { missingReleases = true } = {}) {
  const result = [];
  const today = sydneyDay(now);
  if (f.blocker) result.push(`Blocked: ${f.blocker}`);
  for (const d of f.dependencies || []) if (typeof d === 'object' && d.state === 'Open') result.push(`Dependency open: ${d.id}`);
  for (const d of f.decisions || []) if (!recorded(d.result) && d.due && d.due < today) result.push('Decision date passed');
  if (f.acceptance.state === 'Reopened') result.push('User acceptance reopened');
  if (f.acceptance.state === 'Accepted' && !accepted(f)) result.push('Acceptance evidence incomplete');
  if (f.target && f.target < today && !accepted(f)) result.push('Target date passed');
  for (const r of f.releases) {
    if (missingReleases && f.build === 'Merged' && r.state === 'Not recorded') result.push(`${r.environment} release not recorded`);
    if (r.state === 'Released' && !recorded(r.revision)) result.push(`${r.environment} release revision not recorded`);
    else if (r.state === 'Released' && !released(r)) result.push(`${r.environment} release evidence incomplete`);
  }
  return result;
}
export const liveEnvironment = project => project?.liveEnvironment || 'Production';
/** Release environments to show, always including the live one. */
export const environments = project => [...new Set([...(project?.environments || ['Staging', 'Production']), liveEnvironment(project)])];
/** One reader-facing group per record: done, progress, action, todo or deferred. */
export function delivery(f, project = {}, now = Date.now()) {
  if (f.scope !== 'active') return { group: 'deferred', tag: 'Deferred', warning: '' };
  const live = liveEnvironment(project), day = sydneyDay(now);
  const complete = accepted(f) && f.acceptance.environment === live;
  const overdue = (!complete && f.target && f.target < day) || (f.decisions || []).some(d => !recorded(d.result) && d.due && d.due < day);
  const dependency = (f.dependencies || []).some(d => typeof d === 'object' && d.state === 'Open');
  const warning = f.blocker || dependency ? 'Blocked' : f.acceptance.state === 'Reopened' ? 'Reopened' : overdue ? 'Overdue' : f.acceptance.state === 'Accepted' && !accepted(f) ? 'Evidence missing' : '';
  if (!warning && complete) return { group: 'done', tag: 'Done ✓', warning: '' };
  const staged = f.releases.find(r => r.environment !== live && released(r));
  let tag = 'Not started';
  if (released(f.releases.find(r => r.environment === live))) tag = 'Live, user check due';
  else if (f.releases.some(r => r.state === 'Released' && !released(r))) tag = 'Availability unconfirmed';
  else if (staged) tag = 'On test version';
  else if (f.build === 'Merged') tag = 'Ready to publish';
  else if (f.build === 'In review') tag = 'Being reviewed';
  else if (f.build === 'Building') tag = 'In progress';
  else if (f.build === 'Not recorded') tag = 'Status not recorded';
  const group = warning || !['In progress', 'Being reviewed', 'Not started', 'Status not recorded'].includes(tag) ? 'action' : tag === 'Status not recorded' ? 'unknown' : tag === 'Not started' ? 'todo' : 'progress';
  return { group, tag, warning };
}
export function gaps(f) {
  return [!f.owner && 'owner', !f.nextAction && 'next action', !f.criteria?.length && 'requirements'].filter(Boolean);
}
export function counts(data) {
  const active = data.features.filter(f => f.scope === 'active' && f.kind === 'implementation');
  return { total: active.length, merged: active.filter(f => f.build === 'Merged').length,
    releases: Object.fromEntries(environments(data.project).map(environment => [environment, {
      released: active.filter(f => f.releases.some(r => r.environment === environment && released(r))).length,
      sourceReported: active.filter(f => f.releases.some(r => r.environment === environment && r.state === 'Released' && !released(r))).length,
      unknown: active.filter(f => !f.releases.some(r => r.environment === environment && r.state !== 'Not recorded')).length
    }])), accepted: active.filter(f => delivery(f, data.project).group === 'done').length,
    acceptanceUnknown: active.filter(f => f.acceptance.state === 'Not recorded').length,
    excluded: data.features.filter(f => f.scope !== 'active').length,
    acceptanceRecords: data.features.filter(f => f.scope === 'active' && f.kind === 'acceptance').length,
    acceptanceChecks: { accepted: data.features.filter(f => f.scope === 'active' && f.kind === 'acceptance' && delivery(f, data.project).group === 'done').length } };
}
