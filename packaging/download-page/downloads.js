'use strict';
(() => {
  const problem = message => Object.assign(Error(message), {publicMessage: message});
  const status = document.getElementById('status');
  const releases = document.getElementById('channel');
  const labels = {'darwin/arm64': 'macOS · Apple silicon', 'darwin/x86_64': 'macOS · Intel',
    'windows/x86_64': 'Windows · x64', 'linux/x86_64': 'Ubuntu · x64', 'linux/arm64': 'Ubuntu · arm64'};
  const platform = /Win/i.test(navigator.platform) ? 'windows/' : /Mac/i.test(navigator.platform) ? 'darwin/' : /Linux/i.test(navigator.platform) ? 'linux/' : '';
  async function load() {
    document.getElementById('downloads').hidden = true;
    const response = await fetch(releases.value + '.json', {cache: 'no-store', credentials: 'omit', redirect: 'error'});
    if (!response.ok) throw problem('These downloads are not available yet. Choose another release, or contact Software Combined IT.');
    const doc = await response.json();
    const pilot = doc.pilot === true && releases.value === 'beta';
    const expected = pilot ? 1 : 5;
    if (!/^\d+(?:\.\d+){2,3}$/.test(doc.version) || doc.channel !== releases.value || !Array.isArray(doc.packages) || doc.packages.length !== expected) throw problem('The download list needs attention. Contact Software Combined IT.');
    const packages = document.getElementById('packages');
    const checked = doc.packages.map(item => {
      const url = new URL(item.url, location.origin);
      if (!labels[item.target] || (pilot && item.target !== 'darwin/arm64') || url.origin !== location.origin || url.search || url.hash ||
          !url.pathname.startsWith('/installers/' + doc.version + '/') || !/^[0-9a-f]{64}$/.test(item.sha256)) throw problem('The download list needs attention. Contact Software Combined IT.');
      return {...item, url: url.href};
    });
    if (new Set(checked.map(item => item.target)).size !== expected) throw problem('The download list is incomplete.');
    checked.sort((a, b) => Number(b.target.startsWith(platform)) - Number(a.target.startsWith(platform)));
    packages.replaceChildren(...checked.map(item => {
      const link = document.createElement('a');
      link.className = 'package'; link.href = item.url; link.textContent = labels[item.target];
      return link;
    }));
    for (const [id, suffix] of [['checksums', 'SHA256SUMS'], ['signature', 'SHA256SUMS.sig']]) {
      document.getElementById(id).href = '/installers/' + doc.version + '/' + suffix;
    }
    document.getElementById('recommendation').textContent = `Version ${doc.version}. ${platform ? 'Your platform is listed first. Choose your processor below.' : 'Choose your operating system below.'}`;
    document.getElementById('downloads').hidden = false;
    status.textContent = pilot ? 'Mac pilot. Other native packages are still under test. Setup scripts support every platform.' : releases.value === 'beta' ? 'Beta: early access for testing. Your existing channel is preserved.' : 'Stable: recommended for everyday use.';
  }
  function failure(error) {
    status.textContent = error.publicMessage || 'Downloads need attention. Use the setup script above, or contact Software Combined IT.';
  }
  releases.addEventListener('change', () => load().catch(failure));
  load().catch(failure);
})();
