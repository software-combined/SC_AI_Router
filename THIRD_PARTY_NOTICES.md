# Third-Party Notices

The Linux desktop menu uses pinned `ksni 0.3.6` (Unlicense) and its locked Rust
dependencies. Complete upstream licence texts and copyright notices ship in
[the menu notices](packaging/native/menu/linux/NOTICES.txt).
Regenerate them with `python3.14 tools/collect_native_licenses.py`.
Rust 1.90.0 uses source revision `1159e78c4747b02ef996e55082b704c09b970588`.
Its standard-library notices are retained under
[`packaging/native/menu/linux/rust/`](packaging/native/menu/linux/rust/).

This project is distributed under the [Apache License 2.0](LICENSE). It also
contains material from the projects below, which remains under those
projects' own terms. Nothing in this file grants rights under the Apache
License, or restricts the rights those projects' licences already grant you.

## opencodex

`ai_router/compaction.py` is adapted from `src/responses/compaction.ts` in
[lidge-jun/opencodex](https://github.com/lidge-jun/opencodex) at commit
`f7f890f`. The remote-compaction envelope prefix (`ocx1:`), the
`compaction_trigger` request type, the checkpoint prompt and the summary
preface text come from that source.

MIT License

Copyright (c) 2026 opencodex contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Ponytail

`plugins/development/scg-ponytail/skills/ponytail/` adapts Ponytail 4.10.0 by
[Dietrich Gebert](https://github.com/DietrichGebert/ponytail). It remains under
MIT, with the original copyright and full permission notice preserved in
[its licence](plugins/development/scg-ponytail/skills/ponytail/LICENSE).

## Brand fonts

The sign-in confirmation bundles the Hub's Inter 4.001 and Space Grotesk 2.000
font subsets. Both retain the SIL Open Font License 1.1. The copyright notices
and full licences ship with [Inter](packaging/assets/inter-OFL.txt) and
[Space Grotesk](packaging/assets/space-grotesk-OFL.txt).

## Client wire formats

The router speaks the wire formats of Codex, Claude Code and OpenRouter.
Protocol facts, identifiers and request shapes in this repository were
established by reading those clients and their public documentation; no
client source code is copied into this repository. See
`docs/PROVENANCE.md` and `docs/compatibility.md` for the versions those
observations were made against.

## Router instruction assets

The current router instruction assets are independently authored
Software Combined material under the repository licence. They replace the
previous desktop-derived prompt. See [provenance](docs/PROVENANCE.md) for the
scope of that replacement and the separate decision on older distributions.

## CPython bootstrap runtimes

The router itself declares no third-party Python runtime dependencies.
Bootstrap installations download separate pinned CPython distributions from
[python-build-standalone](https://github.com/astral-sh/python-build-standalone).
These runtimes and their bundled components keep their upstream licences;
the router's Apache-2.0 licence does not relicense them. `packaging/runtime.lock`
records each archive and its interpreter licence path. Preserve all upstream
licence files when mirroring or installing those archives. The candidate
verifies all five exact archives and includes additional native notices in
[RUNTIME-NOTICES.txt](packaging/RUNTIME-NOTICES.txt), with component licences,
source locations and hashes in [the native inventory](packaging/runtime-components.json).
See [runtime licences](docs/runtime-licenses.md) for the Linux source-companion
requirement and the Windows Visual C++ runtime basis.
The application bundle does not contain runtime binaries.
