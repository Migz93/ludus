# Management WebUI

## Access Model

The management WebUI listens on port `9304`. It is intended for a trusted wired
LAN, authenticated VPN, or TLS-terminating reverse proxy — never exposure to
the public internet or an untrusted Wi-Fi network.

The service only opens the port in a `home`, `internal`, `trusted`, or
`FedoraWorkstation` firewalld zone. The HTTP server accepts loopback and
directly connected private IPv4 subnets. If the active zone is unsupported,
configure it before enabling LAN access.

The built-in server is HTTP-only. HTTP Basic/PAM credentials are plaintext on
the network without an external TLS layer.

## Authentication

The default authentication mode is PAM for local `wheel` administrators. Sign
in with that administrator's regular Linux password. Settings can instead use a
local Ludus account or allow either method. A successful PAM sign-in is
remembered in memory for 15 minutes after the most recent request from the same
address and credentials. Parallel requests share one PAM check instead of being
refused by the per-address retry interval.

The frontend sends requests to the unprivileged HTTP service; it passes
privileged operations to the backend via `/run/ludus/backend.sock`. Do not add
an HTTP endpoint that directly shells out or bypasses the backend's validation.
The backend serves up to 16 connections in parallel. Listed read-only
operations may overlap each other; every other operation runs alone, as when
the backend handled one request at a time. PAM checks take no lock. A new read
operation must be added to the backend's shared set explicitly.

## Capabilities

- enrol and remove players without deleting Linux accounts or home data
- manage shared-library records, labels, validation, and safe repair
- view installed Steam games discovered from managed shared-library manifests;
  malformed and duplicate records are shown without changing them; the poster
  grid uses validated local or official-Steam art from a separate Ludus cache
- configure the disabled-by-default console-wide Proton overlay DPI repair and
  per-game inherit/disabled/override policy; game details show each player's
  latest reconciliation, including missing prefixes and queued restorations
- manage console-wide ScopeBuddy launch defaults and per-game overrides, with
  Adaptive native, fixed-resolution upscale, or Custom profiles, game arguments,
  and a managed command preview; per-game fields appear only for an explicit
  override, and Follow default clears them when saved; see each player's state,
  replace or accept manual conflicts, resume management, or queue restoration
  (including games no longer in the inventory)
- inspect Ludus services, mounts, storage, and `ludusctl doctor` results on the
  Dashboard and Health pages
- adopt an existing compatible disk without deleting its data; Ludus grants
  the player group traversal-only access at the filesystem root so a later
  shared library remains reachable without exposing file contents
- rotate WebUI credentials and configure permitted authentication modes
- choose the resolution, refresh rate, and UI scale used by the next Plasma
  Login greeter session
- configure and test the optional Home Assistant MQTT integration

## Operational Checks

Run `sudo ludusctl doctor` to check the configuration, service sockets,
firewall state, Steam launcher, mount state, and SELinux policy. The WebUI
presents the same structured `ludusctl doctor --json` information.

Launch policy reads and writes use authenticated `/api/games/launch-options`
requests through the privileged backend. Saving policy never edits an active
Steam configuration; those writes wait for the affected player's next login.
Accepting an override or resuming management updates only recovery state. See
[shared-libraries.md](shared-libraries.md#managed-launch-options) for ownership,
argument composition, and restoration semantics.

The Games page groups the console-wide Proton DPI and Steam launch controls in
**Global Settings**, collapsed by default. ScopeBuddy's global fields are hidden
while its switch is off. Filter and sharpness appear only for upscale profiles,
and **ScopeBuddy Arguments** only for Custom. The **Game launch command** is
shown on its own line. Game details show a separate **Player application**
section before Steam launch settings. It lists each enrolled player with one
state each for Proton overlay DPI and Steam launch options: Applied, Pending
apply, Pending restore, Restored, Not managed, or Not installed, plus Conflict,
Manual override, Unavailable, or Error where they apply. Error detail is shown
on hover. Conflicts offer **Replace temporarily** and **Accept manual
override**; accepted overrides offer **Resume management**. Player application
appears only on specific game pages, not on the overall Games page.
