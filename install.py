#!/usr/bin/python
"""Install the Chinese-input preset without replacing Omarchy's Fcitx5 service."""

import argparse
import configparser
import fcntl
import json
import os
import shlex
import shutil
import signal
import subprocess
import tempfile
from contextlib import suppress
from pathlib import Path

RIME_URL = "https://github.com/iDvel/rime-ice.git"
RIME_REVISION = "9e66b0729083b37d217312294f6d516c8d7234be"
SERVICE = "omarchy-fcitx5.service"


class Cancellation:
    """Defer termination to safe boundaries; recovery never checks this flag."""

    def __init__(self):
        self.requested = None
        self.handlers = {}

    def __enter__(self):
        for signum in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            self.handlers[signum] = signal.signal(signum, self.request)
        return self

    def request(self, signum, _frame):
        self.requested = signum

    def check(self):
        if self.requested is not None:
            raise InterruptedError(
                f"Installation cancelled by {signal.Signals(self.requested).name}"
            )

    def __exit__(self, *_args):
        for signum, handler in self.handlers.items():
            signal.signal(signum, handler)


def run(*args, cancellation=None, **kwargs):
    if cancellation is None:
        return subprocess.run(args, check=True, **kwargs)
    cancellation.check()
    # Isolate the child so closing the terminal cannot interrupt recovery commands.
    with subprocess.Popen(args, start_new_session=True, **kwargs) as child:
        while True:
            try:
                code = child.wait(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                if cancellation.requested is not None:
                    with suppress(ProcessLookupError):
                        os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        with suppress(ProcessLookupError):
                            os.killpg(child.pid, signal.SIGKILL)
                        child.wait()
                    cancellation.check()
        if code:
            raise subprocess.CalledProcessError(code, args)
    # The caller records completed operations before checking for cancellation.


def configure_profile(path):
    profile = configparser.ConfigParser(interpolation=None, strict=True)
    profile.optionxform = str
    if path.exists():
        profile.read(path)
    if not profile.sections():
        profile.read_dict(
            {
                "Groups/0": {"Name": "Default", "Default Layout": "us"},
                "Groups/0/Items/0": {"Name": "keyboard-us"},
                "GroupOrder": {"0": "Default"},
            }
        )
    group_name = profile.get("GroupOrder", "0")
    group = next(
        section
        for section in profile.sections()
        if section.startswith("Groups/")
        and section.count("/") == 1
        and profile.get(section, "Name", fallback=None) == group_name
    )
    items = [section for section in profile.sections() if section.startswith(f"{group}/Items/")]
    if not any(profile.get(item, "Name", fallback=None) == "rime" for item in items):
        index = max((int(item.rsplit("/", 1)[1]) for item in items), default=-1) + 1
        profile[f"{group}/Items/{index}"] = {"Name": "rime"}
    profile[group]["DefaultIM"] = "rime"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as output:
        profile.write(output, space_around_delimiters=False)


def patch_yaml(path, changes):
    # Installed by omarchy-pkg-add before configuration; also a development dependency.
    import yaml

    document = yaml.safe_load(path.read_text()) if path.exists() else {}
    if document is None:
        document = {}
    if not isinstance(document, dict) or not isinstance(document.get("patch", {}), dict):
        raise ValueError(f"Expected a YAML mapping with a patch mapping: {path}")
    document.setdefault("patch", {}).update(changes)
    path.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False))


def prepare_rime(source, stage):
    # Runtime assets only. Never copy upstream application configs or development files.
    def preserve_word_lists(directory, names):
        relative = Path(directory).relative_to(source)
        if relative != Path("lua/cold_word_drop"):
            return []
        return [
            name
            for name in names
            if name in {"drop_words.lua", "hide_words.lua", "reduce_freq_words.lua"}
            and (stage / relative / name).exists()
        ]

    for asset in source.iterdir():
        if asset.is_dir() and asset.name in {"cn_dicts", "en_dicts", "lua", "opencc"}:
            shutil.copytree(
                asset, stage / asset.name, dirs_exist_ok=True, ignore=preserve_word_lists
            )
        elif asset.is_file() and (
            asset.name.endswith((".yaml", ".txt"))
            and asset.name not in {"squirrel.yaml", "weasel.yaml", "recipe.yaml"}
            and not asset.name.endswith(".custom.yaml")
        ):
            if asset.name == "custom_phrase.txt" and (stage / asset.name).exists():
                continue
            shutil.copy2(asset, stage / asset.name)
    patch_yaml(
        stage / "default.custom.yaml",
        {"schema_list": [{"schema": "rime_ice"}], "menu/page_size": 9},
    )
    patch_yaml(stage / "rime_ice.custom.yaml", {"menu/page_size": 9})


