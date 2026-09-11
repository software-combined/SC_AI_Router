# Third-Party Notices

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

## Client wire formats

The router speaks the wire formats of Codex, Claude Code and OpenRouter.
Protocol facts, identifiers and request shapes in this repository were
established by reading those clients and their public documentation; no
client source code is copied into this repository. See
`docs/PROVENANCE.md` and `docs/compatibility.md` for the versions those
observations were made against.
