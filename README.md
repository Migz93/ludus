# Ludus

[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]][license]
[![Project Maintainer][maintainer-shield]][user_profile]
[![Buy me a coffee][buymecoffeebadge]][buymecoffee]

Ludus turns **Bazzite Desktop KDE** into a controller-first, shared lounge
gaming console.

It replaces the normal login experience with a fullscreen player selector,
starts a separate Linux user session for the selected player, and hands off to
Steam Big Picture only after it is ready. Each player retains their own Steam
account, saves, Proton prefixes, settings, and home directory.

## What Ludus Does

- Shows only enrolled local players in a controller-friendly fullscreen selector
- Starts the selected player's normal Plasma Wayland session without exposing
  the usual desktop startup sequence
- Launches Steam Big Picture through Bazzite's supported Steam launcher
- Supports shared Steam game libraries while keeping account and Proton data
  private per player
- Provides a LAN management WebUI for players, libraries, diagnostics, storage,
  and optional Home Assistant MQTT integration

## How It Works

```text
boot -> Ludus player selector -> selected Linux user -> Steam Big Picture
```

The selector uses Plasma Login's native authentication and session protocol.
Ludus builds a version-matched copy of the Plasma Login greeter under
`/usr/local/lib/ludus`; if a Bazzite update makes it incompatible, the wrapper
falls back to the vendor greeter so the machine still has a usable graphical
login. The vendor greeter also remains in use until a normal local player is
enrolled in the `ludus` group.

The loading cover stays above Plasma panels while Steam starts. It waits for
Xwayland and the Steam Big Picture window before handing over control. A player
who has never signed in to Steam on the machine is sent to the normal Plasma
desktop once to finish initial Steam setup.

## Key Features

- Separate real Linux accounts for every player
- Passwordless graphical login narrowly scoped to enrolled Ludus users
- Xbox-style controller navigation, with mouse support
- Single active player session, avoiding user-switching and shared-library races
- Shared installed game files with private Steam account state, Proton prefixes,
  shader cache, and saves
- Safe library validation and repair through the WebUI or `ludusctl`
- Management WebUI with PAM administrator authentication by default
- Optional Home Assistant MQTT Discovery, player selection, status, and
  lifecycle controls
- Native KWin controller navigation, with mouse support

## Quick Start

### Requirements

- Normal **Bazzite Desktop KDE** — not Bazzite Gaming Mode / Deck mode
- Plasma Login Manager
- The Bazzite-provided `/usr/bin/bazzite-steam` launcher
- A local checkout of this repository
- One or more normal Linux accounts to enrol as players

### Install

Run from the local checkout:

```bash
sudo ./install.sh
```

On a fresh Bazzite installation, the first run stages required build
dependencies in one rpm-ostree deployment and offers to reboot. After booting
the new deployment, run the same command again to complete installation.

The installer creates the `ludus` group, installs the login/session services,
builds the version-matched greeter, and retains a timestamped backup before
changing active login configuration.

### Enrol Players

Only normal local login accounts in the `ludus` group appear in the selector.
For example:

```bash
sudo usermod -aG ludus miguel
sudo usermod -aG ludus steph
```

Alternatively, use the WebUI after installation. Players must sign out and
back in after their group membership changes.

### Open The WebUI

The installer starts the management WebUI on port `9304`:

```text
http://<ludus-hostname-or-LAN-IP>:9304/
```

It defaults to local `wheel` administrator PAM authentication. The built-in
server is HTTP-only, so access it only on a trusted wired LAN, authenticated
VPN, or behind a TLS-terminating reverse proxy. Never expose it directly to the
internet.

## Shared Steam Libraries

Ludus shares installed game files, not Steam ownership: every player still
needs the relevant entitlement on their own Steam account.

Steam's mandatory library in `~/.local/share/Steam` remains private because it
contains the Steam client, account state, and other player-specific data. Install
games into Ludus-managed shared libraries instead. They use `root:ludus`
ownership with group-write/setgid permissions, while `compatdata` and shader
cache are privately bind-mounted for the active player only.

Use the WebUI or `sudo ludusctl` to add, validate, repair, label, and select
libraries. See [Shared Steam Libraries](docs/shared-libraries.md) for the full
model and safety rules.

## Home Assistant MQTT

The optional MQTT integration is configured from the WebUI's **MQTT** page. It
uses Home Assistant MQTT Discovery to expose player selection, session status,
active-player status, lifecycle/error sensors, and one-shot sign-out, restart,
and shutdown buttons.

Use a dedicated broker account with tightly scoped topic permissions. Anyone
who can publish Ludus commands can start an enrolled account, sign out the
active player, or power-cycle the PC. See [Home Assistant MQTT](docs/mqtt.md).

## Important Limitations

- Only one Ludus player session can be active at a time; players must sign out
  before another player signs in.
- Steam readiness is detected through its Xwayland Big Picture window, which may
  need adjustment if Steam changes its behaviour.
- Final GPU, HDMI/VRR, and physical-controller validation must happen on target
  hardware.
- The WebUI is not a public-facing service and does not provide built-in TLS.

## Documentation

Technical and operational documentation lives in [docs/](docs/README.md),
including the [architecture](docs/architecture.md),
[deployment](docs/deployment.md), [WebUI](docs/webui.md), and current
[status](docs/status.md).

## AI Transparency

Ludus was created with heavy AI assistance.

Claude, Codex, and CodeRabbit were used throughout the project for design
exploration, implementation help, refactoring, review, explanation, and
iteration. The intent is not to hide that. Ludus has been built by combining
hands-on product direction with AI-assisted development work.

[buymecoffee]: https://www.buymeacoffee.com/Migz93
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge
[commits-shield]: https://img.shields.io/github/commit-activity/y/Migz93/ludus.svg?style=for-the-badge
[commits]: https://github.com/Migz93/ludus/commits/main
[license]: https://github.com/Migz93/ludus/blob/main/LICENSE
[license-shield]: https://img.shields.io/github/license/Migz93/ludus.svg?style=for-the-badge
[maintainer-shield]: https://img.shields.io/badge/maintainer-Migz93-blue.svg?style=for-the-badge
[user_profile]: https://github.com/Migz93
