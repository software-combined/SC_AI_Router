# Changelog

## Unreleased

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
