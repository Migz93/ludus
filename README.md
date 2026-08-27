# Ludus

Ludus is an experimental, controller-first multi-user launcher for **Bazzite Desktop KDE**. It presents a console-style player selector, starts a separate Linux user session for the selected player, and hands off to Steam Big Picture only after it is ready.

Ludus is licensed under [GNU GPL v3.0 or later](LICENSE).

Ludus is a single-player console experience: only one Ludus user session may be
active at a time.  A player must sign out before another player signs in; it
does not support concurrent player sessions or in-session user switching.

Shared Steam libraries are a Phase 2 feature in progress.  They share installed
files, not Steam ownership: every player still needs the relevant entitlement
on their own Steam account to launch a game.

## Shared Steam libraries

Each player must retain Steam's mandatory library in their own home directory:
`~/.local/share/Steam`. It contains the Steam client, account state, and other
private data, so Ludus labels it **DO NOT USE** rather than removing it.

Install games into a Ludus-managed shared library instead. Shared libraries use
`root:ludus` ownership with group-write and setgid permissions, while their
`steamapps/compatdata` and `steamapps/shadercache` paths are bind-mounted to
the active player's private directories only for that player's session. Every
parent directory of a shared library must also be traversable by all members of
the `ludus` group; Ludus diagnostics check this.

When creating a new shared library, Ludus creates Steam's
`libraryfolder.vdf` marker with a unique positive numeric content ID, then
registers the same path, ID, and optional label in every Steam-ready player's
two `libraryfolders.vdf` files. Steam accepts this automatic setup; manually
adding the path in Steam's Storage UI is not required. Library labels can be
managed from the WebUI and are propagated to each Steam-ready player.

Ludus records the administrator's preferred shared library in
`/etc/ludus/default-library.conf`. Steam keeps the actual default install
choice per player, so select that library in Steam's Storage UI for each
Steam-ready player. Additional shared libraries remain available as alternate
install locations.

## Phase 1 status

This project has been tested on the Bazzite KDE VM with Plasma Login Manager and Wayland. It uses normal Bazzite Desktop Plasma—not the Bazzite Deck/Gaming Mode image—and launches `/usr/bin/bazzite-steam steam://open/bigpicture` inside the selected user's normal Plasma Wayland session.

Ludus builds a version-matched copy of Plasma Login's greeter in `/usr/local/lib/ludus`; vendor packages are not modified. The greeter uses Plasma Login's native authentication and session protocol, while a fallback wrapper starts the vendor greeter if an OS update makes the custom binary incompatible. This prevents an incompatible upgrade from leaving a blank login display.

## Architecture

```text
boot -> plasmalogin -> Ludus player selector
                         |  ludus.service: controller -> virtual keyboard
                         v
                    PAM / logind starts selected user
                         v
              Ludus Plasma Wayland session + loading cover
                         v
                     Steam Big Picture Mode
```

The loading cover stays above Plasma panels while Steam starts. It waits for Xwayland before launching Steam, then only clears after the Steam Big Picture window is detected.
For a player who has never signed in to Steam on this machine, Ludus opens the
normal Plasma desktop without starting Steam; they should open Steam normally,
sign in once, then sign out and use Ludus normally thereafter.

## Enrolled users

Only normal local login accounts enrolled in the `ludus` group are listed. This explicit membership also narrowly scopes passwordless login to the local Plasma Login greeter; it does not affect SSH, sudo, root, or other PAM services.

```bash
sudo usermod -aG ludus miguel
sudo usermod -aG ludus steph
```

The player selector uses Plasma's real display name and avatar lookup. System accounts, non-login shells, and users outside the `ludus` group are excluded.

## Controller controls

`ludus.service` creates a virtual keyboard only while the greeter runs. It maps D-pad/left stick to Left/Right and Xbox A (`BTN_SOUTH`) to Enter. Keyboard arrows and Enter are available as a fallback.

Use `sudo journalctl -u ludus.service -b` to inspect controller detection. Physical-controller validation remains a Phase 1 hardware test item.

## Installation

Run from a local checkout:

```bash
cd ludus
sudo ./install.sh
```

On a fresh Bazzite installation, the first run stages every build dependency
(including the optional MQTT client) in one rpm-ostree deployment and makes no
login changes. It offers to reboot; after booting back in, run the same command
again. The second run completes the installation and offers to restart Plasma
Login, which activates Ludus without another full reboot. Non-interactive runs
print the exact reboot or Plasma Login restart command instead.

