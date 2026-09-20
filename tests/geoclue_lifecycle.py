"""Probe the installed updater on a private bus, never the desktop's system bus.

Run with /usr/bin/python tests/geoclue_lifecycle.py on an Omarchy development host.
Requires python-gobject, dbus-daemon, and automatic-timezoned; not an installer test.
"""

import configparser
import os
import subprocess
import threading
import time
from pathlib import Path

from gi.repository import Gio, GLib

XML = """
<node>
  <interface name="org.freedesktop.GeoClue2.Manager">
    <method name="GetClient"><arg type="o" direction="out"/></method>
  </interface>
  <interface name="org.freedesktop.GeoClue2.Client">
    <property name="DesktopId" type="s" access="readwrite"/>
    <property name="DistanceThreshold" type="u" access="readwrite"/>
    <property name="RequestedAccuracyLevel" type="u" access="readwrite"/>
    <method name="Start"/>
    <signal name="LocationUpdated"><arg type="o"/><arg type="o"/></signal>
  </interface>
  <interface name="org.freedesktop.GeoClue2.Location">
    <property name="Latitude" type="d" access="read"/>
    <property name="Longitude" type="d" access="read"/>
  </interface>
  <interface name="org.freedesktop.timedate1">
    <method name="SetTimezone"><arg type="s" direction="in"/><arg type="b" direction="in"/></method>
  </interface>
</node>
"""
CLIENT = "/org/freedesktop/GeoClue2/Client/1"
LOCATION = "/org/freedesktop/GeoClue2/Location/1"


def connect(address, name):
    connection = Gio.DBusConnection.new_for_address_sync(
        address,
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
        | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
        None,
        None,
    )
    connection.call_sync(
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "RequestName",
        GLib.Variant("(su)", (name, 0)),
        None,
        Gio.DBusCallFlags.NONE,
        5000,
        None,
    )
    return connection


def stop(process):
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def service_recovery():
    """Exercise the shipped dependency graph with disposable user-mode sleep services."""
    assets = Path(__file__).resolve().parent.parent / "timezone"
    units = {
        name: f"omarchy-timezone-probe-{os.getpid()}-{name}"
        for name in (
            "geoclue.service",
            "geoclue-timezone-agent.service",
            "automatic-timezoned.service",
        )
    }

    def command(*args, check=True):
        return subprocess.run(args, check=check, capture_output=True, text=True).stdout.strip()

    def invocation(unit):
        return command("systemctl", "--user", "show", unit, "--property=InvocationID", "--value")

    def await_restart(previous):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if all(
                invocation(unit) not in {"", old}
                and command(
                    "systemctl", "--user", "show", unit, "--property=ActiveState", "--value"
                )
                == "active"
                for unit, old in previous.items()
            ):
                return
            time.sleep(0.1)
        raise AssertionError("Service graph did not recover after simulated GeoClue failure")

    try:
        for name, unit in units.items():
            config = configparser.ConfigParser()
            config.optionxform = str
            config.read(
                assets / ("50-timezone-restart.conf" if name == "geoclue.service" else name)
            )
            properties = []
            for key in ("Requires", "After", "PartOf"):
                peers = [
                    units[peer]
                    for peer in config.get("Unit", key, fallback="").split()
                    if peer in units
                ]
                if peers:
                    properties.append(f"--property={key}={' '.join(peers)}")
            for key in ("Restart", "RestartSec"):
                properties.append(f"--property={key}={config['Service'][key]}")
            command(
                "systemd-run", "--user", f"--unit={unit}", *properties, "/usr/bin/sleep", "infinity"
            )
        previous = {unit: invocation(unit) for unit in units.values()}
        command("systemctl", "--user", "kill", "--signal=SIGKILL", units["geoclue.service"])
        await_restart(previous)
        print("PASS: GeoClue failure restarts GeoClue, the agent, and the updater.")
        updater = units["automatic-timezoned.service"]
        command("systemctl", "--user", "stop", updater)
        previous = {units["geoclue.service"]: invocation(units["geoclue.service"])}
        command("systemctl", "--user", "kill", "--signal=SIGKILL", units["geoclue.service"])
        await_restart(previous)
        if (
            command("systemctl", "--user", "show", updater, "--property=ActiveState", "--value")
            != "inactive"
        ):
            raise AssertionError("GeoClue restart revived a deliberately stopped updater")
        print("PASS: GeoClue recovery does not revive a deliberately stopped updater.")
    finally:
        command("systemctl", "--user", "stop", *reversed(units.values()), check=False)
        command("systemctl", "--user", "reset-failed", *units.values(), check=False)


