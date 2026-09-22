# Omarchy setup index

Choose the desktop features you want, then install their independent plugins.
**This repository is an index, not an installable plugin or an all-in-one installer.**
Do not pass this repository to `omarchy plugin add`.

The four maintained plugins live in separate public repositories under
[krosdai](https://github.com/krosdai). Each repository contains its own
installation, verification, backup, and removal instructions.

## Pick only the features you need

The order below is a suggested setup sequence, **not a dependency chain**. None of
these plugins requires another plugin in this list. Skip any row you do not want.
The machine-readable inventory is [plugins.json](plugins.json).

| Order | Feature and when to choose it                                                        | Repository                                                                                          | Plugin ID                                  |
| ----- | ------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| 0     | Optional graphical plugin manager: install, enable, update and remove plugins        | [fross100/omaplug](https://github.com/fross100/omaplug)                                             | `omaplug`                                  |
| 1     | Chinese input: full Pinyin with Rime-ice and nine candidates                         | [krosdai/omarchy-chinese-input](https://github.com/krosdai/omarchy-chinese-input)                   | `krosdai.chinese-input`                    |
| 2     | Mac-style touchpad: natural scrolling, two-finger right-click, no tap-and-drag       | [krosdai/omarchy-mac-touchpad](https://github.com/krosdai/omarchy-mac-touchpad)                     | `krosdai.mac-touchpad`                     |
| 3     | Traditional mouse wheel: wheel toward you scrolls down; touchpad unchanged           | [krosdai/omarchy-mouse-scrolling](https://github.com/krosdai/omarchy-mouse-scrolling)               | `krosdai.mouse-scrolling`                  |
| 4     | Window/workspace switcher: visual Alt+Tab and Super+Tab, community plugin            | [manateelazycat/omarchy-window-switcher](https://github.com/manateelazycat/omarchy-window-switcher) | `io.github.manateelazycat.window-switcher` |
| 5     | Multi-monitor manager: saved display profiles and automatic hotplug/lid switching    | [crmne/omarchy-hyprmoncfg](https://github.com/crmne/omarchy-hyprmoncfg)                             | `crmne.hyprmoncfg`                         |
| 6     | Automatic time zone: useful for travel; system-wide, with location-provider requests | [krosdai/omarchy-auto-timezone](https://github.com/krosdai/omarchy-auto-timezone)                   | `krosdai.auto-timezone`                    |

For a laptop, start with the touchpad plugin and add Chinese input if needed. Add
mouse scrolling only if you use a wheel mouse and want that preference explicit;
it may already match your default. The window switcher does not require changing
your window layout. Automatic time zone is last so you can
review its system changes and privacy implications separately.

## Optional first step: Omaplug plugin manager

[Omaplug](https://github.com/fross100/omaplug) is a community-maintained graphical
manager for Omarchy 4.x plugins. Install it first if you prefer managing plugins
from the bar rather than the CLI:

```sh
omarchy plugin add https://github.com/fross100/omaplug.git --enable
```

Click the Plugin Manager icon on the bar to open it. It supports plugin installation,
enable/disable toggles, update checks, updates, removal and bar arrangement. Other
plugins do not depend on it, and the CLI instructions below remain valid. Review
plugin trust and update-verification status before installing or updating code.
Updates are separate from automatic update checks; do not bulk-update plugins
without reviewing their changes.

The Apps-menu shortcut is off by default and can be enabled in Omaplug's settings.
Before removing Omaplug, turn off that shortcut if enabled and remove any keyboard
shortcuts you assigned through it. Use `omarchy plugin remove omaplug` to uninstall.

## Install one plugin at a time

Use a current Arch-based Omarchy desktop with native `omarchy plugin` support,
Quickshell and system Python. The desktop presets target Lua-based Hyprland
configuration, tested with Hyprland 0.56.2; they are not legacy `.conf` snippets.
Run as your normal desktop user. Plugins execute trusted code as that user; review
each repository and leave Omarchy's trust confirmation enabled.

For each plugin you chose, read its README, then run **only its command**:

```sh
omarchy plugin add https://github.com/krosdai/omarchy-chinese-input.git --enable
omarchy plugin add https://github.com/krosdai/omarchy-mac-touchpad.git --enable
omarchy plugin add https://github.com/krosdai/omarchy-mouse-scrolling.git --enable
omarchy plugin add https://github.com/krosdai/omarchy-auto-timezone.git --enable
```

Omarchy clones the public repository, validates its manifest,
and enables its launcher. Development environments such as `.venv` are not included
in that clone. No development toolchain is needed to install the plugin.

Each maintained plugin opens a terminal for a separate first-run confirmation.
Approve, finish setup, and check the result before enabling the next one. Chinese
input installs packages and briefly stops Fcitx5. Automatic time zone installs
GeoClue and an AUR package, requires sudo, enables system services and NTP, and may
immediately change the machine's time zone. The two desktop presets only change
their own settings in your personal Hyprland configuration.

Do not blindly approve automatic time zone: Wi-Fi identifiers are sent to BeaconDB,
and public-IP positioning uses ReallyFreeGeoIP. VPN exit locations can produce an
incorrect time zone. Read that repository's privacy and recovery sections first.

## Optional external window switcher

[Omarchy Window Switcher](https://github.com/manateelazycat/omarchy-window-switcher)
is maintained by ManateeLazyCat, not this project or the Omarchy maintainers. The
upstream version reviewed for this guide supports Omarchy Quattro/4's native
plugin mechanism and Lua-based Hyprland bindings:

```sh
omarchy plugin add https://github.com/manateelazycat/omarchy-window-switcher.git --enable
```

It provides `Alt+Tab` for windows and `Super+Tab` for workspaces; adding Shift cycles
backward. It also replaces the built-in workspace bar component. Disable standalone
Orbit or Overview Workspaces installations first to avoid duplicate widgets and
shortcuts. Custom bindings on these keys can be displaced; default system ordering
keeps `Super+1` through `Super+0`, while optional legacy ordering can take them over.
No extra `dofile()` or manual keybinding fragment is needed.

For updates, follow upstream's current README. At the reviewed revision:

```sh
omarchy plugin update io.github.manateelazycat.window-switcher
omarchy restart shell
```

To remove it:

```sh
omarchy plugin remove io.github.manateelazycat.window-switcher
```

Removal restores stock bindings rather than arbitrary previous custom bindings;
review your personal shortcuts afterward. This index links to upstream rather than
vendoring its code. Reviewed source:
[README](https://github.com/manateelazycat/omarchy-window-switcher/blob/bfce7dfbdd6502a71c865008843d3c04d9c6ac5b/README.md)
and [keybinding service](https://github.com/manateelazycat/omarchy-window-switcher/blob/bfce7dfbdd6502a71c865008843d3c04d9c6ac5b/overview/KeybindingService.qml).

## Optional external multi-monitor manager

[hyprmoncfg for Omarchy](https://github.com/crmne/omarchy-hyprmoncfg) is Carmine
Paolino's community-maintained bar panel for visual display arrangement, scale,
resolution, brightness, saved profiles and workspace planning. Its backend can
automatically select profiles on monitor hotplug, lid changes and resume. It manages
display outputs, not Hyprland's window tiling layout.

```sh
omarchy plugin add https://github.com/crmne/omarchy-hyprmoncfg.git --enable
```

**The panel and the backend are separate installations.** The reviewed panel version
2.3.5 requires Omarchy Quattro and `hyprmoncfg` 1.18.3 or newer. If the backend is
missing, open the bar panel and choose **Install hyprmoncfg**. Review the AUR package
and sudo prompt in the terminal: a fresh installation uses `hyprmoncfg-bin`, while
existing installations keep their binary/source package choice. The installation
flow enables and restarts the user service `hyprmoncfgd.service` and opens the editor.
Save suitable profiles before relying on automatic switching. Review and confirm
display changes while the preview is visible; unconfirmed previews revert.

Check backend availability separately from plugin enablement:

```sh
hyprmoncfg --version
systemctl --user status hyprmoncfgd.service
journalctl --user -u hyprmoncfgd.service -n 40 --no-pager
hyprctl monitors
hyprctl configerrors
```

An enabled bar plugin does not prove the backend is installed or managing displays.
Do not let multiple tools compete to apply display profiles. Panel updates and
backend package upgrades are separate; after a backend upgrade, the panel may offer
**Restart daemon** to load the new binary.

To hand display management back to Omarchy before removing the panel:

```sh
hyprmoncfg unmanage
omarchy plugin remove crmne.hyprmoncfg
```

`unmanage` removes the managed Hyprland include, restores Omarchy's monitor watcher
and reloads Hyprland. The backend remains running but persists its unmanaged state;
removing the panel alone does not release display management. If the backend was
never installed, only remove the panel. Saved profiles remain under
`~/.config/hyprmoncfg/profiles`. Consult upstream's README for complete package removal.

## Migrate from the old all-in-one repository

Nothing in this split changes an existing desktop automatically. Preserve your
configuration, dictionaries, completion markers and backups.

- **Chinese input:** the plugin keeps ID `krosdai.chinese-input`. Replace the old
  checkout with the new source; do not enable a second launcher with another ID:

  ```sh
  omarchy plugin remove krosdai.chinese-input
  omarchy plugin add https://github.com/krosdai/omarchy-chinese-input.git --enable
  ```

  Plugin removal does not erase Rime data. The existing successful-install marker
  prevents an unnecessary reinstall. Existing shortcuts and learned words remain.
  Stop updating the old `omarchy-setup` plugin source: this repository no longer
  contains an installable manifest.

- **Automatic time zone:** existing system services and `/var/lib/omarchy-timezone`
  backups remain valid. Adding the new plugin asks you to approve one idempotent
  re-run, which reuses identical system files and records a new per-user completion
  marker. It can restart services and change the time zone; migration is optional.

- **Mouse scrolling:** previously copied Lua snippets continue working. You do not
  need to replace them. If adopting the new managed-block installer, leave working
  snippets in place until verification succeeds; later
  remove only obsolete references if you want a single configuration owner.

- **Mac-style touchpad:** existing personal overrides continue working. Installing
  the independent plugin does not delete those overrides. Uninstalling its managed
  block reveals the remaining personal settings, which may give the same behavior.

## Verify and undo deliberately

After each desktop preset, check `hyprctl configerrors` and its relevant setting:

```sh
hyprctl getoption input:touchpad:natural_scroll       # true for Mac-style touchpad
hyprctl getoption input:touchpad:clickfinger_behavior # true
hyprctl getoption input:touchpad:tap-and-drag          # false
hyprctl getoption input:natural_scroll                # false for mouse scrolling
```

For Chinese input, use `fcitx5-configtool` and try composition in an editor. For
automatic time zone, inspect `timedatectl status` and the service journal; an active
service alone does not prove a location was obtained.

For the maintained setup plugins, `omarchy plugin disable ID` stops the launcher;
it does **not** undo installed settings, stop the time-zone service or uninstall
packages. The two desktop presets provide `install.py --uninstall`; disable the
launcher before using it. Chinese input and automatic time zone document their
own data-preserving recovery/removal procedures. Keep backups until satisfied.
Plugin updates do not silently reapply any of these presets.

## Maintain the index

Feature code and feature tests belong in the individual repositories, not here.
Update `plugins.json` and this guide together when adding a recommendation. Give
external plugins their actual installation method and disclose conflicts; do not
invent unpublished remote URLs or make optional plugins mandatory.

This repository retains its existing development toolchain and lint policy:

```sh
mise run setup
pnpm test
pnpm run lint
```

Index tests check inventory consistency and ensure this repository cannot still be
mistaken for an installable plugin. Run each plugin's own tests before releasing
changes there.
