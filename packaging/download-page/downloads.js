'use strict';
(() => {
  const problem = message => Object.assign(Error(message), {publicMessage: message});
  const status = document.getElementById('status');
  const labels = {'darwin/arm64': 'macOS · Apple silicon', 'darwin/x86_64': 'macOS · Intel',
    'windows/x86_64': 'Windows · x64', 'linux/x86_64': 'Ubuntu · x64', 'linux/arm64': 'Ubuntu · arm64'};
  const systems = [['darwin/', 'macOS', 'apple'], ['windows/', 'Windows', 'microsoft'], ['linux/', 'Linux', 'linux']];
  const notReady = 'The installers for this release are not ready yet. Check back soon, or contact Software Combined IT.';
  // Each platform shows its installers, or says plainly that none is ready; scripts stay in the IT section.
  function tiles(linksFor) {
    document.getElementById('packages').replaceChildren(...systems.map(([prefix, title, logo]) => {
      const tile = document.createElement('section'); tile.className = 'system';
      const icon = document.createElement('img'); icon.src = logo + '.svg'; icon.alt = ''; icon.width = 30; icon.height = 30;
      const heading = document.createElement('h3'); heading.textContent = title;
      const links = linksFor(prefix);
      if (!links.length) {
        const note = document.createElement('span'); note.className = 'package script pending';
        note.textContent = 'Not available yet'; links.push(note);
      }
      tile.replaceChildren(icon, heading, ...links);
      return tile;
    }));
  }
  async function load() {
    const response = await fetch('stable.json', {cache: 'no-store', credentials: 'omit', redirect: 'error'});
    if (!response.ok) throw problem(notReady);
    const doc = await response.json();
    const macOnly = doc.scope === 'macos-arm64';
    const expected = macOnly ? 1 : 5;
    if (!/^\d+(?:\.\d+){2,3}$/.test(doc.version) || doc.channel !== 'stable' ||
        (doc.scope !== undefined && !macOnly) || !Array.isArray(doc.packages) || doc.packages.length !== expected) throw problem('The download list needs attention. Contact Software Combined IT.');
    const current = await fetch('/stable/latest.json', {cache: 'no-store', credentials: 'omit', redirect: 'error'});
    const latest = current.ok ? await current.json() : null;
    if (!latest || latest.version !== doc.version || latest.channel !== 'stable') throw problem(notReady);
    const checked = doc.packages.map(item => {
      const url = new URL(item.url, location.origin);
      if (!labels[item.target] || (macOnly && item.target !== 'darwin/arm64') || url.origin !== location.origin || url.search || url.hash ||
          !url.pathname.startsWith('/installers/' + doc.version + '/') || !/^[0-9a-f]{64}$/.test(item.sha256)) throw problem('The download list needs attention. Contact Software Combined IT.');
      return {...item, url: url.href};
    });
    if (new Set(checked.map(item => item.target)).size !== expected) throw problem('The download list is incomplete.');
    tiles(prefix => checked.filter(item => item.target.startsWith(prefix)).map(item => {
      const link = document.createElement('a');
      link.className = 'package'; link.href = item.url;
      link.textContent = (prefix === 'linux/' ? 'Ubuntu ' : '') + labels[item.target].split(' · ')[1];
      link.setAttribute('aria-label', 'Download for ' + labels[item.target]);
      return link;
    }));
    for (const [id, suffix] of [['checksums', 'SHA256SUMS'], ['signature', 'SHA256SUMS.sig']]) {
      document.getElementById(id).href = '/installers/' + doc.version + '/' + suffix;
    }
    document.getElementById('recommendation').textContent = `Version ${doc.version} · Stable${macOnly ? ' · Apple silicon' : ''}`;
    document.getElementById('downloads').hidden = false;
    document.getElementById('verification').hidden = false;
    status.textContent = '';
  }
  function failure(error) {
    tiles(() => []);
    status.textContent = error.publicMessage || notReady;
  }
  load().catch(failure);
})();