def apply(source, rime, profile, state):
    """Snapshot while Fcitx is stopped, build off-line, and roll back on failure."""
    import yaml

    state.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix="backup-", dir=state))
    rime.parent.mkdir(parents=True, exist_ok=True)
    if rime.is_symlink() or profile.is_symlink():
        raise ValueError("Symlinked Rime directories or profiles require manual setup.")
    swapping = False
    print(f"Backup: {backup}", flush=True)
    # Not an auto-cleaning TemporaryDirectory: recovery failures must retain originals.
    temporary = Path(tempfile.mkdtemp(prefix=".rime-stage-", dir=rime.parent))
    stage = temporary / "rime"
    original = temporary / "original"
    with Cancellation() as cancellation:
        try:
            run("systemctl", "--user", "stop", SERVICE, cancellation=cancellation)
            # Fcitx may create these files while flushing its in-memory state on exit.
            had_rime = rime.exists()
            had_profile = profile.exists()
            cancellation.check()
            if had_profile:
                shutil.copy2(profile, backup / "profile")
            if had_rime:
                # Do not follow symlinks into unrelated user files when applying the preset.
                if any(path.is_symlink() for path in rime.rglob("*")):
                    raise ValueError("Symlinks inside the Rime directory require manual setup.")
                shutil.copytree(rime, backup / "rime")
                shutil.copytree(rime, stage, ignore=shutil.ignore_patterns(".git", "build"))
            else:
                stage.mkdir()
            prepare_rime(source, stage)
            run(
                "rime_deployer",
                "--build",
                str(stage),
                "/usr/share/rime-data",
                str(stage / "build"),
                cancellation=cancellation,
            )
            compiled = yaml.safe_load((stage / "build/rime_ice.schema.yaml").read_text())
            if compiled["menu"]["page_size"] != 9:
                raise ValueError("Compiled Rime-ice schema does not have nine candidates.")
            run(
                "rime_deployer",
                "--set-active-schema",
                "rime_ice",
                cwd=stage,
                cancellation=cancellation,
            )
            staged_profile = temporary / "profile"
            if had_profile:
                shutil.copy2(backup / "profile", staged_profile)
            configure_profile(staged_profile)
            cancellation.check()
            swapping = True
            if had_rime:
                rime.rename(original)
            stage.rename(rime)
            profile.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(staged_profile, profile)
            run("systemctl", "--user", "start", SERVICE, cancellation=cancellation)
            run("systemctl", "--user", "is-active", "--quiet", SERVICE, cancellation=cancellation)
            cancellation.check()
        except BaseException as error:
            try:
                if swapping:
                    # Do not alter potentially live data if service control is unavailable.
                    run("systemctl", "--user", "stop", SERVICE, start_new_session=True)
                    if original.exists() or not had_rime:
                        if rime.exists():
                            shutil.rmtree(rime)
                        if had_rime:
                            original.rename(rime)
                    if had_profile:
                        shutil.copy2(backup / "profile", profile)
                    else:
                        profile.unlink(missing_ok=True)
                run("systemctl", "--user", "start", SERVICE, start_new_session=True)
            except Exception as recovery_error:
                raise RuntimeError(
                    f"Installation failed: {error}. Recovery also failed: {recovery_error}. "
                    f"Retained backup: {backup}; working files: {temporary}. "
                    "Confirm Fcitx is stopped before restoring data manually."
                ) from error
            shutil.rmtree(temporary)
            raise
        shutil.rmtree(temporary)
    return backup


def state_directory():
    return (
        Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
        / "omarchy-chinese-input"
    )


def install(state):
    if os.geteuid() == 0:
        raise RuntimeError("Run as your desktop user, not root or sudo.")
    run("systemctl", "--user", "is-active", "--quiet", SERVICE)
    print(
        "Install Rime-ice Chinese input for this user?\n"
        "This installs fcitx5-rime, fcitx5-configtool, python-yaml and git.\n"
        "It backs up your Rime data and Fcitx5 profile, installs the pinned Rime-ice\n"
        "runtime assets, and selects full Pinyin with nine candidates. Other Rime\n"
        "schemas stay on disk but leave the scheme menu. Personal dictionaries,\n"
        "custom phrases and unrelated patch settings are preserved.\n"
        "Fcitx5 will stop briefly during deployment. No automatic updates are added."
    )
    if input("Continue? [y/N] ").strip().lower() not in {"y", "yes"}:
        return
    run("omarchy-pkg-add", "fcitx5-rime", "fcitx5-configtool", "python-yaml", "git")
    config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    with tempfile.TemporaryDirectory(prefix="rime-ice-source-") as temporary:
        source = Path(temporary) / "source"
        run("git", "init", "--quiet", str(source))
        run("git", "-C", str(source), "fetch", "--depth", "1", RIME_URL, RIME_REVISION)
        run("git", "-C", str(source), "checkout", "--quiet", "--detach", "FETCH_HEAD")
        backup = apply(source, data / "fcitx5/rime", config / "fcitx5/profile", state)
    marker = state / "installed.json"
    pending = state / "installed.json.tmp"
    pending.write_text(
        json.dumps({"revision": RIME_REVISION, "backup": str(backup)}, indent=2) + "\n"
    )
    pending.replace(marker)
    print("Ready. Ctrl+Space switches input methods (unless you customized that shortcut).")
    print("Select candidates with 1-9; F4 opens Rime options. Caps Lock compose is unchanged.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--launch", action="store_true", help="Open first-run setup in an Omarchy terminal"
    )
    args = parser.parse_args()
    state = state_directory()
    if args.launch:
        if not (state / "installed.json").exists():
            command = f"/usr/bin/python {shlex.quote(str(Path(__file__).resolve()))}"
            run("omarchy-launch-floating-terminal-with-presentation", command)
        return
    state.mkdir(parents=True, exist_ok=True)
    with (state / "install.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Chinese input setup is already running.")
            return
        install(state)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Chinese input setup failed: {error}") from error
