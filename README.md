# Ludus

Ludus is an experimental, controller-first multi-user launcher for **Bazzite Desktop KDE**. It presents a console-style player selector, starts a separate Linux user session for the selected player, and hands off to Steam Big Picture only after it is ready.

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

On a fresh Bazzite installation, the first run stages build dependencies with rpm-ostree and exits without changing the login stack. Reboot into that deployment, then run the installer again.

The installer:

- builds against the currently installed `plasma-login-manager` version;
- installs files under `/usr/local/lib/ludus`, `/etc/ludus`, and `/var/lib/ludus/backups/`;
- creates the `ludus` group for enrolled users;
- installs `ludus.service`, the `ludus.desktop` session, and `/etc/pam.d/plasmalogin-ludus`;
- retains a timestamped backup before changing active login configuration.

After installing, restart Plasma Login or reboot:

```bash
sudo systemctl restart plasmalogin
```

## Management WebUI

The installer starts the authenticated management service on port `9876` and
opens it only to the directly connected private IPv4 subnet. It refuses to add
a firewall opening when that subnet cannot be identified as private. It prints a one-time initial `admin` password. Open
`http://<ludus-hostname-or-LAN-IP>:9876/` from a trusted home-network device.
The WebUI can enrol/remove players, manage existing shared-library directories,
run safe repair checks, and rotate its own credentials. Removing a player or
library never deletes a Linux account, game files, or home data.

The current service intentionally uses HTTP Basic authentication as its first
transport boundary. Do not expose it to the Internet; session/rate-limit
hardening remains to be completed.

## Update behavior

Plasma Login uses Qt private APIs, so an OS update can require rebuilding Ludus. If the old custom greeter cannot load, the Ludus wrapper automatically falls back to Bazzite's stock Plasma Login greeter. Re-run `sudo ./install.sh` after booting the new deployment to rebuild Ludus for the updated Plasma version.

## Removal and recovery

```bash
sudo ./uninstall.sh
sudo systemctl restart plasmalogin
```

The uninstaller removes Ludus configuration and restores normal Plasma Login. It leaves the `ludus` group and user accounts intact. If graphical login is unavailable, use SSH or a local TTY to run the command.

## Current limitations

- Steam readiness is detected through its Xwayland Big Picture window; Steam may change this in future.
- The VM cannot validate final GPU, display, HDMI/VRR, or controller behavior.
- On the current SELinux-enforcing test VM, the controller bridge is denied access to `/dev/uinput`; it now fails once rather than looping. A narrowly scoped device-access policy is still needed before controller remapping can be enabled and validated there.
- Player switching from Steam is not supported.  A player must sign out before
  another Ludus user can sign in.

See [Phase1.md](Phase1.md) for the original Phase 1 brief.