def main():
    changed = threading.Event()
    acquisitions = []
    zones = []
    interfaces = Gio.DBusNodeInfo.new_for_xml(XML).interfaces
    loop = GLib.MainLoop()

    def method(connection, _sender, _path, _interface, name, parameters, invocation):
        if name == "GetClient":
            acquisitions.append(time.monotonic())
            invocation.return_value(GLib.Variant("(o)", (CLIENT,)))
        elif name == "Start":
            invocation.return_value(None)
            connection.emit_signal(
                None,
                CLIENT,
                "org.freedesktop.GeoClue2.Client",
                "LocationUpdated",
                GLib.Variant("(oo)", ("/", LOCATION)),
            )
        elif name == "SetTimezone":
            zones.append(parameters.unpack()[0])
            invocation.return_value(None)
            changed.set()

    def get_property(_connection, _sender, _path, _interface, name):
        # Synthetic London coordinates, independent of the user's actual location.
        return {
            "Latitude": GLib.Variant("d", 51.5),
            "Longitude": GLib.Variant("d", -0.12),
            "DesktopId": GLib.Variant("s", "automatic-timezoned"),
            "DistanceThreshold": GLib.Variant("u", 0),
            "RequestedAccuracyLevel": GLib.Variant("u", 4),
        }[name]

    def geoclue(address):
        connection = connect(address, "org.freedesktop.GeoClue2")
        for path, interface in zip(
            ("/org/freedesktop/GeoClue2/Manager", CLIENT, LOCATION), interfaces[:3], strict=True
        ):
            connection.register_object(path, interface, method, get_property, lambda *_: True)
        return connection

    with subprocess.Popen(
        ["dbus-daemon", "--session", "--nofork", "--print-address=1"],
        stdout=subprocess.PIPE,
        text=True,
    ) as bus:
        geo = clock = updater = None
        thread = threading.Thread(target=loop.run)
        thread.start()
        try:
            address = bus.stdout.readline().strip()
            if not address.startswith("unix:"):
                raise RuntimeError("Private test bus did not start")
            clock = connect(address, "org.freedesktop.timedate1")
            clock.register_object("/org/freedesktop/timedate1", interfaces[3], method, None, None)
            geo = geoclue(address)
            env = {**os.environ, "DBUS_SYSTEM_BUS_ADDRESS": address}
            updater = subprocess.Popen(["automatic-timezoned"], env=env)
            if not changed.wait(10) or zones != ["Europe/London"]:
                raise AssertionError(f"Initial fake location not applied: {zones}")
            changed.clear()
            geo.close_sync(None)
            time.sleep(1)
            geo = geoclue(address)
            reconnected = changed.wait(5)
            print(
                f"After GeoClue owner loss: process exit={updater.poll()}, "
                f"client acquisitions={len(acquisitions)}, resumed={reconnected}"
            )
            stop(updater)
            changed.clear()
            updater = subprocess.Popen(["automatic-timezoned"], env=env)
            if not changed.wait(10) or zones[-1] != "Europe/London" or len(acquisitions) < 2:
                raise AssertionError("Restart did not acquire a fresh client and location")
            print(
                "PASS: restarting the updater reacquires GeoClue and sets the expected time zone."
            )
        finally:
            if updater is not None:
                stop(updater)
            if geo is not None:
                geo.close_sync(None)
            if clock is not None:
                clock.close_sync(None)
            loop.quit()
            thread.join(timeout=5)
            stop(bus)


if __name__ == "__main__":
    main()
    service_recovery()
