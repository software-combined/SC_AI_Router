'use strict';
(() => {
  const problem = message => Object.assign(Error(message), {publicMessage: message});
  const status = document.getElementById('status');
  const labels = {'darwin/arm64': 'macOS · Apple silicon', 'darwin/x86_64': 'macOS · Intel',
    'windows/x86_64': 'Windows · x64', 'linux/x86_64': 'Ubuntu · x64', 'linux/arm64': 'Ubuntu · arm64'};
  const systems = [['darwin/', 'macOS', 'apple'], ['windows/', 'Windows', 'microsoft'], ['linux/', 'Linux', 'linux']];
  async function load() {
    document.getElementById('downloads').hidden = true;
    const response = await fetch('stable.json', {cache: 'no-store', credentials: 'omit', redirect: 'error'});
    if (!response.ok) throw problem('The stable installer is being prepared. Use the other setup options below, or contact Software Combined IT.');
    const doc = await response.json();
    const macOnly = doc.scope === 'macos-arm64';
    const expected = macOnly ? 1 : 5;
    if (!/^\d+(?:\.\d+){2,3}$/.test(doc.version) || doc.channel !== 'stable' ||
        (doc.scope !== undefined && !macOnly) || !Array.isArray(doc.packages) || doc.packages.length !== expected) throw problem('The download list needs attention. Contact Software Combined IT.');
    const packages = document.getElementById('packages');
    const checked = doc.packages.map(item => {
      const url = new URL(item.url, location.origin);
      if (!labels[item.target] || (macOnly && item.target !== 'darwin/arm64') || url.origin !== location.origin || url.search || url.hash ||
          !url.pathname.startsWith('/installers/' + doc.version + '/') || !/^[0-9a-f]{64}$/.test(item.sha256)) throw problem('The download list needs attention. Contact Software Combined IT.');
      return {...item, url: url.href};
    });
    if (new Set(checked.map(item => item.target)).size !== expected) throw problem('The download list is incomplete.');
    packages.replaceChildren(...systems.map(([prefix, title, logo]) => {
      const tile = document.createElement('section'); tile.className = 'system';
      const icon = document.createElement('img'); icon.src = logo + '.svg'; icon.alt = ''; icon.width = 30; icon.height = 30;
      const heading = document.createElement('h3'); heading.textContent = title;
      const rows = checked.filter(item => item.target.startsWith(prefix));
      const links = rows.map(item => {
        const link = document.createElement('a');
        link.className = 'package'; link.href = item.url;
        link.textContent = (prefix === 'linux/' ? 'Ubuntu ' : '') + labels[item.target].split(' · ')[1];
        link.setAttribute('aria-label', 'Download for ' + labels[item.target]);
        return link;
      });
      if (!rows.length) {
        const link = document.createElement('a'); link.className = 'package script';
        link.href = prefix === 'windows/' ? '/install/bootstrap.ps1' : '/install/bootstrap.sh';
        link.textContent = 'Setup script'; link.setAttribute('aria-label', 'Download setup script for ' + title);
        links.push(link);
      }
      tile.replaceChildren(icon, heading, ...links);
      return tile;
    }));
    for (const [id, suffix] of [['checksums', 'SHA256SUMS'], ['signature', 'SHA256SUMS.sig']]) {
      document.getElementById(id).href = '/installers/' + doc.version + '/' + suffix;
    }
    document.getElementById('recommendation').textContent = `Version ${doc.version} · Stable${macOnly ? ' · Apple silicon' : ''}`;
    document.getElementById('downloads').hidden = false;
    status.textContent = '';
  }
  function failure(error) {
    status.textContent = error.publicMessage || 'Downloads need attention. Use the other setup options below, or contact Software Combined IT.';
  }
  load().catch(failure);
})();
