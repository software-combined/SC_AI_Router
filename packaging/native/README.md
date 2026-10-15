# Native installer builds

`tools/build_native_installer.py` wraps a canonical release bundle and its
target's pinned Python 3.14 runtime. The builder checks the bundle manifest,
the bundle checksum, and `packaging/runtime.lock` before it stages files.
`--stage-only` writes `<out>/stage/Resources` and needs no platform packaging
tool. It can run with synthetic archives for offline checks.

Native installers are **unsigned**. The build writes `native_signature:
"unsigned"` in `installer.json` and an artifact receipt beside each output.
The receipt records SHA-256 checksums for review. A checksum alone does not
prove who made a download. The router's existing signed update feed remains
the authority for later online updates.

Run the normal build on the target operating system. macOS needs `hdiutil`,
`sips`, and `iconutil`. Windows needs Inno Setup's `ISCC.exe`. Linux needs a
Zenity executable, `libgdk-pixbuf2.0-bin`, an AppImage builder, and a matching
uruntime file. Pass
SHA-256 digests for the Linux builder and uruntime. The builder checks both
files before it runs either one. It embeds uruntime with automatic extraction
when FUSE is unavailable, including images larger than its default 350 MiB
limit.

On Linux, the build copies Zenity, its linked GTK libraries, GObject
Introspection typelibs, compiled GLib settings schemas, and image loaders
into `Resources/gui`. The generated `gui/manifest.json` lists the exact files
copied from that build runner. Build on the oldest supported Ubuntu image so
the copied libraries do not require a newer system C library on staff machines.
The Zenity wrapper sets its library and data paths when a dialog starts. The
recipient does not need a system Zenity command or a system Python install.

The stage's `payload/latest.json` names `file://bundle.tar.gz`. The existing
installer resolves that name beside the local feed document, so moving a DMG,
EXE, or AppImage does not leave a stale build-machine path. The feed's SHA-256
must match `payload/bundle.tar.gz` exactly.
