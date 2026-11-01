# SC_AI repository transition

SC_AI holds the shared AI setup. Router is one component. Agent plugins and
their skills remain first-class repository packages.

## Source and installed paths

Run Router development, tests, and build commands from `router/`.
Router runtime, installer, tools, tests, configuration, and infrastructure
sources live there. Shared guides remain in `docs/`.

The root `.codex-plugin`, `.claude-plugin`, and `skills/manage-router` keep
the `scg-openrouter` setup identity. Marketplace packages remain under
`plugins/`, registered by `.agents/plugins/marketplace.json`. Delivery generates the
Claude marketplace manifest in the local installed marketplace.

The release builder maps these source paths into the existing flat installed
bundle. Installed Python module names, launch commands, plugin IDs, preferences,
keys, and saved state do not move. Source builds work without filesystem links.

## Existing installations and clones

The signed update feed remains the installed-user delivery route. Its domain,
signing key, channel names, and increasing serial requirement remain unchanged.
A new repository's workflow counter must not reset the feed serial.
Set the new repository's `RELEASE_SERIAL_OFFSET` variable to the latest live
serial at the publication freeze. Keep it fixed afterwards. The release builder
adds the workflow run number; missing configuration blocks SC_AI publication.
Recheck both channels before the first release. This source change does not
set that variable or establish the freeze serial.

The previous source repository was `software-combined/SC_AI_Router`.
Historical evidence links use `software-combined/SC_AI_Router-archive`.
The archive is private after cutover; reading it requires authorised access. Existing marketplace source
registrations remain recognised during Router's local-marketplace migration.
The canonical source is now `software-combined/SC_AI`.

Clean history cannot fast-forward an existing clone. Keep local work and use a
fresh clone for the new source. Do not force-reset an existing checkout.
Git marketplace installations require verified native-client refresh before
cutover; a normal Git pull does not prove that transition works.

## Release and acceptance gates

This source change does not publish a release or change a live installation.
Before cutover, verify repository permissions and workflow settings, publishing
trust, release serial continuity, native-client plugin refresh, and installer
delivery. Complete normal client compatibility and native acceptance gates.
The first main push checks all candidate paths for native acceptance. Later
pushes use their actual diff; missing nonzero history fails the scope check.

Preserve the work-account key provisioning and Hub contracts. Repository
migration grants no new consent, key issuance, offboarding, or spending authority.
Build checks do not prove employee onboarding or user acceptance.

Historical CI comparisons require `HISTORICAL_SOURCE_REPOSITORY` to name the
archive containing the baseline commit. They fail before checkout if it is
missing. A private archive also requires authorised cross-repository read access;
the new repository token does not provide that access automatically. Historical
comparison jobs remain unavailable until those conditions are verified. They
are diagnostic jobs and do not replace normal acceptance checks.
