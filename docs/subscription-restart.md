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

Run the real-client check explicitly from the candidate checkout:

```bash
python3.14 tools/probe_subscription_restart.py --live
```

It starts an isolated router and Codex home, completes a synthetic turn,
restarts that router at the same address, and completes a second turn in the
same chat. It leaves the installed router and client configuration alone.
The probe permits at most two native upstream attempts, limits each input to
128 KiB, uses low effort and refuses new upstream attempts after 120 seconds.
Client setup and shutdown take additional time. External routes
are rejected before sending, so its external API spend cap is zero. The native
subscription endpoint does not accept a provider output-token cap.

On 1 October 2026 (AEST), Codex CLI 0.159.2 completed both turns through the
1.0.6 candidate using `gpt-6.1-sol` at low effort. Both responses reported
`gpt-6.1-sol`; there were exactly two upstream attempts and two scoped native
catalogue refreshes. This proves candidate behaviour; the installed release
needs the normal release and compatibility gates before rollout.
