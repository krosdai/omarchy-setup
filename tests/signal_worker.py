"""Disposable subprocess for testing real installer signals without desktop access."""

import os
import signal
import sys
from pathlib import Path
from unittest.mock import patch

import install

root = Path(sys.argv[1])
phase = sys.argv[2]
real_run = install.run
child_code = """
import os, sys, time
from pathlib import Path
Path(sys.argv[1]).write_text(str(os.getpid()))
time.sleep(60)
"""


def command(*args, **kwargs):
    if args[:2] == ("rime_deployer", "--build"):
        if phase == "compile":
            real_run(sys.executable, "-c", child_code, str(root / "ready"), **kwargs)
        build = Path(args[4])
        build.mkdir()
        (build / "rime_ice.schema.yaml").write_text("menu:\n  page_size: 9\n")
    elif args[:3] == ("systemctl", "--user", "start"):
        if phase == "swap" and "cancellation" in kwargs:
            real_run(sys.executable, "-c", child_code, str(root / "ready"), **kwargs)
        else:
            # A second signal must not interrupt recovery.
            os.kill(os.getpid(), signal.SIGHUP)
            (root / "restarted").write_text("yes")


with patch.object(install, "run", side_effect=command):
    try:
        install.apply(
            root / "source",
            root / "data/fcitx5/rime",
            root / "config/fcitx5/profile",
            root / "state",
        )
    except InterruptedError:
        (root / "cancelled").write_text("yes")
    else:
        raise AssertionError("Expected cancellation")
