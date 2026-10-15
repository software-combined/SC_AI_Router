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
staff protection on both installer files and download lists.

The permanent download address is `https://dist.softwarecombined.com/install/`.
The page detects the operating system and shows every processor alternative.
Stable is the default; beta has a separate labelled choice. The page and public
application settings stay readable before sign-in. Download lists and packages
require an approved Microsoft account.

## Configure staff access

Follow [the access deployment guide](../infra/downloads/README.md). Configure the
exact Microsoft resource tenant, API, public client and assigned `Download` role.
Approved guests need that same explicit assignment. No email-domain shortcut
grants access. Keep signing material in AWS Key Management Service.

Set the existing feed stack's `DownloadKeyGroupId` and `DownloadApiHost` from the
reviewed access deployment. Leave `PrivateUpdates=false` during migration.
The page's `/download-access` route forwards authorisation to the API without
caching. Its browser response uses host-only HttpOnly cookies.

Set repository variable `DOWNLOAD_AUTH_CONFIG` to the public `ClientConfiguration`
JSON output. The release places it in signed feed metadata and native packages.
It contains application identifiers and endpoints, not credentials.
After the acceptance matrix passes, set `NATIVE_INSTALLERS_ACCEPTED=true` to
enable private native publication during the normal release workflow.
Keep that variable unset while packages are still under test. A private first
pilot can use `NATIVE_INSTALLERS_PILOT=true` for beta only, after build checks
pass and the API role is assigned only to the named pilot account. This publishes
only macOS arm64 and leaves both routine update feeds unchanged. The other
packages remain private build artifacts. Windows
distribution also requires the runtime licence evidence in
[runtime licences](runtime-licenses.md). Paid publisher certificates are separate.

Native build artifacts stay in the feed bucket's `native-builds/` prefix.
CloudFront cannot read that prefix, even with a staff download cookie.
The public repository's Actions artifacts carry only the source bundle.
The publisher copies accepted packages into the protected installer prefix.
Full publication uses a new release version after acceptance. An existing pilot's
package checksums remain immutable.

## Migration and recovery

1. Release sign-in support to beta while legacy downloads stay public.
2. Prove member and approved-guest sign-in, refresh, update and rollback recovery.
3. Release the same support to stable and repeat those checks.
4. Set `PrivateUpdates=true` only after those results are reviewed.

The last step protects feeds, signatures, bundles, runtimes and model downloads.
A missed migration uses the same native installer to upgrade in place.
The independent controller and download session survive selecting an older
runtime release. Expired access keeps the running router and last good model
cache. A renewal dialog stays pending when no graphical session is available.

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
| Cancellation | Cancel before attachment, during setup and during sign-in; reopening must resume safely. |
| Recovery | Interrupt setup, run scheduled updates, restore an older runtime and renew access. |
| Removal | Restore the prior assistant configuration and stop the owned services. |
| Linux | Run with FUSE and without FUSE on both supported Ubuntu releases and processors. |
| Access | Allow an assigned staff member and guest; deny an unassigned or wrong-tenant account. |

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
