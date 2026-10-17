'use strict';
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const root = path.join(__dirname, '../packaging/download-page');
const origin = 'https://dist.softwarecombined.com';
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
  const context = vm.createContext({URL, fetch, location: {origin},
    navigator: {platform: 'Linux x86_64'},
    document: {getElementById: element, createElement: () => ({})}});
  return {context, element};
}
function execute(browser, name) {vm.runInContext(fs.readFileSync(path.join(root, name), 'utf8'), browser.context);}
const settled = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  const template = fs.readFileSync(path.join(__dirname, '../infra/feed.yaml'), 'utf8');
  const guard = template.split('      FunctionCode: |\n')[1].split('\n  InstallPageHeaders:')[0];
  const edge = vm.createContext({});
  vm.runInContext(guard, edge);
  for (const uri of ['/installers/1.2.0/package.dmg', '/install/beta.json']) {
    assert.equal(edge.handler({request: {uri}}).uri, uri);
    const behavior = template.split('          - PathPattern: ' + (uri.startsWith('/installers/') ? '/installers/*' : '/install/*.json'))[1].split('\n\n')[0].split('          - PathPattern:')[0];
    assert.match(behavior, /EventType: viewer-request/);
    assert.match(behavior, /InstallPageRouting.FunctionARN/);
  }
  assert.equal(edge.handler({request: {uri: '/install/'}}).uri, '/install/index.html');
  for (const wrongOrigin of [false, true]) {
    const data = manifest();
    if (wrongOrigin) data.packages[0].url = 'https://other.example/private.exe';
    const app = browser(async () => ({ok: true, status: 200, json: async () => data}));
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
  let available = true;
  const changing = browser(async () => ({ok: available, status: available ? 200 : 404, json: async () => manifest()}));
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
    execute(pilot, 'downloads.js');
    await settled();
    if (target === 'darwin/arm64') {
      assert.equal(pilot.element('packages').children.length, 1);
      assert.match(pilot.element('status').textContent, /Mac pilot/);
    } else assert.match(pilot.element('status').textContent, /needs attention/);
  }
  const redacted = browser(async () => {throw Error('synthetic private token');});
  execute(redacted, 'downloads.js');
  await settled();
  assert.doesNotMatch(redacted.element('status').textContent, /private token/);
  assert.match(redacted.element('status').textContent, /Downloads need attention/);
  const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
  assert.doesNotMatch(html, /signin.js|id="signin"|Sign in with Microsoft/);
  assert.match(html, /bootstrap.ps1/);
  assert.match(html, /bootstrap.sh/);
  process.stdout.write('Browser contracts passed\n');
})().catch(error => {process.stderr.write(error.stack + '\n'); process.exitCode = 1;});
