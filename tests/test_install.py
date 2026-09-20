import configparser
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

import install


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.rime = self.root / "data/fcitx5/rime"
        self.profile = self.root / "config/fcitx5/profile"
        self.state = self.root / "state"
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "default.yaml").write_text("menu:\n  page_size: 5\n")
        (self.source / "custom_phrase.txt").write_text("upstream phrases\n")
        self.commands = []

    def command(self, *args, **kwargs):
        self.commands.append(args)
        if args[:2] == ("rime_deployer", "--build"):
            build = Path(args[4])
            build.mkdir()
            (build / "rime_ice.schema.yaml").write_text("menu:\n  page_size: 9\n")

    def apply(self):
        return install.apply(self.source, self.rime, self.profile, self.state)

    def seed(self):
        self.rime.mkdir(parents=True)
        (self.rime / "rime_ice.userdb").mkdir()
        (self.rime / "rime_ice.userdb/data").write_bytes(b"personal learning\x00")
        (self.rime / "custom_phrase.txt").write_text("personal phrases\n")
        (self.rime / "default.custom.yaml").write_text(
            "patch:\n  menu/page_size: 5\n  ascii_composer/switch_key/Shift_L: noop\n"
        )
        self.profile.parent.mkdir(parents=True)
        self.profile.write_text(
            "[Groups/0]\nName=Japanese\nDefault Layout=jp\nDefaultIM=mozc\n"
            "[Groups/0/Items/0]\nName=mozc\n"
            "[Groups/1]\nName=Writing\nDefault Layout=de\nDefaultIM=keyboard-de\n"
            "[Groups/1/Items/0]\nName=keyboard-de\nLayout=de\n"
            "[Groups/1/Items/4]\nName=keyboard-us\n"
            "[GroupOrder]\n0=Writing\n1=Japanese\n"
        )

    def test_fresh_install_and_repeated_install(self):
        with patch.object(install, "run", side_effect=self.command):
            self.apply()
            first = self.profile.read_bytes()
            self.apply()
        self.assertEqual(self.profile.read_bytes(), first)
        self.assertEqual(self.profile.read_text().count("Name=rime\n"), 1)
        self.assertIn("Name=keyboard-us", self.profile.read_text())
        self.assertEqual(
            yaml.safe_load((self.rime / "default.custom.yaml").read_text())["patch"],
            {"schema_list": [{"schema": "rime_ice"}], "menu/page_size": 9},
        )

    def test_preserves_data_and_other_groups(self):
        self.seed()
        original_profile = self.profile.read_bytes()
        with patch.object(install, "run", side_effect=self.command):
            backup = self.apply()
        self.assertEqual((backup / "profile").read_bytes(), original_profile)
        self.assertEqual((self.rime / "custom_phrase.txt").read_text(), "personal phrases\n")
        self.assertEqual(
            (self.rime / "rime_ice.userdb/data").read_bytes(), b"personal learning\x00"
        )
        self.assertEqual(
            (backup / "rime/rime_ice.userdb/data").read_bytes(), b"personal learning\x00"
        )
        config = configparser.ConfigParser()
        config.read(self.profile)
        self.assertEqual(config["Groups/0"]["DefaultIM"], "mozc")
        self.assertEqual(config["Groups/1"]["Default Layout"], "de")
        self.assertEqual(config["Groups/1"]["DefaultIM"], "rime")
        self.assertEqual(config["Groups/1/Items/5"]["Name"], "rime")
        self.assertEqual(
            yaml.safe_load((self.rime / "default.custom.yaml").read_text())["patch"][
                "ascii_composer/switch_key/Shift_L"
            ],
            "noop",
        )

    def test_shutdown_created_profile_is_preserved_on_success_and_failure(self):
        for fail_after_swap in (False, True):
            with self.subTest(failure=fail_after_swap):
                self.profile.unlink(missing_ok=True)
                flushed = "[Groups/0]\nName=French\nDefault Layout=fr\nDefaultIM=keyboard-fr\n"
                flushed += "[Groups/0/Items/0]\nName=keyboard-fr\n[GroupOrder]\n0=French\n"

                def command(*args, fail_after_swap=fail_after_swap, flushed=flushed, **kwargs):
                    if args[:3] == ("systemctl", "--user", "stop") and not self.profile.exists():
                        self.profile.parent.mkdir(parents=True, exist_ok=True)
                        self.profile.write_text(flushed)
                    if fail_after_swap and args[:3] == ("systemctl", "--user", "is-active"):
                        raise subprocess.CalledProcessError(1, args)
                    self.command(*args, **kwargs)

                with patch.object(install, "run", side_effect=command):
                    if fail_after_swap:
                        with self.assertRaises(subprocess.CalledProcessError):
                            self.apply()
                        self.assertEqual(self.profile.read_text(), flushed)
                    else:
                        backup = self.apply()
                        self.assertEqual((backup / "profile").read_text(), flushed)
                        self.assertIn("Default Layout=fr", self.profile.read_text())
                        self.assertIn("Name=keyboard-fr", self.profile.read_text())

    def test_cold_word_lists_survive_while_processor_updates(self):
        self.seed()
        upstream = self.source / "lua/cold_word_drop"
        personal = self.rime / "lua/cold_word_drop"
        upstream.mkdir(parents=True)
        personal.mkdir(parents=True)
        names = ["drop_words.lua", "hide_words.lua", "reduce_freq_words.lua"]
        for name in names:
            (upstream / name).write_text("return {}")
            (personal / name).write_text(f"personal {name}")
        (upstream / "processor.lua").write_text("new processor")
        (personal / "processor.lua").write_text("old processor")
        with patch.object(install, "run", side_effect=self.command):
            self.apply()
            self.apply()
        for name in names:
            self.assertEqual((personal / name).read_text(), f"personal {name}")
        self.assertEqual((personal / "processor.lua").read_text(), "new processor")

    def test_failed_rollback_retains_original_and_reports_both_errors(self):
        self.seed()
        old_profile = self.profile.read_bytes()

        def fail(*args, **kwargs):
            if args[:3] == ("systemctl", "--user", "is-active"):
                raise RuntimeError("initial service failure")
            if args[:3] == ("systemctl", "--user", "stop") and "cancellation" not in kwargs:
                raise RuntimeError("rollback stop failure")
            self.command(*args, **kwargs)

        with (
            patch.object(install, "run", side_effect=fail),
            self.assertRaises(RuntimeError) as error,
        ):
            self.apply()
        self.assertIn("initial service failure", str(error.exception))
        self.assertIn("rollback stop failure", str(error.exception))
        retained = next(self.rime.parent.glob(".rime-stage-*"))
        backup = next(self.state.glob("backup-*"))
        self.assertIn(str(retained), str(error.exception))
        self.assertIn(str(backup), str(error.exception))
        self.assertEqual(
            (retained / "original/custom_phrase.txt").read_text(), "personal phrases\n"
        )
        self.assertEqual((backup / "profile").read_bytes(), old_profile)
        self.assertTrue(self.rime.exists())
        self.assertIn("DefaultIM=rime", self.profile.read_text())

    def test_real_signals_cancel_child_and_restore_data(self):
        self.seed()
        original = self.profile.read_bytes()
        for phase, signum in [("compile", signal.SIGTERM), ("swap", signal.SIGHUP)]:
            with self.subTest(phase=phase):
                for name in ("ready", "restarted", "cancelled"):
                    (self.root / name).unlink(missing_ok=True)
                env = {**os.environ, "PYTHONPATH": str(Path(install.__file__).parent)}
                worker = Path(__file__).with_name("signal_worker.py")
                with subprocess.Popen(
                    [sys.executable, str(worker), str(self.root), phase],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                ) as process:
                    try:
                        deadline = time.monotonic() + 10
                        while not (self.root / "ready").exists():
                            if process.poll() is not None or time.monotonic() > deadline:
                                self.fail(
                                    "Signal-test worker did not reach the deployment boundary"
                                )
                            time.sleep(0.01)
                        process.send_signal(signum)
                        stdout, stderr = process.communicate(timeout=10)
                        self.assertEqual(process.returncode, 0, stdout + stderr)
                    finally:
                        if process.poll() is None:
                            process.kill()
                            process.wait()
                child = int((self.root / "ready").read_text())
                with self.assertRaises(ProcessLookupError):
                    os.kill(child, 0)
                self.assertTrue((self.root / "cancelled").exists())
                self.assertTrue((self.root / "restarted").exists())
                self.assertEqual(self.profile.read_bytes(), original)
                self.assertEqual(
                    (self.rime / "custom_phrase.txt").read_text(), "personal phrases\n"
                )
                self.assertEqual(list(self.rime.parent.glob(".rime-stage-*")), [])

    def test_failures_restore_original_files_and_restart_service(self):
        for failing_command in [("rime_deployer", "--build"), ("systemctl", "--user", "is-active")]:
            with self.subTest(command=failing_command):
                if not self.rime.exists():
                    self.seed()
                original_profile = self.profile.read_bytes()
                original_patch = (self.rime / "default.custom.yaml").read_bytes()

                def fail(*args, failing_command=failing_command, **kwargs):
                    if args[: len(failing_command)] == failing_command:
                        raise subprocess.CalledProcessError(1, args)
                    self.command(*args, **kwargs)

                with (
                    patch.object(install, "run", side_effect=fail),
                    self.assertRaises(subprocess.CalledProcessError),
                ):
                    self.apply()
                self.assertEqual(self.profile.read_bytes(), original_profile)
                self.assertEqual((self.rime / "default.custom.yaml").read_bytes(), original_patch)
                self.assertEqual(
                    (self.rime / "custom_phrase.txt").read_text(), "personal phrases\n"
                )
                self.assertEqual(
                    self.commands[-1], ("systemctl", "--user", "start", install.SERVICE)
                )

    def test_fresh_install_failure_leaves_no_profile_or_rime(self):
        def fail(*args, **kwargs):
            if args[:3] == ("systemctl", "--user", "is-active"):
                raise subprocess.CalledProcessError(1, args)
            self.command(*args, **kwargs)

        with (
            patch.object(install, "run", side_effect=fail),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            self.apply()
        self.assertFalse(self.profile.exists())
        self.assertFalse(self.rime.exists())

    def test_invalid_yaml_and_symlinks_are_not_overwritten(self):
        self.seed()
        custom = self.rime / "default.custom.yaml"
        custom.write_text("patch: []\n")
        with patch.object(install, "run", side_effect=self.command), self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(custom.read_text(), "patch: []\n")
        target = self.root / "external"
        target.write_text("untouched")
        (self.rime / "external").symlink_to(target)
        with patch.object(install, "run", side_effect=self.command), self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(target.read_text(), "untouched")

    def test_launch_is_suppressed_after_success(self):
        with (
            patch.object(install, "state_directory", return_value=self.state),
            patch("sys.argv", ["install.py", "--launch"]),
            patch.object(install, "run") as run,
        ):
            install.main()
            self.assertEqual(
                run.call_args.args[0], "omarchy-launch-floating-terminal-with-presentation"
            )
            self.state.mkdir()
            (self.state / "installed.json").write_text("{}")
            run.reset_mock()
            install.main()
            run.assert_not_called()

    def test_cancel_does_not_install_or_mark_success(self):
        with (
            patch("builtins.input", return_value="n"),
            patch.object(install.os, "geteuid", return_value=1000),
            patch.object(install, "run") as run,
        ):
            install.install(self.state)
        run.assert_called_once_with("systemctl", "--user", "is-active", "--quiet", install.SERVICE)
        self.assertFalse((self.state / "installed.json").exists())

    def test_install_marks_only_success_and_honors_xdg_paths(self):
        self.state.mkdir()
        with (
            patch("builtins.input", return_value="y"),
            patch.object(install.os, "geteuid", return_value=1000),
            patch.dict(
                os.environ,
                {
                    "XDG_DATA_HOME": str(self.root / "data"),
                    "XDG_CONFIG_HOME": str(self.root / "config"),
                },
            ),
            patch.object(install, "run") as run,
            patch.object(install, "apply", side_effect=ValueError("deployment failed")) as apply,
        ):
            with self.assertRaises(ValueError):
                install.install(self.state)
            self.assertFalse((self.state / "installed.json").exists())
            apply.side_effect = None
            apply.return_value = self.state / "backup-example"
            install.install(self.state)
            self.assertEqual(apply.call_args.args[1:3], (self.rime, self.profile))
            self.assertTrue(any(install.RIME_REVISION in call.args for call in run.call_args_list))
        self.assertEqual(
            json.loads((self.state / "installed.json").read_text())["backup"],
            str(self.state / "backup-example"),
        )


if __name__ == "__main__":
    unittest.main()
