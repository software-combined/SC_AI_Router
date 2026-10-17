# Native installer delivery

The native packages are unsigned at the owner's request. Existing signed feeds,
manifest checks, SHA-256 checksums and feed replay protection remain required.
This implementation does not establish staff acceptance or authorise closing
the existing public update path.

## Build and publish

`Release` builds one canonical bundle, then creates five packages on native
macOS, Windows and Ubuntu runners. Each build verifies its pinned Python archive.
Linux bundles Zenity and GTK dependencies from Ubuntu 24.04, plus a pinned
AppImage runtime with automatic extraction when FUSE is unavailable.
See [builder details](../packaging/native/README.md).

Each artifact receipt names its target, exact router bundle, runtime and package
checksum. Publication requires all five targets from one exact bundle.
The publisher uploads immutable packages and signed `SHA256SUMS` first.
It changes the channel's download list last. It refuses a distribution without
public access for both installer files and download lists.

The permanent download address is `https://dist.softwarecombined.com/install/`.
The page uses Apple, Microsoft and Linux logos with clear platform labels.
Each platform shows its published processor alternatives or a labelled setup script.
The page offers stable downloads only. Installer lists,
packages, update feeds, bundles, runtimes and model catalogues are public.
Microsoft download sign-in is not required. Model-provider credentials remain
separate and are never published with software.

## Publication and recovery

The publisher checks that the download origin has no signed-cookie requirement.
The S3 origin remains private behind CloudFront origin access control, and the
`native-builds/` prefix remains unavailable through CloudFront. Package checksums,
signed feeds, runtime pins and replay protection remain enforced.

Release builds no longer consume `DOWNLOAD_AUTH_CONFIG` or
`DOWNLOAD_AUTH_ENROLMENT`. Legacy release CLI sign-in options fail explicitly.
Stale generated `dist/download-auth.json` is removed when building a release;
installed users' authentication files are preserved and ignored by public transport.

Keep `NATIVE_INSTALLERS_ACCEPTED` unset until the native acceptance matrix passes.
After Mac verification, `NATIVE_INSTALLERS_MACOS_ARM64_ONLY=true` can publish
the Mac arm64 stable package while the other native packages remain private.
This platform-specific publication does not assert acceptance of the other
platforms or the complete matrix. Beta update feeds remain separate from the
stable-only download page. Full native publication requires the
existing five-platform checks and Windows runtime licence evidence in
[runtime licences](runtime-licenses.md).
Use a new release version when adding native platforms to a published version.
Its signed checksum inventory is immutable.

The download page follows Softcom Hub's light canvas, SC Pink, near-black text
and Space Grotesk/Inter font stacks. The corporate icon is the existing bundled
asset. Device-policy help sits below the main download area.

Every ordinary release also publishes public `bootstrap.sh` and `bootstrap.ps1`
setup scripts under `/install/` at the download origin. An installation whose old updater cannot
get past Microsoft sign-in must run the current public setup script once. It uses
new installer code, so legacy download settings do not block it; successful delivery
also replaces the independent update controller. The existing channel is preserved
unless the operator explicitly requests another. Model keys and client settings are
preserved. Users with working scheduled updates receive the release normally.

Normal update jobs run independently from the serving Router process. An offline
computer or disabled update job cannot fetch a release until it runs again.
Publishing a new feed alone cannot repair an old controller that rejects downloads
before making its first network request. Do not claim automatic recovery on such
hosts without proving their update path works.

Linux dialogs use the retained setup wrapper after the download is deleted,
with system Zenity as a fallback. The wrapper scopes GTK dependencies to its
dialog child, so service processes do not inherit bundled library overrides.

Set up or repair uses the existing installer repair path. A same-version or
older download restores the installed service without replacing its release,
key, channel, custom feed or client settings. Unreadable client receipts remain
intact during service repair; adding an assistant still requires readable receipts.
Repair reuses a usable saved key. Choose **Replace model key** to open the key
window when you want to change it.

Claude desktop can connect without a terminal client. Automatic SC tool delivery
also needs the Claude Code setup tools from the desktop app's Install page.
The graphical setup checks this prerequisite before making a desktop attachment.
It guides existing desktop users there instead of repeating a repair request.
This does not attach the terminal client or restart an assistant.

## Acceptance matrix

Complete this matrix for Windows x64, macOS arm64 and Intel, and Ubuntu
24.04/26.04 GNOME on x64 and arm64. Existing client compatibility records remain
separate from native-package acceptance.

| Gate | Required evidence |
| --- | --- |
| Fresh computer | Install with no Python or Git; use an installed, signed-in supported assistant. |
| Retained files | Delete the download or eject the DMG, then restart the router and the SCG Router app. |
| Existing user | Upgrade and same-version repair preserve key, channel, custom feed, instructions, policy and disabled plugins. |
| Assistant attachment | Verify desktop-only setup and attaching another assistant without detaching the first. |
| Ready state | Observe a new routed reply, enabled SC tools and explicit fresh-session confirmation. |
| Cancellation | Cancel before attachment, during setup; reopening must resume safely. |
| Recovery | Interrupt setup, run scheduled updates, restore an older runtime and verify public update recovery. |
| Removal | Restore the prior assistant configuration and stop the owned services. |
| Linux | Run with FUSE and without FUSE on both supported Ubuntu releases and processors. |
| Access | Allow downloads without an account; reject tampered metadata, bundles and off-origin redirects. |

The first local proof built and mounted an unsigned macOS arm64 DMG. Its bundled
Python reported 3.14.7 and its local feed matched the bundled archive. A clean
Ubuntu 24.04 container ran the bundled Zenity dependency closure without system
Python or GTK. These are build and dependency checks. They do not complete this
matrix or prove a nontechnical staff member can finish the shared-link flow.

The 1.2.0 candidate also passed one real Claude Code 2.1.283 file-read round trip
through an isolated router. It requested `deepseek/deepseek-v4.1-flash` at Low
and completed in two upstream calls. Both calls reported that exact model;
served effort was not exposed. The probe used synthetic data, a twelve-call cap,
2,048 output tokens per call and a USD 0.25 client budget. This proves that reply
path, not graphical installation or the remaining platform matrix.
