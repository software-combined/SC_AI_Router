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

Repository visibility is private (operator decision 2026-09-07), so the
auto-updater release feed must be an S3 plus CloudFront bucket provisioned
from SC_Infrastructure; Plan 110 uses that feed instead of GitHub Releases.

Licensing groundwork landed 2026-09-11 while the repository stays private:
`LICENSE` carries the verbatim PolyForm Shield License 1.0.0 text with the
Software Combined Required Notice, `COMMERCIAL_LICENSE.md` covers separate
commercial licensing, and `THIRD_PARTY_NOTICES.md` records the MIT-licensed
opencodex material adapted into `ai_router/compaction.py`. Repository
metadata uses `LicenseRef-PolyForm-Shield-1.0.0`, because no SPDX identifier
exists for this licence. Publication stays an owner decision, and the plans
directory records internal infrastructure detail that must be reviewed
before any publication.

Open licensing question, unresolved at 2026-09-11: the wording in
`ai_router/openrouter_base_instructions.txt` closely follows the Codex
desktop application's own agent instructions, and shares several sentences
with the published prompt files in `openai/codex` (Apache-2.0). The Codex
desktop application itself is not open source, so the provenance and
licence of that prompt text is not established. It is shipped as router
data rather than copied client code, but it must be resolved by the owner
before this repository is published.
