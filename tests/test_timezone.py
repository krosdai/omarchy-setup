import configparser
import copy
import json
import runpy
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import mock_open, patch

import setup_timezone as timezone
from install import run as real_run


class TimezoneTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.commands = []
        self.enabled = ""
        self.active = dict.fromkeys(timezone.SERVICES, "inactive")
        self.ntp = {"systemd-timesyncd.service": {"enabled": "enabled", "active": "inactive"}}
        (self.root / "proc/123").mkdir(parents=True)
        (self.root / "proc/123/environ").write_bytes(b"LANG=C\0")
        lists = self.root / "usr/lib/systemd/ntp-units.d"
        lists.mkdir(parents=True)
        (lists / "80-systemd-timesync.list").write_text("# Default\nsystemd-timesyncd.service\n")
        self.mock_run = patch.object(timezone, "run", side_effect=self.command).start()
        self.addCleanup(patch.stopall)

    def command(self, *args, **kwargs):
        self.commands.append(args)
        value = ""
        if "--property=Timezone" in args:
            value = "Asia/Tokyo"
        elif "--property=MainPID" in args:
            value = "123"
        elif "--property=LoadState" in args:
            value = "loaded" if args[2] in self.ntp else "not-found"
        elif "--property=UnitFileState" in args:
            value = self.ntp[args[2]]["enabled"] if args[2] in self.ntp else self.enabled
        elif "--property=ActiveState" in args:
            value = self.ntp[args[2]]["active"] if args[2] in self.ntp else self.active[args[2]]
        elif args == ("timedatectl", "set-ntp", "true"):
            # Model timedated selecting one provider and disabling/stopping others.
            for index, state in enumerate(self.ntp.values()):
                state.update(
                    enabled="disabled" if index else "enabled",
                    active="inactive" if index else "active",
                )
        elif len(args) == 3 and args[0] == "systemctl" and args[2] in self.ntp:
            state = self.ntp[args[2]]
            if args[1] in {"enable", "disable"}:
                state["enabled"] = "enabled" if args[1] == "enable" else "disabled"
            elif args[1] in {"start", "stop"}:
                state["active"] = "active" if args[1] == "start" else "inactive"
        return subprocess.CompletedProcess(args, 0, stdout=value + "\n")

    def seed(self):
        for name, relative in timezone.FILES.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((timezone.ASSETS / name).read_bytes())

    def test_install_and_repeat_preserve_files_and_save_prior_state(self):
        backup = timezone.apply(self.root)
        previous = json.loads((backup / "previous.json").read_text())
        self.assertEqual(previous["timezone"], "Asia/Tokyo")
        self.assertEqual(
            previous["ntp"],
            {"systemd-timesyncd.service": {"enabled": "enabled", "active": "inactive"}},
        )
        self.assertEqual(set(previous["created_files"]), set(timezone.FILES.values()))
        self.assertIn(("systemctl", "enable", timezone.SERVICE), self.commands)
        self.assertIn(("timedatectl", "set-ntp", "true"), self.commands)
        original = {relative: (self.root / relative).stat() for relative in timezone.FILES.values()}
        self.enabled = "enabled"
        self.active = dict.fromkeys(timezone.SERVICES, "active")
        repeated = timezone.apply(self.root)
        self.assertNotEqual(backup, repeated)
        self.assertEqual(json.loads((repeated / "previous.json").read_text())["created_files"], [])
        for name, relative in timezone.FILES.items():
            path = self.root / relative
            self.assertEqual(path.read_bytes(), (timezone.ASSETS / name).read_bytes())
            self.assertEqual(path.stat().st_mtime_ns, original[relative].st_mtime_ns)
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)

    def test_assets_enable_wifi_ip_and_root_only_agent_authorization(self):
        config = configparser.ConfigParser()
        config.read(timezone.ASSETS / "90-automatic-timezoned.conf")
        self.assertTrue(config.getboolean("wifi", "enable"))
        self.assertTrue(config.getboolean("ip", "enable"))
        self.assertFalse(config.getboolean("wifi", "submit-data"))
        self.assertEqual(config["automatic-timezoned"]["users"], "0")
        self.assertEqual(config["ip"]["method"], "reallyfreegeoip")
        self.assertEqual(config["wifi"]["url"], "https://api.beacondb.net/v1/geolocate")
        service = configparser.ConfigParser()
        service.read(timezone.ASSETS / timezone.SERVICE)
        self.assertIn(timezone.AGENT, service["Unit"]["Requires"].split())
        self.assertEqual(service["Service"]["ExecStart"], "/usr/bin/automatic-timezoned")
        self.assertEqual(service["Unit"]["PartOf"], "geoclue.service")
        recovery = configparser.ConfigParser()
        recovery.read(timezone.ASSETS / "50-timezone-restart.conf")
        self.assertEqual(recovery["Service"]["Restart"], "on-failure")
        self.assertEqual(recovery["Service"]["RestartSec"], "5")
        self.assertEqual(
            timezone.FILES["50-timezone-restart.conf"],
            "etc/systemd/system/geoclue.service.d/50-timezone-restart.conf",
        )

    def test_conflicting_file_and_symlink_are_refused_without_commands(self):
        path = self.root / timezone.FILES[timezone.SERVICE]
        path.parent.mkdir(parents=True)
        path.write_text("custom service\n")
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            timezone.apply(self.root)
        self.assertEqual(path.read_text(), "custom service\n")
        path.unlink()
        outside = self.root / "outside"
        outside.write_bytes((timezone.ASSETS / timezone.SERVICE).read_bytes())
        path.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "Symlinked"):
            timezone.apply(self.root)
        self.mock_run.assert_not_called()
        self.assertTrue(path.is_symlink())

    def test_failure_before_activation_removes_only_new_files(self):
        existing = self.root / timezone.FILES["90-automatic-timezoned.conf"]
        existing.parent.mkdir(parents=True)
        existing.write_bytes((timezone.ASSETS / existing.name).read_bytes())

        def fail(*args, **kwargs):
            if args[:2] == ("systemd-analyze", "verify"):
                raise RuntimeError("invalid unit")
            return self.command(*args, **kwargs)

        self.mock_run.side_effect = fail
        with self.assertRaisesRegex(RuntimeError, "invalid unit"):
            timezone.apply(self.root)
        self.assertTrue(existing.exists())
        self.assertFalse((self.root / timezone.FILES[timezone.SERVICE]).exists())
        self.assertFalse(any(args[:2] == ("systemctl", "stop") for args in self.commands))

    def test_activation_failure_restores_time_and_service_state(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                self.commands.clear()
                if existing:
                    self.seed()
                    self.enabled = "enabled"
                    self.active = dict.fromkeys(timezone.SERVICES, "active")

                def fail(*args, **kwargs):
                    if args[:2] == ("systemctl", "is-active"):
                        raise RuntimeError("startup failed")
                    return self.command(*args, **kwargs)

                self.mock_run.side_effect = fail
                with self.assertRaisesRegex(RuntimeError, "startup failed"):
                    timezone.apply(self.root)
                stop = ("systemctl", "stop", timezone.SERVICE, timezone.AGENT)
                restore = ("timedatectl", "set-timezone", "Asia/Tokyo")
                self.assertLess(self.commands.index(stop), self.commands.index(restore))
                self.assertFalse(
                    any(args[:2] == ("timedatectl", "set-ntp") for args in self.commands)
                )
                self.assertEqual(
                    self.ntp["systemd-timesyncd.service"],
                    {"enabled": "enabled", "active": "inactive"},
                )
                self.assertEqual(
                    ("systemctl", "disable", timezone.SERVICE) in self.commands, not existing
                )
                for relative in timezone.FILES.values():
                    self.assertEqual((self.root / relative).exists(), existing)
                if existing:
                    self.assertEqual(self.commands[-1], ("systemctl", "restart", timezone.SERVICE))
                else:
                    self.assertEqual(self.commands[-1], ("systemctl", "stop", "geoclue.service"))

    def test_cancellation_after_ntp_change_restores_original_state(self):
        before = copy.deepcopy(self.ntp)

        def cancel(*args, **kwargs):
            result = self.command(*args, **kwargs)
            if args == ("timedatectl", "set-ntp", "true"):
                signal.raise_signal(signal.SIGTERM)
            return result

        self.mock_run.side_effect = cancel
        with self.assertRaises(InterruptedError):
            timezone.apply(self.root)
        self.assertEqual(self.ntp, before)
        self.assertIn(("timedatectl", "set-timezone", "Asia/Tokyo"), self.commands)
        self.assertFalse((self.root / timezone.FILES[timezone.SERVICE]).exists())

    def test_in_flight_cancellation_waits_for_child_and_restores_multiple_providers(self):
        self.ntp["chronyd.service"] = {"enabled": "disabled", "active": "active"}
        (self.root / "usr/lib/systemd/ntp-units.d/90-chrony.list").write_text("chronyd.service\n")
        before = copy.deepcopy(self.ntp)
        completed = self.root / "ntp-completed"

        def delayed(*args, **kwargs):
            if args == ("timedatectl", "set-ntp", "true"):
                # A real isolated child signals the installer while still running.
                # The old cancellation-aware runner killed it before this marker.
                real_run(
                    sys.executable,
                    "-c",
                    "import os, signal, sys, time; from pathlib import Path; "
                    "os.kill(os.getppid(), signal.SIGTERM); time.sleep(0.4); "
                    "Path(sys.argv[1]).write_text('finished')",
                    str(completed),
                    **kwargs,
                )
            elif args[:2] == ("systemctl", "stop"):
                self.assertTrue(completed.exists(), "Rollback raced with the outstanding request")
            return self.command(*args, **kwargs)

        self.mock_run.side_effect = delayed
        with self.assertRaises(InterruptedError):
            timezone.apply(self.root)
        self.assertEqual(completed.read_text(), "finished")
        self.assertEqual(self.ntp, before)
        self.assertLess(
            self.commands.index(("systemctl", "stop", "systemd-timesyncd.service")),
            self.commands.index(("systemctl", "start", "chronyd.service")),
        )

    def test_ambiguous_ntp_failure_retains_state_without_racing_rollback(self):
        before = copy.deepcopy(self.ntp)
        for error in (
            subprocess.CalledProcessError(1, ["timedatectl"]),
            subprocess.TimeoutExpired(["timedatectl"], 120),
        ):
            with self.subTest(error=type(error).__name__):
                self.ntp = copy.deepcopy(before)
                self.commands.clear()

                def fail(*args, error=error, **kwargs):
                    result = self.command(*args, **kwargs)
                    if args == ("timedatectl", "set-ntp", "true"):
                        raise error
                    return result

                self.mock_run.side_effect = fail
                with self.assertRaisesRegex(RuntimeError, "outcome is unknown.*rollback skipped"):
                    timezone.apply(self.root)
                self.assertNotEqual(self.ntp, before)
                self.assertTrue((self.root / timezone.FILES[timezone.SERVICE]).exists())
                self.assertFalse(any(args[:2] == ("systemctl", "stop") for args in self.commands))
                for record in self.root.glob("var/lib/omarchy-timezone/backup-*/previous.json"):
                    self.assertEqual(json.loads(record.read_text())["ntp"], before)

    def test_ntp_list_precedence_missing_units_and_custom_environment(self):
        override = self.root / "etc/systemd/ntp-units.d/80-systemd-timesync.list"
        override.parent.mkdir(parents=True)
        override.write_text("# Override vendor list\nchronyd.service\nabsent.service\n")
        self.ntp["chronyd.service"] = {"enabled": "disabled", "active": "active"}
        self.assertEqual(
            timezone.ntp_state(self.root), {"chronyd.service": self.ntp["chronyd.service"]}
        )
        self.commands.clear()
        (self.root / "proc/123/environ").write_bytes(
            b"SYSTEMD_TIMEDATED_NTP_SERVICES=custom.service\0"
        )
        with self.assertRaisesRegex(ValueError, "overrides require manual"):
            timezone.apply(self.root)
        self.assertFalse((self.root / "var/lib/omarchy-timezone").exists())
        self.assertFalse(any(args[:2] == ("systemctl", "restart") for args in self.commands))

    def test_failed_recovery_retains_files_and_reports_saved_state(self):
        def fail(*args, **kwargs):
            if args[:2] == ("timedatectl", "set-ntp"):
                signal.raise_signal(signal.SIGTERM)
            if args[:2] == ("systemctl", "stop"):
                raise RuntimeError("stop failed")
            return self.command(*args, **kwargs)

        self.mock_run.side_effect = fail
        with self.assertRaisesRegex(RuntimeError, "cancelled.*stop failed.*previous.json"):
            timezone.apply(self.root)
        self.assertTrue((self.root / timezone.FILES[timezone.SERVICE]).exists())
        self.assertEqual(
            len(list(self.root.glob("var/lib/omarchy-timezone/backup-*/previous.json"))), 1
        )

    def test_confirmation_and_package_failure_gate_privileged_configuration(self):
        with (
            patch("sys.argv", ["setup_timezone.py"]),
            patch.object(timezone.os, "geteuid", return_value=1000),
            patch("builtins.input", return_value="n") as answer,
        ):
            timezone.main()
            self.mock_run.assert_not_called()
            answer.return_value = "yes"
            self.mock_run.side_effect = RuntimeError("package failed")
            with self.assertRaisesRegex(RuntimeError, "package failed"):
                timezone.main()
            self.mock_run.assert_called_once_with("omarchy-pkg-add", "geoclue")
            self.mock_run.reset_mock(side_effect=True)
            timezone.main()
            self.assertEqual(
                [call.args for call in self.mock_run.call_args_list],
                [
                    ("omarchy-pkg-add", "geoclue"),
                    ("omarchy-pkg-aur-add", "automatic-timezoned"),
                    (
                        "sudo",
                        "/usr/bin/python",
                        "-I",
                        "-c",
                        timezone.BOOTSTRAP,
                    ),
                ],
            )

    def test_unprivileged_cancellation_exits_with_concise_message(self):
        for at_prompt in (True, False):
            with (
                self.subTest(at_prompt=at_prompt),
                patch("sys.argv", ["setup_timezone.py"]),
                patch.object(timezone.os, "geteuid", return_value=1000),
                patch(
                    "builtins.input",
                    side_effect=KeyboardInterrupt if at_prompt else None,
                    return_value="y",
                ),
                patch("install.run", side_effect=KeyboardInterrupt) as run,
                self.assertRaisesRegex(SystemExit, "^Automatic time zone setup cancelled\\.$"),
            ):
                runpy.run_path(timezone.__file__, run_name="__main__")
            if at_prompt:
                run.assert_not_called()
            else:
                run.assert_called_once_with("omarchy-pkg-add", "geoclue")

    def test_lock_contention_exits_without_configuration(self):
        with (
            patch("sys.argv", ["setup_timezone.py", "--configure"]),
            patch.object(timezone.os, "geteuid", return_value=0),
            patch.object(timezone.Path, "open", mock_open()),
            patch.object(timezone.fcntl, "flock", side_effect=BlockingIOError),
            patch.object(timezone, "apply") as apply,
            patch("builtins.print") as output,
        ):
            timezone.main()
        apply.assert_not_called()
        output.assert_called_once_with("Automatic time zone setup is already running.")

    def test_elevation_uses_source_snapshot_taken_before_consent(self):
        with (
            patch("sys.argv", ["setup_timezone.py"]),
            patch.object(timezone.os, "geteuid", return_value=1000),
            patch.object(timezone.Path, "read_text", return_value="trusted snapshot") as read,
            patch("builtins.input") as answer,
        ):

            def consent(_prompt):
                read.return_value = "changed after consent"
                return "y"

            answer.side_effect = consent
            timezone.main()
        payload = json.loads(self.mock_run.call_args.kwargs["input"])
        self.assertEqual(payload, dict.fromkeys(timezone.SOURCES, "trusted snapshot"))

    def test_bootstrap_uses_private_staging_and_isolated_imports(self):
        payload = dict.fromkeys(timezone.SOURCES, "")
        payload["install.py"] = "TOKEN = 'frozen'\n"
        payload["setup_timezone.py"] = (
            "import sys; from pathlib import Path; import install\n"
            "assert sys.argv[1:] == ['--configure']\n"
            "assert Path(__file__).parent.stat().st_mode & 0o077 == 0\n"
            "assert install.TOKEN == 'frozen'\n"
            "print(Path(__file__).parent)\n"
        )
        (self.root / "install.py").write_text("raise RuntimeError('untrusted import')\n")
        result = real_run(
            sys.executable,
            "-I",
            "-c",
            timezone.BOOTSTRAP,
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            cwd=self.root,
            env={**timezone.os.environ, "PYTHONPATH": str(self.root)},
        )
        self.assertFalse(Path(result.stdout.strip()).exists())


if __name__ == "__main__":
    unittest.main()
