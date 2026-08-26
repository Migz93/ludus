# Ludus — Phase 2: Shared Steam Libraries and Management WebUI

## Context

Ludus is an all-in-one tool for turning a Bazzite Desktop gaming PC into a controller-first, shared lounge console.

Phase 1 has already established the core player-selection experience:

- Separate real Linux users are used for each player.
- Ludus presents a controller-friendly fullscreen player selector instead of relying on the normal desktop login experience.
- Selecting a player starts that user's graphical session in the background.
- Steam is launched directly into Big Picture Mode for that user.
- Ludus keeps the login/startup process hidden behind its own loading UI until Steam is ready.
- Users enrolled in the Ludus Linux group are the users shown by the player selector.
- The existing project includes installer/setup logic and documentation intended to make the configuration reproducible.

Phase 2 expands Ludus from a user-switching/login tool into the management layer for the whole lounge gaming PC.

## Single active player session

Ludus is a single-player lounge console.  There is only ever one active Ludus
player session: a player must sign out before another player can sign in.  Ludus
does not support concurrent graphical/Steam sessions, user switching, or two
players using the shared libraries at once in Phase 2.

This is an intentional constraint of the shared-library design.  The active
user's private Steam data can be bind-mounted at the common library path before
Steam starts, then removed when that user signs out.  The UI, session handling,
diagnostics, and privileged backend must reject or clearly report any state
that would leave more than one Ludus session active.

The two major Phase 2 features are:

1. Shared Steam libraries with proper per-user isolation.
2. A Ludus WebUI for administering the machine without SSH, keyboard, or mouse.

---

# 1. Shared Steam Libraries

We have found an existing GPL-licensed project that solves much of the Steam multi-user problem:

**steam-multiuser**

https://github.com/benwhite1987/steam-multiuser

Review this project carefully before implementing the Ludus version.

Do not independently reinvent its solution without first understanding how it works.

In particular, inspect its:

- PAM/login hooks
- mount namespaces
- bind mounts
- permissions/group ownership
- shared `appmanifest_*.acf` handling
- shared Steam content
- Workshop handling
- per-user `compatdata`
- per-user shader/cache handling
- `libraryfolders.vdf` handling
- Steam library registration
- handling of pre-existing content
- repair/health-check logic
- uninstall/cleanup logic

We want to adapt the useful architecture and, where appropriate and licence-compatible, implementation into Ludus.

## Problem being solved

Each player in Ludus is a separate real Linux user.

This gives us the isolation we want for:

- local game saves
- Steam configuration
- Proton/Wine prefixes
- emulator configuration
- application configuration
- per-user game settings
- other player-specific files

However, game installations should belong to the machine rather than to one player.

If Miguel installs a 100 GB game, Steph should not need another 100 GB copy.

Both users should immediately see the same installed-game state.

The target model is:

```text
Shared between Ludus users:
- Steam game installation files
- Steam app manifests
- Workshop content where safe/appropriate
- Other machine-level library content where appropriate

Private to each Linux user:
- Steam account/session
- compatdata / Proton prefixes
- local saves
- user-specific configuration
- shader/cache data where appropriate
- other per-user Steam state
```

Steam ownership and Steam Family Sharing/entitlements remain account-level
concerns.  A shared installed game is not a licence grant: a player must still
be entitled to launch it with their own Steam account.

## Multiple libraries are a core requirement

Ludus must support more than one shared Steam library.

The intended physical machine will approximately use:

```text
1 TB NVMe
├── Bazzite
└── Shared Steam Library 1

2 TB SSD
└── Shared Steam Library 2
```

The exact mount paths should be configurable rather than hardcoded.

Both enrolled Ludus users must see all configured shared libraries.

Adding another shared library later should also be supported.

## Installed-state behaviour

A core requirement is:

> If one Ludus user installs or uninstalls a game, the other Ludus users should see the resulting installed state automatically.

If sharing the Steam `appmanifest_*.acf` files provides this behaviour correctly, prefer that architecture.

Do **not** introduce a file watcher or manifest-copy/synchronisation daemon unless it is genuinely required.

The aim is for there to be one authoritative machine-level installed-game state.

## Existing Ludus user group

Phase 1 already uses a Linux group to determine which local accounts are enrolled in Ludus and therefore displayed on the player-selection screen.

