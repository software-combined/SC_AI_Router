/* Microsoft PKCE uses one public client. Tokens never enter persistent storage. */
'use strict';
window.scgSignin = (() => {
  const problem = message => Object.assign(Error(message), {publicMessage: message});
  const slot = 'scg-router-pkce';
  const callback = new URL('./', location.href).href;
  let config;
  const encoded = bytes => btoa(String.fromCharCode(...bytes)).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '');
  async function settings() {
    if (config) return config;
    const response = await fetch('config-public', {cache: 'no-store'});
    if (!response.ok) throw problem('Download sign-in is not available yet. Contact Software Combined IT.');
    const value = await response.json();
    const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
    if (value.version !== 1 || value.distribution_origin !== location.origin ||
        !uuid.test(value.tenant_id) || !uuid.test(value.client_id) ||
        !/^api:\/\/[0-9a-f-]{36}\/Download\.Read$/.test(value.scope)) throw problem('Download sign-in needs attention. Contact Software Combined IT.');
    config = value;
    return value;
  }
  async function start() {
    const value = await settings();
    const verifier = encoded(crypto.getRandomValues(new Uint8Array(32)));
    const state = encoded(crypto.getRandomValues(new Uint8Array(32)));
    const challenge = encoded(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))));
    sessionStorage.setItem(slot, JSON.stringify({verifier, state, created: Date.now()}));
    const url = new URL(`https://login.microsoftonline.com/${value.tenant_id}/oauth2/v2.0/authorize`);
    url.search = new URLSearchParams({client_id: value.client_id, response_type: 'code', redirect_uri: callback,
      response_mode: 'query', scope: value.scope, state, code_challenge: challenge, code_challenge_method: 'S256'});
    location.assign(url);
  }
  async function finish() {
    const query = new URLSearchParams(location.search);
    if (!query.has('code') && !query.has('error')) return;
    history.replaceState(null, '', callback);
    const saved = JSON.parse(sessionStorage.getItem(slot) || 'null');
    sessionStorage.removeItem(slot);
    if (!saved || saved.state !== query.get('state') || Date.now() - saved.created > 600000 || query.has('error')) throw problem('Sign-in did not finish. Choose Sign in to try again.');
    const value = await settings();
    const response = await fetch(`https://login.microsoftonline.com/${value.tenant_id}/oauth2/v2.0/token`, {
      method: 'POST', redirect: 'error', headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: new URLSearchParams({client_id: value.client_id, grant_type: 'authorization_code', code: query.get('code'),
        code_verifier: saved.verifier, redirect_uri: callback, scope: value.scope})});
    if (!response.ok) throw problem('Sign-in did not finish. Choose Sign in to try again.');
    const token = await response.json();
    if (typeof token.access_token !== 'string' || !/^[A-Za-z0-9._~-]{1,32768}$/.test(token.access_token)) throw problem('Sign-in did not finish.');
    const access = await fetch('/download-access', {method: 'POST', redirect: 'error', credentials: 'same-origin',
      headers: {Authorization: 'Bearer ' + token.access_token, 'Content-Type': 'application/json'}, body: '{}'});
    if (!access.ok) throw problem('This account does not have download access. Contact Software Combined IT.');
  }
  return {start, finish};
})();
