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

## Windows runtime basis

The Windows archive contains `vcruntime140.dll` and `vcruntime140_1.dll`, both
version 14.44.35211.0. The Python-free application bundle contains neither DLL;
the setup script, its runtime mirror and the Windows installer carry them
inside the pinned runtime.

On 20 October 2026 the repository owner accepted this basis for redistributing
them, without a purchased Visual Studio licence:

- SC AI Router is published as open source under Apache-2.0, an Open Source
  Initiative (OSI) approved licence.
- Clause 1.b.i of the [Visual Studio Community 2022 licence](https://visualstudio.microsoft.com/license-terms/vs2022-ga-community/)
  lets any number of an organisation's users develop and test applications
  released under OSI-approved licences.
- Microsoft's [2022 distributable list](https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution)
  lets a validly licensed Community 2022 user copy and distribute with a program
  the unmodified files in `VC\redist`, subject to the licence terms.

Section 4 of that licence, read on 20 October 2026, sets the distribution
conditions. For any distributed file, the licensee must add significant primary
functionality to it in its application (the router is that application), and
must require distributors and external end users to agree to terms that protect
the file at least as much as the licence. It may not distribute preview or beta
components, use Microsoft's trademarks in an application's name, or bring the
files under a licence that requires source disclosure.

Both Windows install paths ask for that agreement before the files arrive. The
installer shows [windows-runtime-terms.txt](../packaging/native/windows-runtime-terms.txt)
as a page that must be accepted. `bootstrap.ps1` prints the same terms and
downloads the runtime only after the user types ACCEPT, or when IT runs it with
`-AcceptMicrosoftRuntimeTerms`. A silent installer run (`/SILENT` or
`/VERYSILENT`) skips the page, so IT that deploys silently accepts on users'
behalf, as with that switch. Installations that received the runtime before
this step did not see the terms.

The repository owner approved the terms text as written on 20 October 2026.
Every stable release publishes `bootstrap.ps1`, and every release ships the
notice, so any later change to the terms needs the owner's approval before it
merges.

Keep these conditions while relying on it: ship the DLLs unmodified, exactly as
in the checksum-pinned upstream archive; ship them only inside the router's
runtime; keep the end-user terms on both install paths; keep the router under
an OSI-approved licence; and keep the notice in
[RUNTIME-NOTICES.txt](../packaging/RUNTIME-NOTICES.txt) that they remain
Microsoft's software under Microsoft's terms.

This is the owner's acceptance, not legal review. If the router stops being
OSI-licensed, or legal advice differs, stop
redistributing the DLLs: ship the runtime without them and have setup install
Microsoft's Visual C++ Redistributable from Microsoft instead.

The inventory and supplied notices close the technical inspection gap. They
do not assert universal legal clearance, ownership of earlier removed text,
or permission to change already published distributions.