Reuse the **`ludus`** group for shared-library access wherever practical.

Do not create a second unrelated `gamers` group unless there is a strong technical reason.

Membership of the Ludus group should ideally mean:

- user appears in the Ludus player selector
- user is eligible to use Ludus shared Steam libraries

The WebUI will manage this membership.

## Bazzite / Fedora Atomic requirements

The target platform is **Bazzite Desktop KDE / Fedora Atomic**, not Arch Linux or CachyOS.

Adapt any assumptions made by `steam-multiuser` accordingly.

Pay particular attention to:

- immutable/atomic filesystem behaviour
- persistent locations under `/etc` and `/var`
- systemd system services
- systemd user services
- PAM configuration
- mount namespaces
- the Steam installation Bazzite supplies
- SELinux
- filesystem mount options
- ownership and permissions
- changes that must survive Bazzite updates

Avoid relying on modifications to locations that will be replaced by OS updates when a persistent mechanism exists.

Do not disable SELinux globally merely to make the implementation work.

### Supported Steam integration

Phase 2 targets the Steam launcher supplied by the installed Bazzite Desktop
image, currently invoked by Phase 1 as `/usr/bin/bazzite-steam`.  Do not build a
second Steam installation or make users choose between native and Flatpak
layouts.  The backend must detect the supported launcher and its per-user data
paths on the installed image, report an actionable unsupported-installation
error when it cannot, and use one tested layout consistently for all Ludus
users.

All implementation and health-check assumptions about Steam paths must be
derived from that supported Bazzite integration and documented beside the code.

### Ownership and private-data contract

Use the existing `ludus` group for shared-library access.  Adapt the proven
`steam-multiuser` permissions model unless Bazzite/SELinux requires a narrowly
documented variation:

- shared library content and manifests: `root:ludus`, group writable, with the
  setgid bit on shared directories so new content retains the `ludus` group;
- the unmounted private-data bind targets: `root:root`, inaccessible when no
  Ludus player session is active;
- each user's real `compatdata`, shader/cache, saves, Steam account data, and
  other private state: owned by that user and never group-readable merely for
  sharing games.

For every managed path, diagnostics must check ownership, mode, setgid
inheritance, mount state, and expected SELinux label.  Repair must restore only
this Ludus-owned layout; it must not recursively alter unrelated directories.

## Idempotency

All shared-library configuration must ultimately be handled by the Ludus installation/configuration tooling.

Running setup again should not:

- duplicate mounts
- duplicate config entries
- break ownership
- destroy existing Steam libraries
- overwrite user data unnecessarily

Existing configuration should be detected and reconciled.

### Steam-running precondition

Any operation that changes a shared library's structure, manifests,
`libraryfolders.vdf`, ownership, or registration must first
verify that Steam is stopped for every enrolled user.  If it is running, the
CLI and WebUI must make no change and explain which user/process must exit.

This does not prevent the controlled login hook from preparing the active
user's bind mounts before Ludus launches Steam.

---

# 2. Ludus WebUI

Phase 2 should add a WebUI so the lounge PC can be administered remotely.

The physical machine is intended to normally run without a keyboard or mouse, so routine management should not require:

- SSH
- opening KDE Desktop Mode
- attaching a keyboard
- attaching a mouse
- manually editing config files

The WebUI should be part of Ludus rather than an unrelated companion project.

## Initial WebUI scope

### Dashboard

Provide a simple overview showing the state of Ludus.

Useful information could include:

- Ludus version
- hostname
- enrolled users
- configured Steam libraries
- whether required Ludus services are running
- whether shared library mounts/bind mounts are healthy
- whether permissions appear correct
- whether Steam-related integration appears healthy
- warnings requiring attention

Use clear healthy/warning/error states.

Do not turn this into a generic Linux monitoring dashboard.

It should focus specifically on things Ludus owns or depends on.

### Users

Allow management of Ludus-enrolled users.

At minimum:

- list eligible/local interactive Linux users
- show whether each user is enrolled in Ludus
- show the user's avatar/profile image where available
- enrol a user
- remove a user from Ludus
- show relevant status/validation for each enrolled user

Enrolling a user should perform all required Ludus configuration for that user, including shared Steam library integration.

