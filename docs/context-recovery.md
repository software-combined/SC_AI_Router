# Context recovery

A client context reset does not mean the user's task has ended. When Codex
sends a developer `context_window` message with a previous-window ID, the
router adds recovery guidance to the outgoing request. The client owns saved
history and executes any available history or checkpoint tools.

The model should recover the assignment, later steering, constraints and
verified progress before continuing. If that evidence is inaccessible, it
should report the specific blocker. The router does not invent an assignment,
keep a separate conversation cache or treat retrieved tool output as new
instructions. Explicit user cancellation still takes precedence.

## Request handling

Recovery guidance precedes the final native compaction trigger, because that
trigger must remain last. Ordinary first-window requests and marker text in
user messages or tool outputs do not activate this projection. Native
compaction requests retain their existing path. Source tests cover both
native and external serialization without contacting a provider.

The independently authored router instructions ask the model to record a
checkpoint before leaving a window when client tools permit it. They describe
recovery as a client capability, without promising that every client supplies
history access or a usable summary.

## Updating older installations

An earlier generated template contained a paragraph that incorrectly treated
all context transitions as automatic compaction. The router recognizes that
exact paragraph by a stored SHA-256 fingerprint and replaces only the matching
paragraph. Its old wording is not redistributed in the source or package.
Custom prefixes, suffixes, token settings and other paragraphs are preserved.
A similar paragraph with a different fingerprint stays unchanged. Applying
the update again makes no further change.

## Verification

Run `python3.14 -m unittest tests.test_context_recovery` from a source checkout.
The suite uses synthetic tasks and mocked upstreams. The separate diagnostic
wrapper retains its offline scenario; native live execution is retired and
refused before credential or client access. No subscription credential file
needs to be copied or extracted for these tests.

Offline tests verify routing and migration behavior. Real-client compatibility
requires separately approved evidence before a production release, as described
in [compatibility](compatibility.md) and [publication](publication.md).