The installer:

- builds against the currently installed `plasma-login-manager` version;
- installs files under `/usr/local/lib/ludus`, `/etc/ludus`, and `/var/lib/ludus/backups/`;
- creates the `ludus` group for enrolled users;
- installs `ludus.service`, the `ludus.desktop` session, and `/etc/pam.d/plasmalogin-ludus`;
- retains a timestamped backup before changing active login configuration.

If you decline the final prompt, activate Ludus later with:

```bash
sudo systemctl restart plasmalogin
```

## Management WebUI

The installer starts the management service on port `9876`. It only opens the
firewall port in a `home`, `internal`, `trusted`, or Bazzite's default
`FedoraWorkstation` firewalld zone; the WebUI itself also admits only loopback
and directly connected private IPv4 subnets. If the active zone is not one of
those supported zones, configure it before enabling LAN access. The built-in
server is HTTP-only: HTTP Basic/PAM
credentials are plaintext on the network. Use it only through a trusted wired
LAN, an authenticated VPN, or a TLS-terminating reverse proxy—never ordinary
Wi-Fi or an untrusted network. Open
`http://<ludus-hostname-or-LAN-IP>:9876/` only when one of those protections
is in place.
The WebUI can enrol/remove players, manage existing shared-library directories,
run safe repair checks, and rotate its own credentials. Removing a player or
library never deletes a Linux account, game files, or home data.

The WebUI defaults to PAM authentication for local `wheel` (administrator)
members. Sign in with that administrator account's normal Linux password.
The WebUI is restricted to loopback and the directly connected private LAN.
Settings can instead select a local Ludus account or accept either method. Do
not expose it to the Internet. Re-running the installer upgrades an older
unauthenticated WebUI configuration to the PAM administrator default.

## Home Assistant MQTT

The optional MQTT integration is configured from the WebUI's **MQTT** page.
It uses Home Assistant MQTT Discovery to create a Ludus device with a player
selector, session-active and active-player status, lifecycle/error sensors,
and one-shot Sign out, Restart, and Shut down buttons. The selector includes
`Inactive` plus the currently enrolled Ludus users.

Selecting a player publishes a retained request, so it can be made before the
PC is powered on. Once the machine reaches the Ludus greeter, it consumes the
request, starts that selected user's normal Ludus session, and resets the
selector to `Inactive`. Selecting `Inactive` before then clears the pending
request. Requests expire after two minutes once handed to the greeter and are
rejected whenever another Ludus session is active.

Only player-selection messages may be retained. Sign out, restart, and shut
down commands must be non-retained MQTT button messages with payload `PRESS`;
Ludus rejects and clears retained lifecycle commands to prevent replay after a
reconnect or reboot.

Use a dedicated broker account with narrowly scoped topic permissions. Anyone
allowed to publish Ludus commands can start an enrolled account without its
password, sign out the active player, or power-cycle the PC. Keep MQTT on your
trusted network; use TLS where your broker supports it and access Home
Assistant remotely through your usual VPN or other secured route.

## Update behavior

Plasma Login uses Qt private APIs, so an OS update can require rebuilding Ludus. If the old custom greeter cannot load, the Ludus wrapper automatically falls back to Bazzite's stock Plasma Login greeter. Re-run `sudo ./install.sh` after booting the new deployment to rebuild Ludus for the updated Plasma version.

## Removal and recovery

```bash
sudo ./uninstall.sh
sudo systemctl restart plasmalogin
```

The uninstaller removes Ludus configuration and restores normal Plasma Login. It
also restores any Steam autostart entries that Ludus changed, removes its
installer-created WebUI service account, and removes only the clearly marked
`/etc/fstab` entries created when Ludus adopted a disk. It deliberately leaves
the `ludus` group, user accounts, game data, Steam library registrations, and
timestamped recovery backups in `/var/lib/ludus/backups/` intact. If graphical
login is unavailable, use SSH or a local TTY to run the command.

## Current limitations

- Steam readiness is detected through its Xwayland Big Picture window; Steam may change this in future.
- The VM cannot validate final GPU, display, HDMI/VRR, or controller behavior.
- Player switching from Steam is not supported.  A player must sign out before
  another Ludus user can sign in.

See [Phase1.md](Phase1.md) for the original Phase 1 brief.
