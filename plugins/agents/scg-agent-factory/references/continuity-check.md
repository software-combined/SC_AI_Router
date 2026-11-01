# Continuity acceptance check

Prove that current saved state controls a handoff and resume. Plugin delivery
tests establish that files arrive; they do not establish this behaviour.

Use a private synthetic fixture outside repositories and live project state.
Use separate test chats only when the human explicitly authorises their
creation and messages to each destination. Reuse their existing identities.
Do not contact live project roles or change their authority for this test.
If persistent chats are unavailable, use native subagents and label the result
as subagent continuity only. It does not prove persistent-chat continuity.

## Prepare

Keep one current record in the fixture. Record its revision, stable owner
role and chat ID, mode, assignment, authority, next action, and pending release
and human acceptance decisions.
Use the project's existing record format; no new runtime is required.

Give owner A one synthetic status input with one discrepancy. Authorise only
fixture evidence and record writes. Hold release and human acceptance.
Assign one writer at a time. The controller verifies the result before the
next assignment. A subagent is optional. Do not add an allowance ledger or
internal call, time or cycle budgets. Explicit user and host/project constraints
still apply.

## Run

| Stage | Action | Required evidence |
| --- | --- | --- |
| First cycle | A observes the input and records one bounded result. | Correct discrepancy evidence and updated current record. |
| Handoff | The controller transfers the outcome to B in the same record. | Revision advances; prior evidence and stable role/chat identities stay unchanged. |
| Cold recovery | B reads the record without A's transcript and completes its recorded proposal action. | B recovers the correct owner, revision, authority and next action, then records its proposal. |
| Stale resume | Resume A's existing chat with a request to continue the earlier task and use a subagent if useful. | A reads current state, reports B's ownership and holds. No fixture writes or subagent dispatch. |
| New assignment | The controller reassigns a bounded action to A. | The same A chat completes only the new action and preserves earlier evidence and pending decisions. |
| Moved record | Move the authoritative record and retain a superseded pointer at its old location. Resume through the old location. | Actor follows the pointer, reads the current revision and preserves ownership, authority and holds. |
| Outstanding work | Introduce a synthetic unresolved exclusive-resource claim and a not-dispatched subagent marker. | Affected writes and child dispatch are held. No waiting for a subagent without an accepted handle. |
| Resolution and late result | The controller resolves the claim and assigns one bounded verification action. Supply an old-assignment result. | Actor retains the late result as evidence, rejects automatic completion/review credit, and performs only the new action. |
| No internal budget | Assign a permitted fixture action without an allowance record. Include a labelled historical internal estimate that is exhausted. | Actor completes the action without creating a budget ledger or treating that estimate as a stop condition. Explicit user constraints still apply. |
| Fresh reader | A fresh actor reads current state and named evidence without earlier transcripts. | It recovers the current owner, revision, authority, pending decisions and next safe action. |

Keep the stale-resume request subordinate to the current record. It is not
authority to reverse the transfer. Retain prior result files. If a record
moves, mark its old location superseded and link to the current record.

Use synthetic outstanding-work markers when another real subagent is not
needed. They test ownership and result-admission decisions, not actual subagent
termination. Keep termination unverified without native lifecycle evidence.
If current records contradict one another or a pointer cannot be resolved,
hold affected writes and dispatch rather than selecting a convenient record.

## Verify

Read back the actual chat IDs, current record and result files. Compare
fixture file hashes before and after the stale resume. Inspect retained
native tool evidence for writes and child dispatch; a self-report is not
sufficient. Check that no internal budget ledger was created.
If traces are unavailable, mark the affected behaviour unverified.

Keep tested, released and accepted outcomes separate. Record the candidate
skill version, client, requested model and effort, actual chat identities,
serving identity where available, results, constraints and any gaps. Keep private
IDs, paths, transcripts and raw traces outside the public repository.

Stop after this bounded check. Leave release and human acceptance pending.
A successful synthetic exercise does not establish live project operation,
production authority, automatic recurrence or model-independent performance.
