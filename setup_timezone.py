#!/usr/bin/python
"""Opt-in Wi-Fi/IP automatic time zone setup for Omarchy."""

import argparse
import fcntl
import json
import os
import subprocess
import tempfile
from pathlib import Path

from install import Cancellation, run

ASSETS = Path(__file__).resolve().parent / "timezone"
FILES = {
    "90-automatic-timezoned.conf": "etc/geoclue/conf.d/90-automatic-timezoned.conf",
    "50-timezone-restart.conf": "etc/systemd/system/geoclue.service.d/50-timezone-restart.conf",
    "automatic-timezoned.service": "etc/systemd/system/automatic-timezoned.service",
    "geoclue-timezone-agent.service": "etc/systemd/system/geoclue-timezone-agent.service",
}
SERVICE = "automatic-timezoned.service"
AGENT = "geoclue-timezone-agent.service"
SERVICES = ("geoclue.service", AGENT, SERVICE)
SOURCES = ("setup_timezone.py", "install.py", *(f"timezone/{name}" for name in FILES))
BOOTSTRAP = f"""
import json, runpy, sys, tempfile
from pathlib import Path

sources = json.load(sys.stdin)
with tempfile.TemporaryDirectory(prefix="omarchy-timezone-source-") as directory:
    root = Path(directory)
    for name in {SOURCES!r}:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(sources[name])
    sys.path.insert(0, str(root))
    sys.argv = [str(root / "setup_timezone.py"), "--configure"]
    runpy.run_path(sys.argv[0], run_name="__main__")
"""


def query(*args):
    return run(*args, capture_output=True, text=True).stdout.strip()


def ntp_state(root):
    """Snapshot providers from timedated's standard, precedence-ordered list files."""
    # timedatectl has activated timedated before this call. Do not guess which
    # providers a custom environment override might select.
    pid = query("systemctl", "show", "systemd-timedated.service", "--property=MainPID", "--value")
    if not pid.isdecimal() or pid == "0":
        raise ValueError("Cannot inspect the time synchronization provider configuration.")
    environment = (root / f"proc/{pid}/environ").read_bytes().split(b"\0")
    if any(item.startswith(b"SYSTEMD_TIMEDATED_NTP_SERVICES=") for item in environment):
        raise ValueError("Custom timedated NTP provider overrides require manual setup.")
    lists = {}
    for directory in ("usr/lib", "usr/local/lib", "run", "etc"):
        for path in (root / directory / "systemd/ntp-units.d").glob("*.list"):
            lists[path.name] = path
    providers = {}
    for name in sorted(lists):
        for line in lists[name].read_text().splitlines():
            unit = line.strip()
            if not unit or unit.startswith("#") or unit in providers:
                continue
            loaded = query("systemctl", "show", unit, "--property=LoadState", "--value")
            if loaded in {"not-found", "masked"}:
                continue
            enabled = query("systemctl", "show", unit, "--property=UnitFileState", "--value")
            active = query("systemctl", "show", unit, "--property=ActiveState", "--value")
            if (
                loaded != "loaded"
                or enabled not in {"enabled", "disabled"}
                or active not in {"active", "inactive"}
            ):
                raise ValueError(f"Unsupported NTP provider state; configure it manually: {unit}")
            providers[unit] = {"enabled": enabled, "active": active}
    if not providers:
        raise ValueError("No supported time synchronization provider found.")
    return providers


def restore_ntp(providers):
    # SetNTP changes both enablement and activity, possibly switching providers.
    # Stop newly started providers first so mutually exclusive daemons cannot race.
    for unit, state in providers.items():
        if state["active"] == "inactive":
            run("systemctl", "stop", unit, start_new_session=True)
    for unit, state in providers.items():
        action = "enable" if state["enabled"] == "enabled" else "disable"
        run("systemctl", action, unit, start_new_session=True)
    for unit, state in providers.items():
        if state["active"] == "active":
            run("systemctl", "start", unit, start_new_session=True)


