# Provenance

Imported from `software-combined/SC_Infrastructure` path
`domains/ai-platform/codex-model-router` at commit `8d715eb4` on 2026-09-07
(prior adapter commits `4c8e98e3`, `d1386bc0`, `749a6b8d`, `67486f14`,
`6053502c`; sixteen OpenRouter models). Earlier history lived only in the
deployed directory `~/.codex/mixed-model-router` and is not recoverable.
Compatibility release 2 was verified against `codex-cli 0.153.4` on
2026-09-07.

An earlier migration commit (`3481b8e`) created this repository from the
same source at `749a6b8d`; this layout supersedes it with the current
source plus package structure, governance and CI.

The repository was created private on 2026-09-07, so the auto-updater's
release feed is an S3 plus CloudFront distribution (`infra/`) rather than
GitHub Releases; that feed is now public and token-free (see
`CHANGELOG.md`).

Licensing: the repository converted to Apache-2.0 only on 2026-09-11.
`LICENSE` carries the verbatim Apache License 2.0 text, `NOTICE` carries the
Software Combined copyright, `COMMERCIAL_LICENSE.md` was removed, and
repository metadata uses the SPDX identifier `Apache-2.0`. The MIT-licensed
opencodex material adapted into `ai_router/compaction.py` stays recorded in
`THIRD_PARTY_NOTICES.md`. Publication stays an owner decision, and the plans
directory records internal infrastructure detail that must be reviewed
before any publication.

Open licensing question, unresolved at 2026-09-11: the wording in
`ai_router/openrouter_base_instructions.txt` closely follows the Codex
desktop application's own agent instructions, and shares several sentences
with the published prompt files in `openai/codex` (Apache-2.0). The Codex
desktop application itself is not open source, so the provenance and
licence of that prompt text is not established. It is shipped as router
data rather than copied client code, but it must be resolved by the owner
before this repository is published or a release is distributed.
