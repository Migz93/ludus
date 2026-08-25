# Ludus

Ludus is an experimental, controller-first multi-user launcher for **Bazzite Desktop KDE**. It presents a console-style player selector, starts a separate Linux user session for the selected player, and hands off to Steam Big Picture only after it is ready.

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
- Player switching from Steam is planned for a later phase.

See [Phase1.md](Phase1.md) for the original Phase 1 brief.
