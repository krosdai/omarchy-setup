# Omarchy Chinese Input

An Omarchy shell plugin that installs **Fcitx5 + Rime-ice (雾凇拼音)** with full Pinyin,
simplified Chinese by default, and **nine candidates per page**. It uses Omarchy's
existing Fcitx5 service and leaves Caps Lock compose sequences unchanged.

## Install

Requires an up-to-date Arch-based Omarchy desktop with the `omarchy plugin` commands,
Python 3, and an active `omarchy-fcitx5.service`. Run as your desktop user, not root.
Internet access to the Arch package mirrors and GitHub is required.

Once this plugin has been published to the repository's default branch:

```sh
omarchy plugin add https://github.com/krosdai/omarchy-setup.git --enable
```

Omarchy asks whether you trust the plugin. On first enable, the plugin opens an
installation terminal. Review the changes and answer `y`; enter your sudo password
if the package installer asks for it. No application build or development tools are
needed on the recipient's machine.

Adding a plugin does not run an install hook: Omarchy has no such hook. This plugin's
headless QML service opens the installer when enabled. After a successful installation,
it does nothing on subsequent logins or hot reloads. Cancelling or failing leaves setup
available on the next enable/login, or you can run it manually:

```sh
/usr/bin/python ~/.config/omarchy/plugins/krosdai.chinese-input/install.py
```

## What gets configured

- Packages: `fcitx5-rime`, `fcitx5-configtool`, `python-yaml`, and `git` through
  `omarchy-pkg-add`; `librime` is installed as a dependency.
- Rime-ice runtime assets from the official repository, pinned to the revision in
  `install.py`. It does not run upstream installation scripts.
- The Rime scheme menu selects `rime_ice` (full Pinyin). Other installed schemes stay
  on disk. The upstream scheme defaults to simplified Chinese; existing user choices
  such as traditional-character mode are not forcibly reset.
- `menu/page_size: 9` in both `default.custom.yaml` and `rime_ice.custom.yaml`.
- Rime is added once to the first group in Fcitx5's group order and becomes that group's
  default non-keyboard input method. Existing keyboard layouts, other input methods,
  groups, and global shortcuts are preserved. A fresh profile gets US English + Rime.

Fcitx5 stops during deployment to prevent concurrent writes to your personal dictionary.
Finish any pending composition before approving installation. Source downloads happen
before the service stops.

## Use

| Key                         | Action                                                              |
| --------------------------- | ------------------------------------------------------------------- |
| `Ctrl+Space`                | Switch between keyboard input and Rime, with stock Fcitx5 shortcuts |
| `Space`                     | Select the first candidate                                          |
| `1`–`9`                     | Select a numbered candidate                                         |
| `F4`                        | Open Rime options, including simplified/traditional Chinese         |
| Caps Lock compose sequences | Keep working through Omarchy's existing configuration               |

Run `fcitx5-configtool` for input-method settings. Custom global shortcuts are not
replaced; use your existing shortcut if it differs from `Ctrl+Space`.

## Existing data, backups, and removal

The installer keeps personal dictionaries (`*.userdb`), sync data, existing
`custom_phrase.txt`, cold-word suppression lists (`drop_words.lua`, `hide_words.lua`,
and `reduce_freq_words.lua`), and unrelated YAML patch settings. It replaces the upstream
runtime assets, the scheme menu, and candidate-page size. Direct edits to upstream
dictionaries or Lua files should be moved to custom patches before installation.
YAML/profile serialization can change formatting and remove comments; original files
remain in the backup. Symlinked Rime data or profiles are refused rather than followed.

After Fcitx5 stops and flushes its configuration, the installer backs up the Rime directory
and profile. Deployment failure or cancellation with Ctrl+C, SIGHUP, or SIGTERM stops the
deployment child before restoring configuration and restarting Fcitx5. Repeated cancellation
signals do not interrupt recovery. SIGKILL and power loss cannot be handled this way.

If recovery itself fails, the installer keeps the backup and working directory, reports
both errors and their paths, and requires manual recovery. In particular, it will not replace
potentially live data if it cannot stop Fcitx5. System packages installed before a failure
remain installed; they are not rolled back.

Default locations (standard `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, and `XDG_STATE_HOME`
overrides are honored):

```text
~/.config/fcitx5/profile
~/.local/share/fcitx5/rime/
~/.local/state/omarchy-chinese-input/installed.json
~/.local/state/omarchy-chinese-input/backup-*/
```

`installed.json` records the source revision and latest successful backup location.
To restore manually, stop `omarchy-fcitx5.service`, move the current Rime directory and
profile aside, copy the saved `rime/` and `profile` back when present, and start the
service. An absent backup item means it did not exist before installation. Keep newer
personal dictionary data if you want to retain learning since the backup.

```sh
omarchy plugin remove krosdai.chinese-input
```

Removing or disabling the plugin does **not** uninstall packages, remove Rime, or erase
your dictionary. It only removes/disables the setup launcher. The completion marker also
remains; after re-adding the plugin, run the installer manually to reapply the preset.

## Updates

There are **no automatic dictionary updates**. `omarchy plugin update` updates this
plugin, not the installed Rime-ice data. A maintainer can change the pinned revision
after testing it; users then update the plugin and run its installer manually.
Reapplying the preset creates another backup and preserves personal data. An existing
Git checkout in the Rime directory is saved in the backup, not carried into the managed
runtime directory; do not use `git pull` there after adopting this plugin.

## Optional Hyprland scrolling layout

`presets/scrolling.lua` makes Hyprland's built-in scrolling layout the default.
It is independent of Chinese-input setup and is **not applied automatically** when
the plugin is enabled. It requires a Lua-configured Hyprland with scrolling support
(tested on Omarchy with Hyprland 0.56.2); it is not a legacy `hyprland.conf` snippet.
It leaves column widths, keybindings, appearance, and explicit workspace layouts alone.

From this repository's checkout (or the installed plugin directory), run:

```sh
mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/hypr"
cp -i presets/scrolling.lua "${XDG_CONFIG_HOME:-$HOME/.config}/hypr/scrolling.lua"
```

Back up your `hypr/hyprland.lua`, then add this line **once at the end**, after
Omarchy's defaults and your other overrides:

```lua
require("hypr.scrolling")
```

Apply and verify:

```sh
hyprctl reload
hyprctl configerrors
hyprctl getoption general:layout
```

The error list should be empty and the layout should read `scrolling`. Existing
per-workspace layout choices still take precedence; the preset changes the default
for workspaces without an override. To undo, remove the `require` line and reload;
your previous default takes effect again. The copied preset remains independent of
plugin updates or removal.

## Development

```sh
mise run setup
pnpm test
pnpm run lint
```

Tests use temporary directories and mock package/service commands, so they never modify
your desktop. For a local install before publication, run `/usr/bin/python install.py`
from this checkout in a terminal.

Validate a clean plugin export with `omarchy plugin validate /path/to/export`. Do not
validate a checkout containing `node_modules` or `.venv`: Omarchy rejects symlinks inside
plugin directories. The published Git checkout does not contain those development files.

For a real deployment smoke test without altering the desktop, copy the pinned Rime-ice
runtime assets into a disposable directory with `prepare_rime`, run `rime_deployer --build`
against `/usr/share/rime-data`, and inspect the compiled schema's candidate-page size.
