<!-- shared: structure — headings kept in sync across Migz93 self-hosted apps, content is app-specific -->

# Ludus Architecture Overview

## What Ludus Is

Ludus turns normal Bazzite Desktop KDE into a controller-first shared lounge
gaming console. It presents a fullscreen player selector, starts the chosen
local Linux user's Plasma Wayland session, and hands off to Steam Big Picture
only after it is ready.

It is deliberately a **single-player** experience: one Ludus player session
may be active at a time. The active player must sign out before another begins.

---

## Core Model

- Each player is a real local Linux account enrolled in the `ludus` group
- The Plasma Login greeter is the controller-friendly entry point
- Passwordless login is scoped to enrolled accounts at that local greeter only
- Steam accounts, Proton prefixes, shader cache, saves, and configuration stay
  private to each player
- Installed game content can live in shared Ludus-managed Steam libraries
- The vendor Plasma Login greeter remains a compatibility fallback

---

## Deployment Model

Ludus is installed directly onto Bazzite Desktop KDE, not run in a container.
The installer builds a Plasma Login greeter matching the installed
`plasma-login-manager` version, then installs Ludus-owned files under:

- `/usr/local/lib/ludus` — executables, greeter, UI assets, and SELinux modules
- `/etc/ludus` — persistent configuration and credentials
- `/var/lib/ludus/backups` — recovery backups made before changing login state
- `/run/ludus` and `/run/ludus-mount` — runtime sockets and state

Systemd services run the controller bridge, mount daemon, WebUI backend and
frontend, firewall helper, and optional MQTT integration.

---

## Login And Session Flow

```text
boot -> Plasma Login -> Ludus player selector
                            | controller bridge -> virtual keyboard
                            v
                   PAM / logind starts selected user
                            v
              Ludus Plasma Wayland session + loading cover
                            v
                    Steam Big Picture via bazzite-steam
```

The custom greeter uses Plasma Login's native authentication/session protocol.
If an operating-system update leaves the version-matched custom greeter unable
to start, `ludus-greeter` starts the vendor greeter instead so the system still
has a usable graphical login.

The loading cover remains above Plasma panels while Steam starts. It waits for
Xwayland and then for the Steam Big Picture window. A player who has not signed
in to Steam on the machine is sent to the normal Plasma desktop to complete
their first Steam login; later Ludus sessions launch Big Picture normally.

---

## Major Subsystems

### Player selection

The custom Plasma Login greeter lists normal local login accounts enrolled in
the `ludus` group. It uses the system display-name and avatar lookup, excludes
system/non-login accounts, and supports keyboard plus common Xbox-style
controller navigation through a virtual keyboard bridge.

### Session launcher

`ludus.desktop`, `ludus-session`, `ludus-overlay`, and `ludus-steam` own the
selected user's Ludus session. They sequence the splash/overlay, private Steam
mount setup, library registration, and Big Picture launch.

### Shared libraries

`ludusctl` manages enrolled users and shared Steam libraries. Game content is
shared with `root:ludus` group ownership and setgid directories; each active
player's `compatdata` and shader cache are bind-mounted from private storage
for that session only. See [shared-libraries.md](shared-libraries.md).

### Management WebUI

The WebUI manages users, libraries, diagnostics, disk adoption, authentication,
and MQTT configuration. Its privileged backend talks to `ludusctl` over a local
Unix socket; the HTTP frontend does not execute administrative commands itself.
See [webui.md](webui.md).

### Home Assistant MQTT

The optional MQTT service publishes Home Assistant discovery and Ludus state,
and accepts tightly constrained player-selection and lifecycle commands. See
[mqtt.md](mqtt.md).

---

## Important Invariants

- Never run more than one Ludus player session at once
- Never expose private Steam data through a shared library
- Require Steam to be stopped before structural library changes
- Keep PAM, SELinux, and firewall changes narrowly scoped and reversible
- Preserve accounts, player home data, game files, and recovery backups on
  removal unless the user explicitly removes them separately
- Treat Bazzite and Plasma Login updates as a reason to rebuild via
  `sudo ./install.sh` after booting the updated deployment
