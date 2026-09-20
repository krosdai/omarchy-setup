# Omarchy Chinese Input Plugin

This repository packages a Chinese-input preset as the native Omarchy shell service
plugin `krosdai.chinese-input`. It is not the upstream scaffold anymore; the scaffold's
toolchain and formatting configuration remain in place.

## Ownership

- `manifest.json`: root plugin manifest required by `omarchy plugin add`.
- `Service.qml`: first-enable launcher, with no visual UI or replacement Fcitx5 daemon.
- `install.py`: confirmed installation, pinned Rime-ice assets, configuration, backups,
  rollback, and successful-install marker.
- `tests/test_install.py`: isolated installer tests; system commands are mocked.

## Constraints

Keep the plugin installable from a plain Git clone without development dependencies.
Use the installed system Python at runtime and Omarchy's package helper for dependencies.
Do not edit `/usr/share/omarchy`, introduce another Fcitx5 autostart, or reset user layouts,
compose keys, personal dictionaries, or unrelated patches. Installation needs explicit
confirmation in a terminal. Preserve backups and test failure paths before changing the
installer. Never exercise installation tests against the developer's real home directory.

Automatic dictionary updates are intentionally out of scope. Pin and test new upstream
Rime-ice revisions deliberately; plugin updates do not silently reconfigure the desktop.

## Verification

Run `pnpm test` and `pnpm run lint` before declaring work done. Use `mise run setup` for
development dependencies. Do not change linter/formatter settings without approval.
Validate a clean export with `omarchy plugin validate`; `.venv` and `node_modules` contain
symlinks that the plugin validator correctly refuses. QML startup can be checked in an
isolated Quickshell process with a temporary `XDG_STATE_HOME` and a completed-install
marker, so it cannot trigger a real installation.

Keep the shared hygiene tools small. Follow Gitmoji + Conventional Commits when commits
are requested. Do not publish or push without authorization.
