# Plan 048 review and handoff status

Updated 2026-09-08. Planning only: no managed key service, cloud resources,
keys, invitations, runtime configuration or release was deployed by this task.

- Deliverable: `048-router-managed-key-provisioning.md`, indexed in README.
  Implementation remains TODO. Business and Enterprise are separate required
  live acceptance gates; neither is claimed verified.
- Design analysis: Muse Contributor/xhigh and owner-authorised Kimi K3/max.
  Kimi Contributor was unavailable. Accepted Kimi corrections are recorded below.
- Required formal review used current policy: `meta/muse-spark-1.3-contributor`
  at `xhigh` for Pass 1, correctness, quality and adversarial. Returned model
  and effort were not echoed; all recorded as `unverified`.
- Pass 1: verified no-op. All three independent lanes returned ALL_CLEAR on
  staged tree `18db0cb43159af747619967889a8778bb191df3e`.
  Main checked actual brief reads, ponytail-before-staged order and complete
  index-file coverage. Quality completed its missing supporting-source reads
  before its final ALL_CLEAR. No material plan finding was accepted.
- Earlier inline delegation briefs were not delivered reliably. Shared
  temporary brief files, explicitly named in subagent task labels, succeeded
  through the same subagent tools. Earlier unsupported coverage claims were
  rejected; a reviewer's unrelated test-split worktree was safely cleaned up.
  The shared review skill now documents this transport fallback.
- Scope is one coherent cross-repository plan, status record and index entry,
  below the 800-line limit. No product behavior/version change in this commit.
- Original source anchors are historical snapshots at `1979e7f`; formal review
  and 285 passing tests used `07e1bab`. Integration advanced to `1fc8ea2`,
  preserving the other task's updated index statuses and manual `--setup`
  key window. Its temporary keyless startup exception does not implement managed
  provisioning or persistent managed-credential readiness. Reconcile source
  drift before implementation as the plan requires.
- Integration delta: plan body unchanged; README conflict resolved by retaining
  main's updated rows plus the reviewed 048 row. Correctness and adversarial
  returned ALL_CLEAR on tree `14a1535ebf612bfd9898c72560bda42daaa05130`;
  quality inherited because its own reviewed index edits and planned ownership/
  architecture are unchanged. Final combined decision: ALL_CLEAR.
- Integrated-base verification: 300 tests passed on `1fc8ea2`; compileall and
  source limits passed (55 files, zero failures). Final delta from reviewed
  tree `14a1535e` changes only this factual review record; no plan contract,
  implementation, authority or verification requirement changed.
- Main then advanced to `19f3f11` with catalogue/global-guidance changes. The
  reviewed plan files were preserved byte-for-byte when placed on that base;
  no managed-key contract changed, so the review conclusions are inherited.
  Final-base verification: 312 tests passed, compileall passed, source limits
  passed (58 files, zero failures). Only this factual record changed afterward.
- Review worktree: `/Users/cyrilallart/Documents/Github/.worktrees/codex-router-provisioning-plan`;
  branch `codex/router-provisioning-plan`; owner this planning task `/root`;
  integration target local `main`. Git history owns the final commit identity.
  Cleanup follows verified integration. No push: main/beta publish releases.
- Final status-only review corrections are mechanical and require a fresh
  secret scan before exact-tree approval; no plan contract changes are made.
  The hook receipt records the approved final tree.

## Kimi findings adjudicated

Main checked the cited runtime/provider/installer code and tests before editing.
This was a design analysis, not a substitute for the exact staged-tree gate.

| Finding | Decision and final plan treatment |
|---|---|
| Organisation sign-in could be read as a new auth integration | Clarified existing subscription mode plus native ChatGPT OAuth. Rejected the stronger claim that current acceptance was untestable. |
| Unspecified coupling between OpenRouter grant and OpenAI workspace | Made independence explicit; any required workspace pin belongs to supported OpenAI admin policy, not inferred email matching. |
| Three model lists lack a reconciliation owner | Added workspace/provider authority, approved local subset, pilot-operator evidence and router-maintainer ownership. |
| Policy retrieval endpoint not identified | Require actual host/path and direct-versus-router routing evidence; existing native paths do not prove coverage. |
| Personal subscription-only startup also fails without an OpenRouter key | Pre-existing and outside scope; retained personal behaviour and managed-mode-only readiness separation. |
| Missing legacy default for credential mode | Added absent-means-personal, explicit value validation, atomic enrolment and migration tests. |
| Comparison code might be mistaken for device/installer attestation | Clarified transaction-only meaning. Corrected the review's implication that hashing protects against a malicious installer owning the secret; publisher trust remains essential. |
| Simultaneous month-end expiry | Added bounded jitter/backoff, operation deduplication, renewal-pending response, fleet/expiry tests and explicit continuity limits. |
| Duplicate Python bootstrap investigation | Reuse and revalidate Plan 047 Work Order E's existing approach. |

The Kimi prose clarifications were checked with `git diff --check` and
`git diff --cached --check` against the historical 258-test baseline. The later
commit attempt reran all 285 tests on `07e1bab`, as recorded above. No live
capability or implementation success is inferred from either analysis.
