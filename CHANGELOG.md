# Changelog

## Unreleased

- Preflight every assistant before removal. Preserve changed connection values
  and unrelated settings, and keep Router running when an interrupted removal
  needs another attempt.

- Repair Linux's scheduled updater independently of assistant settings. Retain
  verified maintenance code across runtime rollback and keep releases used by
  loaded jobs or the running updater.

- Repair and remove Codex attachments after harmless client formatting changes.
  Preserve added user settings, comments and dotfile links, while refusing
  changed connection values and unsafe edits.

## 1.3.1

- Preserve the exact previous menu pointer after failed Windows menu delivery.

## 1.3.0

- Keep desktop controls responsive across profile changes, expose menu delivery
  failures separately and make redacted support bundles easy to find.
- Preserve Windows file durability and case-insensitive app identity, and wait
  for orphaned Linux app writers before changing client settings.

- Deliver matching native menu resources through signed updates. Repair missing
  controls on same-version and cached checks while preserving the previous menu.

- Build native menu helpers for macOS, Windows and Linux, with pinned Linux
  dependencies and per-target Resources archives for update delivery.

- Add shared desktop controls, safe router restart and owned sign-in startup.
  Keep the menu separate from routing and retain a full control window without a tray host.

- Add explicit desktop connection destinations while retaining existing switch
  shortcuts. Claude transitions now serialize with installation and updates.