Removing a user from Ludus must **not delete the Linux user or their home directory** unless a future feature explicitly says otherwise.

It should simply remove them from Ludus management/access cleanly.

The CLI/setup logic and WebUI should use the same underlying backend logic rather than having two independent implementations.

### Shared Steam Libraries

Provide a page for configured shared Steam libraries.

At minimum:

- list configured libraries
- show their filesystem paths
- show mount/device information where useful
- show available/free space
- add an existing directory as a shared Steam library
- remove a library from Ludus management
- validate permissions
- validate expected Steam directory structure
- validate manifests/shared-data configuration
- repair configuration where practical

Be conservative when removing a library.

Removing a library from Ludus must not automatically delete installed games.

### Health / Diagnostics

Provide a central diagnostics view.

Checks should cover the components Ludus actually depends on, for example:

- Ludus services
- SDDM/player-selector integration from Phase 1
- Ludus group existence
- enrolled-user group membership
- configured Steam libraries
- library ownership/permissions
- mount namespace/bind mount configuration
- per-user private Steam directories
- shared manifests
- Steam library registration
- required systemd units
- other state introduced by Ludus

Each check should ideally return something like:

```text
Healthy
Warning
Error
```

with a concise explanation.

Where safe, expose a **Repair** action.

Repair logic should also be callable from the CLI.

## WebUI safety

The WebUI will perform privileged operations, so do not simply run the entire web application as root if a safer architecture can be used.

Prefer an architecture such as:

```text
Browser
   ↓
Ludus WebUI/API
   ↓
controlled Ludus backend/service
   ↓
privileged operations
```

or another well-structured privilege boundary.

Do not expose arbitrary shell-command execution through the WebUI.

Validate all filesystem paths and user inputs carefully.

Initially assume the WebUI is intended for a trusted home LAN, but design authentication/access control so it can be added or enabled cleanly.

The WebUI must be available to devices on the home LAN by default, but it must
require authentication from its first release.  Install it as a non-root service
and expose only a narrowly scoped, authenticated privileged backend API.  Do
not make a no-authentication LAN mode the default.

Its listener and firewall rules must be explicitly configured for LAN access;
the service must not accidentally become reachable from the public Internet.
The initial administrator credential/onboarding flow and credential rotation
must work without SSH and must be documented.

---

# 3. Shared Backend / CLI

Phase 2 should avoid putting important business logic directly inside UI code.

Design a common Ludus backend/library that can be used by:

- installer
- WebUI
- diagnostics
- repair functions
- future CLI
- future player-selector integration

A CLI called **`ludusctl`** is desirable.

Potential commands might eventually resemble:

```bash
ludusctl status

ludusctl users list
ludusctl users enroll <user>
ludusctl users remove <user>

ludusctl libraries list
ludusctl libraries add <path>
ludusctl libraries remove <path>
ludusctl libraries check
ludusctl libraries repair

ludusctl doctor
ludusctl repair
```

These names are examples, not mandatory API requirements.

Choose a clean structure that fits the implementation.

The WebUI should call this common backend directly or through a defined internal API rather than shelling out to random scripts wherever possible.

---

# 4. Integration With Phase 1

Do not replace or regress the existing controller login/player-selector work.

Phase 2 should integrate with it.

The existing Ludus group should remain the source of truth for player enrolment unless investigation identifies a materially better design.

For example:

```text
WebUI
  ↓
Enrol Steph
  ↓
add Steph to ludus group
  ↓
configure private/shared Steam layout for Steph
  ↓
Phase 1 player selector automatically sees Steph
```

Similarly:

```text
WebUI
  ↓
Remove Steph from Ludus
  ↓
remove Ludus-specific integration/group membership
  ↓
Steph no longer appears in player selector
```

The player selector should not need its own separate user database if Linux/group state already gives us a reliable source of truth.

---

# 5. Configuration and State

Create a coherent configuration model for Ludus.

Possible locations:

```text
/etc/ludus/
/var/lib/ludus/
```

Use `/etc/ludus` for administrator-managed configuration and `/var/lib/ludus`
for durable service state and backups.  Use `/opt/ludus` only if a
future packaged application payload genuinely needs it; it is not the place for
mutable configuration or state.  Executables and systemd units should follow
the existing Bazzite-compatible installation conventions.

