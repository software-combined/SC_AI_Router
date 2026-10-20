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
  const create = () => ({value: 'stable', hidden: false,
      listeners: {}, addEventListener(name, callback) {this.listeners[name] = callback;},
      setAttribute(name, value) {this[name] = value;},
      replaceChildren(...children) {this.children = children;}});
  function element(id) {
    if (!elements.has(id)) elements.set(id, create());
    return elements.get(id);
  }
  const context = vm.createContext({URL, fetch, location: {origin},
    navigator: {platform: 'Linux x86_64'},
    document: {getElementById: element, createElement: create}});
  return {context, element};
}
function execute(browser, name) {vm.runInContext(fs.readFileSync(path.join(root, name), 'utf8'), browser.context);}
const settled = () => new Promise(resolve => setImmediate(resolve));
// Without a published installer a tile says so; it never offers a script as the ordinary path.
const notReady = app => assert.deepEqual(Array.from(app.element('packages').children,
  tile => [tile.children[2].textContent, tile.children[2].href]), Array(3).fill(['Not available yet', undefined]));

(async () => {
  const template = fs.readFileSync(path.join(__dirname, '../infra/feed.yaml'), 'utf8').replace(/\r\n/g, '\n');
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
    const app = browser(async (url, options) => {
      assert.ok(['stable.json', '/stable/latest.json'].includes(url));
      assert.equal(options.credentials, 'omit');
      return {ok: true, status: 200, json: async () => data};
    });
    execute(app, 'downloads.js');
    await settled();
    if (wrongOrigin) {
      assert.match(app.element('status').textContent, /needs attention/);
      notReady(app);
    } else {
      const tiles = app.element('packages').children;
      assert.equal(tiles.length, 3);
      assert.deepEqual(Array.from(tiles, tile => tile.children[0].src), ['apple.svg', 'microsoft.svg', 'linux.svg']);
      assert.equal(tiles.flatMap(tile => tile.children.slice(2)).length, 5);
      assert.equal(tiles[2].children[2]['aria-label'], 'Download for Ubuntu · arm64');
      assert.equal(app.element('downloads').hidden, false);
    }
  }
  const unavailable = browser(async () => ({ok: false, status: 404}));
  execute(unavailable, 'downloads.js');
  await settled();
  assert.equal(unavailable.element('downloads').hidden, false);
  assert.match(unavailable.element('status').textContent, /not ready yet/);
  notReady(unavailable);
  const stale = browser(async url => ({ok: true, status: 200,
    json: async () => url === 'stable.json' ? manifest() : {version: '1.2.3.5', channel: 'stable'}}));
  execute(stale, 'downloads.js');
  await settled();
  notReady(stale);
  assert.match(stale.element('status').textContent, /not ready yet/);
  for (const target of ['darwin/arm64', 'windows/x86_64']) {
    const data = manifest();
    data.scope = 'macos-arm64';
    data.packages = data.packages.filter(item => item.target === target);
    const scoped = browser(async () => ({ok: true, status: 200, json: async () => data}));
    execute(scoped, 'downloads.js');
    await settled();
    if (target === 'darwin/arm64') {
      const tiles = scoped.element('packages').children;
      assert.equal(tiles.length, 3);
      assert.match(tiles[0].children[2].href, /\/installers\//);
      for (const tile of tiles.slice(1)) {
        assert.equal(tile.children[2].textContent, 'Not available yet');
        assert.equal(tile.children[2].href, undefined);
      }
      assert.match(scoped.element('recommendation').textContent, /Stable/);
    } else assert.match(scoped.element('status').textContent, /needs attention/);
  }
  const beta = manifest(); beta.channel = 'beta';
  const rejected = browser(async () => ({ok: true, json: async () => beta}));
  execute(rejected, 'downloads.js'); await settled();
  assert.equal(rejected.element('downloads').hidden, false);
  assert.match(rejected.element('status').textContent, /needs attention/);
  const redacted = browser(async () => {throw Error('synthetic private token');});
  execute(redacted, 'downloads.js');
  await settled();
  assert.doesNotMatch(redacted.element('status').textContent, /private token/);
  assert.match(redacted.element('status').textContent, /not ready yet/);
  const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
  assert.doesNotMatch(html, /signin.js|id="signin"|Sign in with Microsoft/);
  assert.doesNotMatch(html, /id="channel"|Beta —|early access/);
  assert.match(html, /Advanced: setup scripts for IT[^]*bootstrap.ps1[^]*bootstrap.sh/);
  assert.doesNotMatch(html.split('<div id="packages">')[1].split('</div>')[0], /bootstrap/);
  assert.doesNotMatch(html, /id="downloads" hidden/);
  assert.equal((html.match(/class="system"/g) || []).length, 3);
  process.stdout.write('Browser contracts passed\n');
})().catch(error => {process.stderr.write(error.stack + '\n'); process.exitCode = 1;});
