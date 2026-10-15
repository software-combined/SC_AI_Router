# Bootstrap runtime licences

On 14 October 2026, all five exact install-only CPython 3.14.7 archives in
`packaging/runtime.lock` were downloaded from their pinned upstream URLs.
Their byte counts and SHA-256 hashes matched. Each contained the required
interpreter and licence member. Every regular install-only file was also
compared with the corresponding full upstream archive; all bytes matched.

| Platform | Install-only archive bytes | Regular files matched |
|---|---:|---:|
| macOS arm64 | 26,671,536 | 1,689 |
| macOS x86_64 | 26,723,319 | 1,686 |
| Linux x86_64 | 123,986,414 | 3,521 |
| Linux arm64 | 95,970,257 | 3,521 |
| Windows x86_64 | 49,587,410 | 2,132 |

[The install-only inventory](../packaging/runtime-notices.json) records the
42 licence/notice files retained by each archive. Those files mainly cover
Python and pip's bundled libraries. They do not include the native dependency
notice directory from the full build. Preserve all original notices.

[The native inventory](../packaging/runtime-components.json) records full
archive hashes, platform linking metadata, SPDX identifiers, exact upstream
source locations and notice sections. The application bundle now includes
[21 native notice sections](../packaging/RUNTIME-NOTICES.txt). Their source
texts are unchanged apart from normalized line endings. Windows and Unix
variants contain identical text after that normalization.

These cover Python/CNRI, bzip2, libffi, ncurses, mpdecimal, Expat, OpenSSL,
liblzma, SQLite, Tcl/Tk/Tix, libuuid, libedit, X11 libraries, zlib and Berkeley
DB. Full upstream metadata references missing Zstandard and zlib-ng notice
files; the candidate recovers them from the exact checksum-pinned source
archives in that build's download catalogue. Zstandard uses its BSD-3-Clause
option. Where metadata names alternative OpenSSL libraries, both notices
are retained. No licence is changed to Apache-2.0 by this inventory.

## Source availability

The Linux `_dbm` extension links Berkeley DB 6.0.19 under the Sleepycat
licence. The exact source archive was downloaded and its pinned hash verified;
its licence confirms the source-availability condition recorded in the build.
The inventory supplies the Berkeley DB, CPython and build-source URLs and
hashes. A distributor must also provide complete application source with the
runtime distribution. Publish the reviewed `public-source.tar.gz` companion
beside the application bundle, and retain those source locations and notices.
Do not promote a binary distribution while its source companion is private
or unavailable. Existing mirrors and downloads need a separate approved
distribution change; local preparation does not repair them.

## Windows runtime condition

The Windows archive contains `vcruntime140.dll` and `vcruntime140_1.dll`, both
version 14.44.35211.0. Microsoft's [runtime redistribution guide](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files)
and [2022 distributable list](https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution)
make redistribution subject to applicable terms. The [Community licence](https://visualstudio.microsoft.com/license-terms/vs2022-ga-community/)
includes organizational open-source eligibility and downstream distributor
provisions; a newly purchased Visual Studio licence is not automatically
required. Identify the accepted entitlement/terms or upstream permission chain
covering these unmodified DLLs. That evidence has not yet been supplied.
The Python-free application bundle contains neither DLL. Windows runtime
mirroring/redistribution remains blocked until the owner supplies that
evidence or approves a delivery path that does not redistribute those DLLs.

The inventory and supplied notices close the technical inspection gap. They
do not assert universal legal clearance, ownership of earlier removed text,
or permission to change already published distributions.