Use standard Linux conventions appropriately.

We will likely need persisted information such as:

- configured shared library paths
- schema/version information
- WebUI configuration
- Ludus component configuration

Do not duplicate information that can be reliably discovered from the operating system.

For example, if enrolled users can safely remain represented by membership in the `ludus` Linux group, do not maintain an unnecessary second user list in JSON.

---

# 6. Installation, Upgrade and Uninstall

Update the existing Ludus installer so Phase 2 is reproducible on a fresh Bazzite Desktop installation.

The installer should configure everything necessary for:

- Phase 1 player selector
- Ludus user/group integration
- shared Steam library system
- required services
- WebUI
- CLI/backend
- diagnostics

It should remain reasonably idempotent/re-runnable.

## Existing installations

The installer must account for systems where Phase 1 is already installed.

It should upgrade/configure the existing Ludus installation rather than requiring a wipe.

## Uninstall

Update the uninstall process accordingly.

Removing Ludus should restore the system to a usable standard Bazzite configuration.

Be particularly careful with shared Steam libraries.

Uninstalling Ludus should **not delete installed games, user home directories, saves, or other valuable user data**.

Where ownership/layout changes cannot safely be automatically reversed, document exactly what remains.

---

# 7. Existing Steam Content

Player-owned game installations are deliberately outside Ludus's scope. Ludus
must never move, rewrite, or delete games or Steam manifests from a player's
existing library. A player can choose how to manage old installations through
Steam itself.

New Ludus shared-library directories must be prepared safely and must have
empty `compatdata` and shader-cache bind targets before Ludus makes those paths
private. If an existing directory conflicts with that layout, Ludus reports the
conflict and leaves it untouched.

---

# 8. Diagnostics and Repair

A major goal of Ludus is making this setup maintainable without remembering a collection of Linux commands.

Build health checking as a first-class feature rather than an afterthought.

The same checks should ideally power:

```text
WebUI → Health
```

and:

```bash
ludusctl doctor
```

Potential checks include:

- expected group exists
- expected users are correctly enrolled
- library paths exist
- expected filesystems are mounted
- correct group ownership
- required group write permissions
- shared manifests visible
- per-user `compatdata` remains private
- bind mounts/namespaces active where required
- library registration present for every enrolled user
- relevant systemd services healthy
- Phase 1 selector service healthy
- WebUI service healthy

Repair actions should be explicit and safe.

Do not automatically rewrite or delete significant Steam/user data simply because a health check fails.

---

# 9. Development Approach

Before implementing Phase 2:

1. Review the current Ludus codebase and Phase 1 architecture.
2. Review `steam-multiuser` carefully.
3. Document how `steam-multiuser` achieves its shared/private Steam layout.
4. Identify which pieces can be reused directly, which need adapting for Bazzite, and which should not be carried over.
5. Check licence obligations before copying/adapting GPL code.
6. Propose the Phase 2 architecture.
7. Implement iteratively on the test VM.
8. Keep installation scripts and documentation updated while changes are made.

Do not make a large set of undocumented manual changes and then try to reconstruct them later.

The repository should remain deployable to the new physical lounge PC once the VM implementation is validated.

Phase 2 should license Ludus under **GPL-3.0-or-later**.  Directly copied or
adapted `steam-multiuser` code must retain its copyright and GPL-2.0-or-later
notices, with the source and required licence materials distributed alongside
Ludus.  Architecture informed by the project should still be documented with
its origin.

---

# End Goal

Ludus should turn a normal Bazzite Desktop installation into something that behaves much more like a dedicated shared console.

The intended user experience is:

```text
Power on
   ↓
Ludus player selector
   ↓
Choose Miguel or Steph
   ↓
That real Linux user's session starts
   ↓
Steam Big Picture
```

while behind the scenes:

```text
Separate Linux users
        +
Separate saves / Proton prefixes / personal state
        +
Shared game installations
        +
Shared installed-game state
        +
Multiple shared Steam libraries
```

and administration happens through:

```text
Ludus WebUI
├── Dashboard
├── Users
├── Shared Libraries
└── Health / Repair
```

The goal is that once Ludus is installed, routine use and administration of the lounge gaming machine should require neither SSH nor a keyboard/mouse.