def apply(root):
    """Apply to the real root only from the privileged, locked entry point."""
    destinations = {name: root / relative for name, relative in FILES.items()}
    # Never silently replace custom configuration, masks, or symlink targets.
    for name, path in destinations.items():
        if any(parent.is_symlink() for parent in (path, *path.parents)):
            raise ValueError(f"Symlinked configuration requires manual setup: {path}")
        if path.exists() and not path.is_file():
            raise ValueError(f"Non-regular configuration path requires manual setup: {path}")
        if path.exists() and path.read_bytes() != (ASSETS / name).read_bytes():
            raise ValueError(f"Conflicting configuration; back it up and reconcile it: {path}")
    legacy = root / "etc/geoclue/conf.d/90-no-ip-location.conf"
    if legacy.exists() or legacy.is_symlink():
        raise ValueError(f"Remove or reconcile the old IP-blocking override first: {legacy}")

    previous = {
        "timezone": query("timedatectl", "show", "--property=Timezone", "--value"),
        "ntp": ntp_state(root),
        "enabled": query("systemctl", "show", SERVICE, "--property=UnitFileState", "--value"),
        "active": {
            service: query("systemctl", "show", service, "--property=ActiveState", "--value")
            for service in SERVICES
        },
    }
    if previous["enabled"] not in {"", "disabled", "enabled"} or any(
        value not in {"active", "inactive", "failed"} for value in previous["active"].values()
    ):
        raise ValueError("Services are masked, transient, or changing state; resolve this first.")
    if not previous["timezone"]:
        raise ValueError("Cannot save the current time zone.")

    state = root / "var/lib/omarchy-timezone"
    state.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix="backup-", dir=state))
    created = [path for path in destinations.values() if not path.exists()]
    previous["created_files"] = [str(path.relative_to(root)) for path in created]
    (backup / "previous.json").write_text(json.dumps(previous, indent=2) + "\n")
    print(f"Previous settings: {backup / 'previous.json'}", flush=True)

    written = []
    activating = False
    ntp_attempted = False
    ntp_completed = False
    with Cancellation() as cancellation:
        try:
            for name, path in destinations.items():
                cancellation.check()
                if path in created:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("xb") as output:
                        written.append(path)
                        output.write((ASSETS / name).read_bytes())
                    path.chmod(0o644)
            run("systemctl", "daemon-reload", cancellation=cancellation)
            run(
                "systemd-analyze",
                "verify",
                *(str(destinations[name]) for name in (SERVICE, AGENT)),
                cancellation=cancellation,
            )
            cancellation.check()
            activating = True
            run("systemctl", "restart", "geoclue.service", cancellation=cancellation)
            run("systemctl", "enable", SERVICE, cancellation=cancellation)
            run("systemctl", "restart", SERVICE, cancellation=cancellation)
            for service in SERVICES:
                run("systemctl", "is-active", "--quiet", service, cancellation=cancellation)
            cancellation.check()
            ntp_attempted = True
            # Killing the client does not cancel timedated's server-side work.
            # Defer signals until its reply, with the client isolated from the terminal.
            run("timedatectl", "set-ntp", "true", start_new_session=True)
            ntp_completed = True
            cancellation.check()
        except BaseException as error:
            if ntp_attempted and not ntp_completed:
                raise RuntimeError(
                    f"NTP request outcome is unknown: {error}. Automatic rollback skipped; "
                    "the services and files may remain installed and active. Confirm timedated "
                    "and its provider jobs have finished before restoring settings from "
                    f"{backup / 'previous.json'}."
                ) from error
            try:
                # Stop writers before restoring files or the previous time zone.
                if activating:
                    run("systemctl", "stop", SERVICE, AGENT, start_new_session=True)
                    if previous["enabled"] != "enabled":
                        run("systemctl", "disable", SERVICE, start_new_session=True)
                for path in written:
                    path.unlink(missing_ok=True)
                run("systemctl", "daemon-reload", start_new_session=True)
                if ntp_attempted:
                    restore_ntp(previous["ntp"])
                if activating:
                    run("timedatectl", "set-timezone", previous["timezone"], start_new_session=True)
                    for service in SERVICES:
                        if previous["active"][service] == "active":
                            run("systemctl", "restart", service, start_new_session=True)
                        elif service == "geoclue.service":
                            run("systemctl", "stop", service, start_new_session=True)
            except Exception as recovery_error:
                raise RuntimeError(
                    f"Setup failed: {error}. Recovery also failed: {recovery_error}. "
                    f"Use {backup / 'previous.json'} for manual recovery."
                ) from error
            raise
    print("Automatic time zone service enabled. Location acquisition may take time.")
    try:
        run("timedatectl", "status")
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"Setup completed, but time status could not be displayed: {error}")
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configure", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.configure:
        if os.geteuid() != 0:
            raise RuntimeError("System configuration requires sudo.")
        with Path("/run/omarchy-timezone.lock").open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("Automatic time zone setup is already running.")
                return
            apply(Path("/"))
        return
    if os.geteuid() == 0:
        raise RuntimeError("Run as your desktop user, not root or sudo.")
    # Freeze the trusted checkout before consent/package installation. The root
    # phase receives these bytes, never reopens the user's mutable checkout, and
    # uses isolated Python with only the private staged directory added for imports.
    source = Path(__file__).resolve().parent
    sources = json.dumps({name: (source / name).read_text() for name in SOURCES})
    print(
        "Enable automatic time zone and network clock synchronization for this computer?\n"
        "Installs GeoClue from Arch and automatic-timezoned from the community AUR\n"
        "using Omarchy's package helpers. The AUR build may install a Rust toolchain.\n"
        "Nearby Wi-Fi identifiers are sent to BeaconDB; IP lookups use ReallyFreeGeoIP.\n"
        "GeoClue prefers more accurate results but can query Wi-Fi and IP concurrently.\n"
        "Wi-Fi coverage is not guaranteed; VPNs can give an incorrect IP location.\n"
        "Enables system services at boot and may immediately change the time zone.\n"
        "Existing differing files are refused. Previous service/time settings are saved\n"
        "under /var/lib/omarchy-timezone. Packages remain installed after a failure."
    )
    if input("Continue? [y/N] ").strip().lower() not in {"y", "yes"}:
        return
    run("omarchy-pkg-add", "geoclue")
    run("omarchy-pkg-aur-add", "automatic-timezoned")
    run("sudo", "/usr/bin/python", "-I", "-c", BOOTSTRAP, input=sources, text=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit("Automatic time zone setup cancelled.") from None
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Automatic time zone setup failed: {error}") from error
