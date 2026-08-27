<!-- shared: structure — keep headings aligned across Migz93 self-hosted apps -->

# Deployment

## Target System

| Thing | Value |
|---|---|
| Supported OS | Normal Bazzite Desktop KDE / Fedora Atomic |
| Display/login manager | Plasma Login Manager |
| Steam launcher | `/usr/bin/bazzite-steam` |
| Management WebUI port | `9876` |
| Installer | `sudo ./install.sh` |
| Uninstaller | `sudo ./uninstall.sh` |

Ludus does not support Bazzite Deck/Gaming Mode or a separately installed Steam
layout.

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

## Persistent Data

| Path | Purpose |
|---|---|
| `/usr/local/lib/ludus` | Ludus executables, greeter, UI files, and policy artefacts |
| `/etc/ludus` | Configuration, WebUI settings, MQTT settings, library records, and install markers |
| `/var/lib/ludus/backups` | Pre-change login and Steam-autostart backups |
| `/run/ludus` | WebUI backend socket, MQTT status, and transient requests |
| `/run/ludus-mount` | Mount control socket and active-session marker |

The first three paths persist across reboots. The `/run` paths are recreated by
systemd and must not be used for durable configuration.

## Runtime Services

| Unit | Responsibility |
|---|---|
| `ludus.service` | Controller bridge while the greeter is active |
| `ludus-mount.service` | Private Steam bind-mount daemon |
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

Removal restores Ludus-managed login configuration and removes Ludus config,
but intentionally leaves the `ludus` group, Linux accounts, game data, Steam
library registrations, and timestamped backups intact.
