<!-- shared: structure — keep headings aligned across Migz93 self-hosted apps -->

# Deployment

## Target System

| Thing | Value |
|---|---|
| Supported OS | Normal Bazzite Desktop KDE / Fedora Atomic |
| Display/login manager | Plasma Login Manager |
| Steam launcher | `/usr/bin/bazzite-steam` |
| Management WebUI port | `9304` |
| Installer | `sudo ./install.sh` |
| Uninstaller | `sudo ./uninstall.sh` |

Ludus does not support Bazzite Deck/Gaming Mode or a separately installed Steam
layout.

The greeter uses KWin's `qt6-controllable` QML module for normalised gamepad
input. The installer layers it when it is not already present.

## Installing It

Run the installer from a local checkout:

```bash
sudo ./install.sh
```

On a fresh installation, the first run layers the required packages into an
rpm-ostree deployment and requires a reboot. Boot that deployment, then run the
same command again to build and activate Ludus. The installer offers to restart
Plasma Login once installation is complete.

The installer builds the custom greeter against the currently installed
`plasma-login-manager` version. It retains a timestamped backup before changing
the active login configuration.

Plasma Login runs in its own Wayland/KWin session and does not inherit a
player's desktop resolution or scale. The WebUI can save a Ludus-owned login
display mode and scale. It is applied to each enabled output when Plasma Login
next starts; unsupported modes are safely left at the output default.

For each enrolled player, Ludus disables Plasma's automatic screen lock and
the AC PowerDevil idle actions (suspend, display dimming, and display blanking)
in that user's configuration. This is per-user and does not change global
system power or lock policy.

## Persistent Data

| Path | Purpose |
|---|---|
| `/usr/local/lib/ludus` | Ludus executables, greeter, UI files, and policy artefacts |
| `/etc/ludus` | Configuration, WebUI settings, login-display settings, MQTT settings, library records, the versioned game-settings policy, and install markers |
| `/var/lib/ludus/backups` | Pre-change login and Steam-autostart backups |
| `/var/lib/ludus/proton-dpi` | Root-private per-player reconciliation state and first-change whole-file audit backups |
| `/var/lib/ludus/launch-options` | Root-private list of players with possible launch-options recovery state, retained on removal |
| `~/.local/state/ludus/launch-options` | Player-private launch-options originals, write journal, and accepted overrides (directory 0700, state 0600), retained on removal |
| `/var/cache/ludus/game-art` | Validated local or official-Steam artwork cached by numeric app ID for the WebUI |
| `/run/ludus` | WebUI backend socket, MQTT status, and transient requests |
| `/run/ludus-mount` | Mount control socket and active-session marker |

The first three paths persist across reboots. The `/run` paths are recreated by
systemd and must not be used for durable configuration.

## Runtime Services

| Unit | Responsibility |
|---|---|
| `ludus-mount.service` | Private Steam bind-mount daemon and active-player pre-Steam Proton DPI and unprivileged launch-options reconciliation |
| `ludus-backend.service` | Privileged WebUI backend socket |
| `ludus-web.service` | HTTP WebUI frontend |
| `ludus-web-firewall.service` | Supported-zone firewall rule management |
| `ludus-mqtt.service` | Optional Home Assistant MQTT integration |

Use `sudo ludusctl doctor` and `journalctl -u <unit> -b` for operational
checks.

## Updates And Recovery

Plasma Login uses private Qt APIs. After a Bazzite update, an old custom
greeter may no longer match the installed packages. The wrapper falls back to
the vendor greeter, so a normal login remains available. After booting the new
deployment, run:

```bash
sudo ./install.sh
```

To remove Ludus and restore normal Plasma Login:

```bash
sudo ./uninstall.sh
sudo systemctl restart plasmalogin
```

If any player prefixes still contain a Ludus-managed Proton DPI value, removal
stops and lists the affected player and app IDs. Disable those settings and let
each listed player complete one login/logout cycle before retrying. An
administrator may deliberately bypass this protection with
`sudo ./uninstall.sh --force`; the listed registry values are then left as-is.

Managed Steam launch options have a similar uninstall check. Use **Remove all
launch management** on the Games page and allow each affected player to log in
and out. Manual conflicts must be resolved or explicitly accepted. `--force`
leaves the current launch options in place and retains recovery records. Players
previously reconciled remain included in the check even after unenrolment;
re-enrol them to complete queued restoration, or deliberately use `--force`.
Reinstallation uses the retained records for subsequent recovery. ScopeBuddy
must already be installed for its preset; Ludus does not install it. No new PAM,
firewall, systemd unit, or SELinux policy is introduced by launch management.
The shared game policy is serialized using `/etc/ludus/game-settings.lock`.

Removal restores Ludus-managed login configuration and removes Ludus config,
but intentionally leaves the `ludus` group, Linux accounts, game data, Steam
library registrations, timestamped backups, and rpm-ostree build dependencies
intact. Review `rpm-ostree status` and deliberately uninstall any dependencies
you no longer need, then reboot.
