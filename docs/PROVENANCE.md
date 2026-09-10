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
