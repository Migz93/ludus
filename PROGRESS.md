# Ludus progress

Updated: 2026-08-25

## Goal

Ludus turns Bazzite Desktop KDE into a controller-first, shared lounge console.
It supports one active player session at a time: the player signs out before a
different player signs in.

## Phase 1: player selection and Steam launch

Implemented and tested on the Bazzite KDE VM:

- A custom Plasma Login greeter displays only users enrolled in the `ludus`
  Linux group.
- The greeter is built against the installed Plasma Login version and installed
  separately under `/usr/local/lib/ludus`; the vendor greeter remains intact as
  a fallback.
- Selecting a user starts their normal Plasma Wayland session without exposing
  the usual desktop-login flow.
- A Ludus loading overlay starts Steam through Bazzite's `/usr/bin/bazzite-steam`
  launcher and waits for Big Picture readiness.
- `ludus.service` provides controller-to-virtual-keyboard navigation at the
  greeter.
- The installer is Bazzite-only, uses `rpm-ostree` for build dependencies, keeps
  timestamped backups, and is intended to be re-runnable.

Known Phase 1 limitation:

- SELinux currently denies the controller bridge access to `/dev/uinput` on the
  enforcing VM. The bridge therefore cannot yet be fully validated with a
  physical controller. A narrow SELinux policy is still required.

## Phase 2: shared Steam libraries

### Implemented foundation

- `ludusctl` provides shared-library administration:
  - `status` / `doctor`
  - enrolled-user listing, enrolment, and removal
  - add, list, remove, check, repair, and conservative migration of libraries
- Library configuration is stored in `/etc/ludus/libraries.conf`.
- Multiple libraries are supported.
- Shared content is `root:ludus`, group-writable, and setgid so new content
  retains the Ludus group.
- The unmounted `compatdata` and `shadercache` targets are `root:root` mode
  `000`; real private directories live under each user's home and remain owned
  by that user.
- Library-changing operations refuse to run while Steam is active.
- Library paths are validated so every enrolled user can traverse their parent
  directories; `/var/lib/ludus` is intentionally rejected as a library location
  because it is root-private.

### Bazzite/SELinux design and validation

The first PAM-based implementation was blocked by SELinux because PAM helpers
run in the display-manager domain and cannot enter the host mount namespace.
It was replaced with a safer structure:

```text
Ludus Steam launcher (selected user)
        -> local Unix socket
Ludus root mount service
        -> host-namespace bind mounts
```

- `ludus-mount.service` owns the privileged mounts.
- The local socket is restricted to the `ludus` group and derives the requesting
  user from peer credentials rather than accepting a username from the client.
- The service enforces one active Ludus user at a time.
- On Steam exit/sign-out, the launcher requests clean unmounting.

Validated on the Bazzite VM with SELinux enforcing:

- Miguel's `compatdata` and shader-cache paths were bind-mounted into the
  disposable test library while Steam Big Picture was running.
- Both unmounted cleanly when Miguel signed out.
- The active-user guard rejected another user's concurrent mount request.
- No fresh Ludus SELinux AVC denial was recorded for this design.

### Steam registration

- Ludus registers every configured shared library before Steam starts.
- Bazzite Steam uses both `config/libraryfolders.vdf` and
  `steamapps/libraryfolders.vdf`; Ludus updates both.
- Steam retained the test library registration and generated a real Steam
  content ID during VM testing.
- Shared installed files do not grant Steam ownership; every player still needs
  their own entitlement to launch a game.

### Migration

`ludusctl libraries migrate <configured-path> [--yes]` has a conservative first
implementation. It stops if Steam is running, copies with `rsync`, checksum
verifies before deleting a source game directory, moves matching manifests, and
leaves ambiguous destination or manifest conflicts untouched.

Migration still needs broad real-world validation, including Workshop content,
existing Proton/shader layouts, duplicate games, and interrupted migrations.

## Phase 2: WebUI

Work in progress:

- A root-only local backend service has been started. It exposes an allow-listed
  operation set rather than arbitrary commands.
- A separate `ludus-web` system user and WebUI systemd service have been added.
- The first browser service uses HTTP Basic authentication, reads a root-owned
  credential configuration, binds to the LAN by default, and can query status,
  users, and libraries through the local backend socket.
- The installer generates an initial administrator password when no WebUI config
  exists.
- The WebUI now provides Dashboard, Users, Libraries, Health/Repair, and
  credential-rotation views.  Its mutation routes are JSON-only, authenticated,
  and map to the backend's fixed operation allow-list.
- Deployed on the Bazzite VM: backend, WebUI, and firewall services are active;
  unauthenticated requests receive `401`, JSON-only mutation protection was
  exercised, and authenticated requests succeeded through the VM's private-LAN
  address.  No new Ludus AVC was observed during those checks.
- `ludus-web-firewall.service` opens TCP 9876 only for the directly connected
  private IPv4 subnet and refuses to create a rule for public/VPN networks.
- User status now distinguishes Steam-ready accounts from users who still need
  their first Steam login. The WebUI shows that prerequisite rather than trying
  to create or edit Steam configuration prematurely.
- The Libraries page offers a safe mounted-filesystem choice, creating a
  standard `ludus-steam-library` directory, alongside the advanced exact-path
  option. Shared game data lives there; per-user Proton and shader state lives
  under each user's home.

The WebUI is not yet feature-complete or ready to describe as production-ready.

## Still to do

### Shared libraries

- Test real game installation, launch, update, and uninstall from the shared
  library using both Ludus users.
- Validate migration against existing populated libraries and add Workshop
  handling where it is proven safe.
- Add complete diagnostics for mounts, private paths, registrations, SELinux
  labels, services, and Steam-running state.
- Test repair and uninstall end-to-end; ensure no game, save, or home data is
  removed.
- Add a GPL-3.0-or-later licence file and retain appropriate upstream notices
  when copying/adapting `steam-multiuser` code.

### WebUI

- Add migration controls and richer per-library storage/mount information to
  the WebUI.
- Improve authentication further with sessions and rate limiting. Basic
  authentication remains only the initial transport boundary; JSON-only writes
  avoid form-based CSRF.
- Validate the private-subnet firewall rule from a second LAN device and add a
  documented configuration path for more complex/VPN networks.
- Validate the root backend's peer-credential/group checks and SELinux behavior.
- Validate the expanded `ludusctl doctor` checks on the Bazzite VM and add
  SELinux-label and Steam-registration checks.

### Phase 1 follow-up

- Create and validate a narrowly scoped SELinux policy for `/dev/uinput` so
  controller navigation can be tested on physical hardware.
- Test recovery, upgrade, and uninstallation paths after Bazzite updates.

## Current disposable VM test library

The configured VM test library is:

```text
/var/srv/ludus-test-steam-library
```

It is empty and exists only to validate Ludus. It is not an intended permanent
game-library location.
