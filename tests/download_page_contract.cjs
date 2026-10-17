'use strict';
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto').webcrypto;
const root = path.join(__dirname, '../packaging/download-page');
const origin = 'https://dist.softwarecombined.com';
const config = {version: 1, distribution_origin: origin,
  tenant_id: '11111111-1111-4111-8111-111111111111', client_id: '22222222-2222-4222-8222-222222222222',
  scope: 'api://33333333-3333-4333-8333-333333333333/Download.Read'};
const manifest = () => ({version: '1.2.3.4', channel: 'stable', packages:
  ['darwin/arm64', 'darwin/x86_64', 'windows/x86_64', 'linux/arm64', 'linux/x86_64'].map((target, i) => ({
    target, url: origin + '/installers/1.2.3.4/' + i + '.bin', sha256: 'a'.repeat(64)}))});

function browser(fetch) {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, {value: 'stable', hidden: false,
      listeners: {}, addEventListener(name, callback) {this.listeners[name] = callback;},
      replaceChildren(...children) {this.children = children;}});
    return elements.get(id);
  }
  const storage = new Map();
  const context = vm.createContext({URL, URLSearchParams, TextEncoder, crypto, btoa, fetch,
    sessionStorage: {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key)},
    location: {origin, href: origin + '/install/', search: '', assign(url) {this.redirect = url;}},
    history: {replaceState() {}}, navigator: {platform: 'Linux x86_64'}, window: {},
    document: {getElementById: element, createElement: () => ({})}});
  return {context, element, storage};
}
function execute(browser, name) {vm.runInContext(fs.readFileSync(path.join(root, name), 'utf8'), browser.context);}
const settled = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  const template = fs.readFileSync(path.join(__dirname, '../infra/feed.yaml'), 'utf8');
  const guard = template.split('      FunctionCode: !Sub\n        - |\n')[1].split('        - StaffDownloads:')[0];
  for (const configured of [true, false]) {
    const edge = vm.createContext({});
    vm.runInContext(guard.replace('${StaffDownloads}', String(configured)), edge);
    for (const uri of ['/installers/1.2.0/package.dmg', '/install/beta.json']) {
      assert.equal(edge.handler({request: {uri}}).statusCode, configured ? undefined : 403);
      const behavior = template.split('          - PathPattern: ' + (uri.startsWith('/installers/') ? '/installers/*' : '/install/*.json'))[1].split('\n\n')[0].split('          - PathPattern:')[0];
      assert.match(behavior, /EventType: viewer-request/);
      assert.match(behavior, /InstallPageRouting.FunctionARN/);
    }
    assert.equal(edge.handler({request: {uri: '/install/'}}).uri, '/install/index.html');
  }
  for (const wrongOrigin of [false, true]) {
    const data = manifest();
    if (wrongOrigin) data.packages[0].url = 'https://other.example/private.exe';
    const app = browser(async () => ({ok: true, status: 200, json: async () => data}));
    app.context.window.scgSignin = {finish: async () => {}};
    execute(app, 'downloads.js');
    await settled();
    if (wrongOrigin) {
      assert.match(app.element('status').textContent, /needs attention/);
      assert.equal(app.element('packages').children, undefined);
    } else {
      assert.equal(app.element('packages').children.length, 5);
      assert.equal(app.element('packages').children[0].textContent, 'Ubuntu · arm64');
      assert.equal(app.element('downloads').hidden, false);
    }
  }
  let calls = 0;
  let available = true;
  const changing = browser(async () => ({ok: available, status: available ? 200 : 404, json: async () => manifest()}));
  changing.context.window.scgSignin = {finish: async () => {}};
  execute(changing, 'downloads.js');
  await settled();
  assert.equal(changing.element('downloads').hidden, false);
  available = false;
  changing.element('channel').value = 'beta';
  changing.element('channel').listeners.change();
  await settled();
  assert.equal(changing.element('downloads').hidden, true, 'a failed channel switch must hide the previous downloads');
  for (const target of ['darwin/arm64', 'windows/x86_64']) {
    const data = manifest();
    data.pilot = true; data.channel = 'beta';
    data.packages = data.packages.filter(item => item.target === target);
    const pilot = browser(async () => ({ok: true, status: 200, json: async () => data}));
    pilot.element('channel').value = 'beta';
    pilot.context.window.scgSignin = {finish: async () => {}};
    execute(pilot, 'downloads.js');
    await settled();
    if (target === 'darwin/arm64') {
      assert.equal(pilot.element('packages').children.length, 1);
      assert.match(pilot.element('status').textContent, /Private Mac pilot/);
    } else assert.match(pilot.element('status').textContent, /needs attention/);
  }
  const redacted = browser(async () => {throw Error('synthetic private token');});
  redacted.context.window.scgSignin = {finish: async () => {throw Error('synthetic private token');}};
  execute(redacted, 'downloads.js');
  await settled();
  assert.doesNotMatch(redacted.element('status').textContent, /private token/);
  assert.match(redacted.element('status').textContent, /Downloads need attention/);
  const app = browser(async () => {calls++; return {ok: true, json: async () => config};});
  execute(app, 'signin.js');
  await app.context.window.scgSignin.start();
  const authorize = app.context.location.redirect;
  assert.equal(authorize.origin, 'https://login.microsoftonline.com');
  assert.equal(authorize.searchParams.get('code_challenge_method'), 'S256');
  assert.equal(authorize.searchParams.get('redirect_uri'), origin + '/install/');
  app.context.location.search = '?code=synthetic&state=wrong';
  await assert.rejects(app.context.window.scgSignin.finish(), /did not finish/);
  assert.equal(calls, 1, 'state rejection must precede token or cookie exchange');
  assert.equal(app.storage.size, 0, 'a callback can be consumed once only');
  process.stdout.write('Browser contracts passed\n');
})().catch(error => {process.stderr.write(error.stack + '\n'); process.exitCode = 1;});
