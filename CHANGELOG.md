# Changelog

## Unreleased

- Add explicit desktop connection destinations while retaining existing switch
  shortcuts. Claude transitions now serialize with installation and updates.

## 1.2.11

- Offer stable downloads only, with a simpler page aligned to Softcom Hub.
  Mac arm64 publication can proceed after its verification while other native
  packages remain private pending their own acceptance.
- Include the catalogue diagnostic helper in installed release bundles.
- Record Claude's served model list during setup and repair, so key and company
  filtering do not cause a false listing warning.
- Native setup and repair reuse a usable saved key instead of asking for it again.
  The separate Replace model key action still opens the secure key window.

## 1.2.10

- Check the installed model catalogue against the same company policy and
  key availability used to create it. A healthy filtered catalogue no longer
  asks the user to reinstall; real catalogue differences still report a warning.

## 1.2.9

- Restore public Router installers, updates and model catalogues without Microsoft
  download sign-in. Existing sign-in settings no longer block the corrected
  updater or setup readiness. Publish public setup scripts for in-place recovery,
  preserve model keys and settings, and retain signed feeds and checksum checks.
- Remove stale generated download sign-in settings when reusing a build folder.

## 1.2.8

- Saved sessions using the previous DeepSeek Flash ID continue on Flash 1017.
  The previous ID stays hidden from both model pickers.

- Replace DeepSeek V4.1 Flash with the pinned 1017 snapshot, including the
  fresh-install default and compaction helper. Retire the previous picker entry.

## 1.2.7

- Include the sanitized local review exporter in installed plugin bundles.
  Verify that it runs using only files included in the router release.

## 1.2.6

- Keep Windows permission checks working when setup starts from PowerShell 7.
  Use Windows PowerShell's own module paths without changing the parent environment.

## 1.2.5

- Restore stopped or missing services from native Set up or repair, preserving
  installed releases and saved settings when the download is older.
- Keep Linux dialogs available after deleting the download. Leave renewal
  notices pending after display or launch failures, and isolate bundled dialog
  libraries from service processes.
- Isolate Windows tasks by account. Migrate only owned legacy tasks after the
  replacement serves, preserve disabled schedules and retain active updater
  parents until exit. Resume interrupted migration through the normal installer.
- Verify Windows task ownership before changes and require prior instances to
  exit before restart. Refuse foreign tasks and failed process-state queries;
  preserve existing tasks when registration fails.
- Verify Windows file permissions using security identifiers and numeric rules,
  so translated account names do not block safe files. Refuse unverifiable or
  widened permissions, and verify fresh permissions after protecting a file.
- Preserve attached assistants and the retained Python interpreter during updates.
  Allow adding assistants after service-only setup without changing other clients.
- Apply Claude's subscription choice independently of Codex and reload the current
  router before confirming a connection. Refuse conflicting subscription choices.
- Refuse a different Claude settings folder until the previous attachment is
  detached, preserving its original settings and restore record.

## 1.2.0-beta

- Add unsigned macOS DMG, Windows EXE and Ubuntu AppImage builds with private
  Python, graphical setup, bundled SC tools and a permanent SCG Router app.
  Preserve existing channels and settings during repair and extra attachments.
  Find the Mac desktop app's bundled Codex tools without a terminal install.
- Add staff Microsoft sign-in for downloads, a permanent download-page source
  and signed package checksums. Keep download access outside runtime rollback.
  Private publication and closing legacy downloads require separate acceptance.

Entries older than the 1.2 series are archived unedited in
[docs/changelog-archive.md](docs/changelog-archive.md).
