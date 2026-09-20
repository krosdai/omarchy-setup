# Automatic time zone for Omarchy

An optional system-wide setup for GeoClue + `automatic-timezoned`, independent of
the Chinese-input preset. It enables Wi-Fi positioning and public-IP fallback,
updates the time zone through `systemd-timedated`, and enables NTP clock synchronization.
It does not hard-code a location or time zone.

## Install explicitly

From a checkout containing this feature, run as your normal desktop user:

```sh
/usr/bin/python setup_timezone.py
```

Or, after installing a plugin revision that includes it:

```sh
/usr/bin/python ~/.config/omarchy/plugins/krosdai.chinese-input/setup_timezone.py
```

Review the terminal prompt and answer `y`. Enabling the Chinese-input plugin does
**not** run this setup. No Node.js, pnpm, or Python development dependencies are
needed. Keep `setup_timezone.py`, `install.py`, and `timezone/` together.

Use a checkout you trust. Before confirmation, setup snapshots its Python sources
and service assets in memory. The elevated phase uses those bytes in a private,
root-owned temporary directory with isolated Python imports, rather than reopening
checkout files that could change during package installation or the sudo prompt.

Requires current Arch-based Omarchy, systemd, sudo, and working internet access.
The installer uses `omarchy-pkg-add geoclue` and
`omarchy-pkg-aur-add automatic-timezoned`. The latter builds a community-maintained
[AUR package](https://aur.archlinux.org/packages/automatic-timezoned) and may install
Rust build dependencies. Inspect its PKGBUILD before approving if you have not
already reviewed it. These packages are not pinned; future upstream changes can
affect behavior. This setup was exercised with GeoClue 2.8.2 and
`automatic-timezoned` 2.0.154.

## Location behavior and privacy

- GeoClue sends nearby Wi-Fi access-point identifiers, SSIDs, and signal strengths
  to [BeaconDB](https://beacondb.net/). It does not need to join those networks.
- GeoClue also uses [ReallyFreeGeoIP](https://reallyfreegeoip.org/) for public-IP
  positioning. BeaconDB can itself fall back to IP when it cannot locate the access points.
- More accurate results are preferred. **Wi-Fi and IP requests can run concurrently**;
  this is not a strict sequential Wi-Fi timeout followed by an IP request.
- Wi-Fi-only positioning requires provider coverage. Hidden/opt-out networks and
  locally administered access-point addresses can reduce usable data. A successful
  scan does not guarantee a Wi-Fi-derived position.
- Public-IP positioning can follow a VPN, proxy, or ISP exit location. Check the
  resulting time zone when traveling or enabling a VPN.
- `submit-data=false` disables contribution of GPS-tagged Wi-Fi observations to
  the provider's database; it does **not** disable the positioning requests above.

With the tested versions, the updater requests city-level accuracy and a 10 km
movement threshold for location notifications. GeoClue scans Wi-Fi about every
300 seconds while active; network changes also trigger lookups and cached data
may avoid requests. The updater reacts to location events rather than using its
own polling timer. NTP clock synchronization has a separate adaptive schedule.

## System changes and verification

The setup installs these files, then restarts GeoClue and enables the updater at boot:

```text
/etc/geoclue/conf.d/90-automatic-timezoned.conf
/etc/systemd/system/geoclue.service.d/50-timezone-restart.conf
/etc/systemd/system/automatic-timezoned.service
/etc/systemd/system/geoclue-timezone-agent.service
```

The updater runs as root to set the system time zone. The bundled GeoClue demo agent
runs for root as its dependency: GeoClue otherwise waits for an agent on desktops
such as Hyprland. The application allowlist entry is restricted to UID 0; the global
agent whitelist is unchanged. Restarting GeoClue can briefly interrupt other location
clients. No personal coordinates, Wi-Fi identifiers, API keys, or detected time zone
are stored in this repository.

The GeoClue drop-in restarts it after failures with a five-second delay. The updater
and its agent restart with GeoClue, acquiring a fresh client rather than waiting on
a stale connection. A deliberately stopped updater stays stopped. Clean GeoClue
exits and explicit administrative stops are not treated as crashes.

```sh
systemctl is-enabled automatic-timezoned
systemctl status automatic-timezoned geoclue-timezone-agent geoclue
journalctl -u automatic-timezoned -u geoclue -n 40 --no-pager
timedatectl status
```

Look for `Set timezone to "…"` in the updater log and confirm the `Time zone` value.
An active service alone does not prove a location was obtained. Offline startup can
leave the old time zone until a lookup succeeds. Check `System clock synchronized`
separately for NTP success. Nothing in this setup guarantees Wi-Fi provider coverage.

If GeoClue was deliberately stopped or repeated failures exhausted systemd's restart
limit, resolve the underlying error, then recover with:

```sh
sudo systemctl reset-failed geoclue.service geoclue-timezone-agent.service automatic-timezoned.service
sudo systemctl restart automatic-timezoned.service
```

If location detection stalls, check network access and existing GeoClue configuration
or systemd overrides. The shipped provider options require a recent GeoClue. Later
drop-ins can override these settings. An old `90-no-ip-location.conf` is explicitly
refused because it would disable the requested fallback; review and move it aside
yourself before retrying. Do not remove unrelated location policies blindly.

## Safety, recovery, and removal

Existing files with identical contents are reused; differing files and symlinks are
refused, not overwritten. Each configuration attempt saves the previous time zone,
each NTP provider's boot enablement and running state, location-service states,
and intended new-file paths in:

```text
/var/lib/omarchy-timezone/backup-*/previous.json
```

On activation failure or a handled cancellation, setup stops the updater and agent,
removes only files it created, reloads systemd, and restores the saved time/NTP settings
and previously running services. Existing configuration files are not modified.
Cancellation during the NTP request is deferred until `timedatectl` successfully
returns: terminating that client would not cancel timedated's outstanding work.
NTP is restored only after a completed request, never for an earlier setup failure.
An enabled-but-stopped provider stays enabled and stopped; a disabled-but-running
provider stays disabled and running. Provider discovery honors systemd's standard
`ntp-units.d/*.list` file precedence. Custom `SYSTEMD_TIMEDATED_NTP_SERVICES`
environment overrides and provider states other than enabled/disabled and
active/inactive are refused before system configuration changes rather than guessed.
Keep provider configuration unchanged during setup; timedated caches its provider list.

If the NTP client fails, times out, or disconnects, its server-side outcome is treated
as unknown. **Automatic rollback is skipped**, because it could race with an
outstanding mutation. Setup reports the saved-state path; installed files and running
services are retained. Confirm timedated and its provider jobs have finished before
retrying or manually restoring settings. A nonzero client exit alone is not proof
that the operation was cancelled or that no changes were made.

Packages remain installed. SIGKILL and power loss cannot trigger automatic recovery.
If recovery fails, setup reports both errors and the retained state record rather
than claiming success. Stop the updater and agent before manually restoring that
record's settings. Previously failed services are left stopped, not recreated as failed.

To disable automatic time-zone changes while keeping NTP and the current time zone:

```sh
sudo systemctl disable --now automatic-timezoned.service
sudo systemctl stop geoclue-timezone-agent.service
```

Removing or disabling the Chinese-input plugin does **not** remove these system
services. To remove this setup completely, first disable it as above, then review
the saved record and move aside only the four setup-owned files listed above.
Run `sudo systemctl daemon-reload`. Keep GeoClue if other applications use it, and
do not delete unrelated drop-ins or uninstall shared dependencies. To return to a
fixed time zone, use `sudo timedatectl set-timezone YOUR_IANA_TIME_ZONE` after disabling
the updater. Re-running setup enables the updater again; plugin updates alone do not
reapply system configuration.

## Lifecycle regression probe

On an Omarchy development host with `python-gobject`, `dbus-daemon`, the installed
`automatic-timezoned` binary, and a running user systemd manager:

```sh
/usr/bin/python tests/geoclue_lifecycle.py
```

The probe runs the real updater against synthetic GeoClue and time-setting endpoints
on a private D-Bus, then exercises the shipped dependency graph with disposable
user-mode services. It verifies fresh-client acquisition after an updater restart,
restart propagation after a simulated GeoClue crash, and that a deliberately stopped
updater is not revived. It does not contact the real location service, query external
positioning providers, or change the desktop's time zone. This opt-in probe is separate
from `pnpm test`, whose installer regression tests mock all system commands.
