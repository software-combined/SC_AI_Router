# Subscription chats after a router restart

An ongoing Codex chat can request a subscription model before its client asks
the restarted router for `/models`. The saved model preferences are not a
complete entitlement list: a model discovered during the previous process
can be missing from them. Rejecting that first request turns a routine update
into Codex's "model is not available on this machine" error.

For a missing native model, the router now asks the native catalogue using
the request's subscription authentication and client version, then routes the
original request only if the returned roster allows it. The same recovery
applies when compaction is the first request. Concurrent resumptions reuse
one result. Existing account, workspace and version boundaries remain in
force; recovery never switches a subscription request to OpenRouter.

An unavailable catalogue returns a retryable service error. Rejected
authentication clears that account's discovery scope. A model absent from a
successful catalogue response remains unavailable, without repeated discovery
for every request.

## Verification

`tests/test_subscription_restart.py` reproduces the original failure and checks
restart, compaction, concurrent resumption, account and client-version
separation, unavailable discovery, authentication rejection, and unchanged
external routing. Its fake upstream never uses the network.

Run the offline regression wrapper from a source checkout:

```bash
python3.14 tools/probe_subscription_restart.py
```

It runs `tests.test_subscription_restart` against synthetic credentials and
mocked upstreams. `--live` is retired and refuses before any client or provider
call. Native authentication is verified through the normal signed-in client
path, never by reading or copying its credential files into a probe home.
This candidate needs fresh real-client compatibility evidence before a
production release; no live or paid checks were performed during preparation.
