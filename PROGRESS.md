# Ludus progress

Updated: 2026-08-26

## Goal

Ludus turns Bazzite KDE into a controller-first shared lounge console. One
player session is active at a time; players sign out before another player
starts their Ludus session.

## Phase 1: player selection and Steam launch

Implemented on the Bazzite VM:

- A custom Plasma Login greeter shows only members of the `ludus` group and
  starts their normal Plasma Wayland session through `ludus.desktop`.
- Player cards support mouse click selection and keyboard Left/Right/Enter.
  The controller bridge maps common gamepad Left/Right/A input to those keys.
- The locally built greeter is version-matched to the installed Plasma Login
  package; the vendor greeter remains a compatibility fallback.
- A Ludus splash launches Steam Big Picture through Bazzite's launcher. If
  Big Picture does not become ready, the splash now offers **Exit to desktop**
  (and Escape) so the user is never trapped behind an overlay.
- The root mount daemon has its own `/run/ludus-mount` runtime directory. This
  avoids the prior failure where a WebUI backend restart deleted its socket.

### Controller navigation: ready to validate

- The controller bridge now has a dedicated `ludus_controller_t` SELinux
  domain. It is limited to reading physical input devices, writing `/dev/uinput`,
  and checking whether the greeter is active; only the bridge executable is
  labelled for this transition.
- Install and validate on the enforcing Bazzite VM with a real controller:
  Left/Right/A navigation at the greeter, service restart behaviour, and a
  clean AVC log with no broad allow rules.

## Phase 2: shared Steam libraries

Implemented on the Bazzite VM:

- `ludusctl` manages shared libraries, enrolled users, safe repair, and a
  conservative migration workflow.
- Shared content is `root:ludus`, group-writable, and setgid. Proton
  `compatdata` and shader caches are private per player under their home.
- A user who has not completed their first Steam login is shown as awaiting
  Steam setup. Ludus defers their private-library and Steam-VDF work until the
  next Ludus launch after that first login.
- Steam registrations are written to both Bazzite Steam VDF locations. Global
  shared libraries can be selected as Steam's default library; each
  Steam-ready user is updated immediately and later users inherit the choice.
- The Libraries UI distinguishes global Ludus libraries from a user's personal
  Steam library registrations. Removing a personal registration only edits the
  Steam VDF files (with backups); it never deletes games or user data.
- The Tools UI can adopt an existing unmounted ext4, XFS, or Btrfs partition,
  persist it in `/etc/fstab`, and defaults the friendly mount path to
  `/mnt/games` while allowing an absolute-path override. UUIDs remain the
  persistent filesystem identity.
- Miguel's shared libraries are `/var/srv/steam-library` on the Bazzite
  system disk and `/var/mnt/games/steam-library` on the additional disk. The
  former is selected as Miguel's Steam default; the latter remains available
  for larger games.
  Steam's mandatory per-user home library is labelled **DO NOT USE** and is
  retained for client/account data. Both enrolled users have verified access
  to both shared paths. Steam/Big Picture launch with the library arrangement
  has been verified for Miguel; Steph still needs their first Steam login.
- New shared libraries no longer need one manual Steam Storage setup. Ludus
  creates a unique numeric `libraryfolder.vdf` content ID and writes matching
  user registrations; an empty automatic-library test was accepted by Steam
  through a full launch/shutdown cycle and then removed. Shared-library labels
  are editable in the WebUI and persist through Steam launch. The current
  labels are `SSD` for the system-disk library and `NVME` for the additional
  disk.

Still to validate later:

- Install, launch, update, and uninstall real shared games as Miguel and then
  Steph.
- Complete Steph's first Steam login and validate deferred registration.
- Exercise populated-library migration, Workshop content, Proton/shader
  isolation, repair, reboot persistence, uninstall, and Bazzite-update
  recovery.

## Phase 2: WebUI

Implemented on the Bazzite VM:

- The WebUI uses an unprivileged service and a root backend with an explicit
  operation allow-list over a peer-credential-checked Unix socket.
- Authentication can be configured in Settings as none, PAM (`wheel` users),
  a local Ludus account, or both. The default is no WebUI credential.
- Settings also has an opt-in narrow SELinux compatibility policy for VS Code
  Remote SSH TCP forwarding; it is off by default.
- The UI includes Dashboard, Users, Global/User Libraries, Disk Tools,
  Health/Repair, and Settings.
- WebUI access from another LAN device has been verified. Firewalld opens only
  the WebUI port in the existing active zone; it never assigns a whole LAN
  source range to a custom Ludus zone. The WebUI also restricts requests to
  loopback and directly connected private LANs.

### Doctor and diagnostics: ready to validate

- `ludusctl doctor` no longer checks the obsolete `ludus` firewalld zone. It
  reports the recorded active firewall zone, mount sources/filesystems, private
  bind state, Steam registrations/defaults, SELinux mode/policy/label, service
  health, and whether Steam is running for each player.
- `ludusctl doctor --json` emits the same checks as structured records with a
  stable `code`, `group`, `subject` and `data`. Every diagnostic goes through
  one `report` function, so the text output is the `message` field verbatim and
  the two modes cannot drift. `ludus-steam-user-libraries check-records`
  supplies the Steam registration records the same way.
- `ludusctl storage` reports per-library capacity and free space as JSON via
  the read-only `ludus-storage` helper. It changes nothing.
- Validate its output on the Bazzite VM in both idle and active-player states.

### WebUI redesign: ready to validate

The WebUI is now a desktop-browser management dashboard rather than a command
output viewer. It is still one self-contained page with no framework, build
step, CDN or external icon service.

- The markup, stylesheet and script live in `src/web/` and are inlined into a
  single document once at start-up. No request path is mapped onto the
  filesystem, so no static file server was added.
- Sections are Dashboard, Players, Shared libraries, Disk tools, Health &
  repair and Settings, reachable by hash routes and keyboard.
- Health checks come from `ludusctl doctor --json` and are rendered as grouped
  rows with a plain English title, an explanation and a per-row technical
  disclosure. The copy is keyed by the stable check code, so rewording a
  diagnostic on the machine cannot silently change what the page says. An
  install whose `ludusctl` predates the structured output falls back to parsing
  the text form and renders identically. Raw output stays behind an Advanced
  diagnostic output disclosure.
- Per-library free space comes from `ludusctl storage`, and partition sizes
  from the `SIZE` column now requested in `ludus-disks`. Both degrade quietly
  when unavailable.
- Browser `confirm()` is gone. Destructive and persistent changes use an
  in-page dialog that reviews exactly what will happen and states what is not
  touched. Disk adoption uses a review-and-confirm dialog.
- Every pre-existing operation and API route is unchanged. Authentication,
  privilege separation, disk-safety rules, Steam/library behaviour and firewall
  behaviour were not modified. Two read-only operations were added to the
  backend allow-list, `doctor.json` and `storage`; both take no argument and
  change no system state.
- The page response adds a Content-Security-Policy with a per-request script
  nonce, plus `Referrer-Policy: no-referrer`. Both are additive hardening.

Validate on the Bazzite VM in idle and active-player states, and confirm that
every doctor line is recognised rather than falling back to raw text.

### Planned WebUI refinement

Still outstanding from that pass:

- Migration controls for populated libraries. `ludusctl libraries migrate` and
  the `libraries.migrate` backend operation exist, but nothing in the WebUI
  reaches them yet.

## Other remaining work

- Add a GPL-3.0-or-later licence file and retain applicable upstream notices.
- Improve WebUI authentication with sessions and rate limiting if the project
  later needs stronger LAN-facing security.
