# Ludus progress

Updated: 2026-08-27

## Goal

Ludus turns Bazzite KDE into a controller-first shared lounge console. One
player session is active at a time; players sign out before another player
starts their Ludus session.

## Phase 1: player selection and Steam launch

Implemented on the Bazzite VM:

- A custom Plasma Login greeter shows only members of the `ludus` group and
  starts their normal Plasma Wayland session through `ludus.desktop`.
- Player cards support mouse click selection and keyboard Left/Right/Enter.
  Display names use one blue colour; the selected card has a close pulsing
  glow ring, and hovering a card moves the same selection used by keyboard
  and controller navigation. The controller bridge maps common gamepad
  Left/Right/A input to those keys.
- The locally built greeter is version-matched to the installed Plasma Login
  package; the vendor greeter remains a compatibility fallback.
- A Ludus splash launches Steam Big Picture through Bazzite's launcher. If
  Big Picture does not become ready, the splash now offers **Exit to desktop**
  (and Escape) so the user is never trapped behind an overlay.
- The root mount daemon has its own `/run/ludus-mount` runtime directory. This
  avoids the prior failure where a WebUI backend restart deleted its socket.

### Controller navigation

- The controller bridge runs in a dedicated `ludus_controller_t` SELinux
  domain. The policy was updated for current Bazzite/Fedora device labels
  (`event_device_t`) and now declares the required executable and system-role
  attributes. The bridge is correctly labelled, active, and has `/dev/uinput`
  open; `ludusctl doctor --json` reports the controller policy and label as
  healthy under enforcing SELinux.
- Still validate Left/Right/A navigation with a real connected controller at
  the greeter.

## Phase 2: shared Steam libraries

Implemented on the Bazzite VM:

- `ludusctl` manages shared libraries, enrolled users, and safe repair.
- Shared content is `root:ludus`, group-writable, and setgid. Proton
  `compatdata` and shader caches are private per player under their home.
- A user who has not completed their first Steam login is shown as awaiting
  Steam setup. Ludus opens that user at the normal desktop rather than trying
  Big Picture; after they sign in to Steam once, their private-library and
  Steam-VDF work runs at the next Ludus launch.
- Steam registrations are written to both Bazzite Steam VDF locations. Ludus
  records the administrator's preferred shared library, but Steam's actual
  default install choice remains per user and is selected in Steam's Storage
  UI.
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
  retained for client/account data. The shared paths have the required group
  access; Steam/Big Picture launch with this arrangement has been verified for
  Miguel and Steph. Steph completed her first normal-desktop Steam sign-in,
  then her next Ludus session entered Big Picture with both shared libraries
  registered and Miguel's installed games visible.
- New shared libraries no longer need one manual Steam Storage setup. Ludus
  creates a unique numeric `libraryfolder.vdf` content ID and writes matching
  user registrations; an empty automatic-library test was accepted by Steam
  through a full launch/shutdown cycle and then removed. Shared-library labels
  are editable in the WebUI and persist through Steam launch. The current
  labels are `SSD` for the system-disk library and `NVME` for the additional
  disk.

Validated on the Bazzite VM:

- A real shared game was installed and uninstalled by each player in turn.
  It appeared correctly for the other player in both directions, confirming
  the shared-library registration and visibility path for Miguel and Steph.
- Shared libraries persisted through multiple reboots.
- The Ludus uninstaller was exercised successfully.
- Miguel and Steph each launched the same shared native game, **Unpacking**.
  Steph received a clean **New Game** state rather than Miguel's **Resume**
  state, and her shader cache was created under her own Ludus directory.
- Miguel and Steph each launched the same shared Proton game, **Ravenous
  Devils**. Each received a separately owned `compatdata/1615290/pfx` and
  shader cache in their own home directory. The game exited after a black
  screen in the software-rendered VM, as expected without a physical GPU.
- During both active-player sessions, `ludusctl doctor --json` confirmed that
  all four shared-library private binds pointed only at that active player's
  own directories. The doctor now resolves Bazzite's equivalent `/home` and
  `/var/home` spellings before comparing bind targets.
- A Steam-created `steamapps/downloading` directory initially lacked
  group-write access for the second player. Library repair now skips Steam
  Runtime read-only mounts while continuing the repair, and Ludus launches
  Steam with umask `0002` so future shared downloads and game files retain
  group-write access. Steph successfully wrote to the repaired directory.

Still to validate later:

- No further scheduled shared-library validation. Test game updates and
  Bazzite-update recovery opportunistically when those events occur.

### Installer and removal lifecycle

- The installer now declares all build and SELinux tooling it invokes, tracks
  every Steam autostart entry it takes over (including users later enrolled
  through the WebUI), and preserves the original file for restoration.
- The uninstaller restores those tracked autostart entries, removes the
  installer-created `ludus-web` service account and group, and removes only
  clearly marked `/etc/fstab` records created by Ludus disk adoption. It
  deliberately retains users, the `ludus` group, games, Steam registrations,
  mounted disks, and timestamped recovery backups.
- The obsolete, uncalled Steam VDF `make-default` implementation was removed.

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

### Doctor and diagnostics

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
- In the idle state, root's `ludusctl doctor --json` returned 32 healthy
  records and exit status zero. This covered all services, firewall access,
  both shared-library mounts and bind targets, both players' Steam
  registrations, SELinux, controller policy, and the optional VS Code policy.
- In active Miguel and Steph sessions, doctor correctly reported the active
  player and all four private bind sources. Validate storage output while a
  player session is active.
- In the idle state, `ludusctl storage` returned valid capacity records for
  both configured shared libraries.

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

Validate the dashboard in an active-player state, and confirm that every
doctor line is recognised rather than falling back to raw text.

## Other remaining work

- The repository now includes the GPL-3.0-or-later licence text. Retain
  applicable upstream notices as the project incorporates upstream work.
