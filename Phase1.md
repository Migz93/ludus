You are connected via SSH/terminal to a test VM running the **normal Bazzite Desktop KDE image**.

I want you to investigate, prototype, and where practical implement a custom **controller-friendly user login/selector experience** for a dedicated lounge gaming PC.

This VM is specifically for experimentation. You may inspect the OS, installed packages, display manager, systemd services, user/session configuration, Bazzite-specific configuration, Steam installation, etc.

## Overall goal

The final physical machine will have separate Linux user accounts, for example:

- Miguel
- Steph

I specifically want **separate Linux users**, rather than switching Steam accounts inside one Linux profile, because I want complete separation of:

- game saves
- Steam configuration
- Proton/Wine prefixes
- emulator configuration
- application configuration
- home directories
- other per-user data

However, I want the machine to feel like a console rather than a normal PC.

On boot, instead of exposing a normal KDE/SDDM login screen that needs a keyboard and mouse, I want a custom fullscreen UI that can be operated entirely with an Xbox-style controller.

Conceptually:

```text
PC boots
   ↓
Custom fullscreen user selector
   ↓
┌───────────────────────────────┐
│                               │
│        Who's playing?         │
│                               │
│     (photo)      (photo)      │
│      Miguel       Steph       │
│                               │
│        A: Select              │
│                               │
└───────────────────────────────┘
```

The application should discover the **actual eligible local user accounts** on the system rather than hardcoding Miguel and Steph.

Each user should be represented by:

- their display name / username
- their configured profile picture/avatar if one exists
- the avatar should be displayed as a **circle**

System/service accounts should obviously not appear.

## Desired login experience

When I select a user with the controller, I do **not** want to see:

- SDDM
- password prompts
- KDE desktop loading
- panels appearing
- terminal windows
- Steam slowly opening
- other normal Linux startup UI

Instead the user-selector application should remain fullscreen and show something like:

```text
Getting things ready...

        ◌
```

or another clean loading animation.

Behind that screen, the system should:

1. authenticate/start the selected Linux user's graphical session
2. start whatever minimum desktop/session components are required
3. launch Steam
4. launch Steam directly into **Big Picture Mode**
5. determine when Steam Big Picture is sufficiently ready
6. only then stop covering the display / transfer control to that user's session

From the person sitting on the sofa, the intended experience is approximately:

```text
Select Miguel
     ↓
Getting things ready...
     ↓
Steam Big Picture
```

It should *look* like the machine has directly switched from our user selector into Miguel's Steam environment.

A couple of seconds of waiting is fine. Hiding the ugly login/session startup process is more important than trying to make everything literally instantaneous.

## Authentication

This will be a dedicated lounge gaming machine.

I am not concerned about strong local Linux passwords for these gaming accounts. They may have blank/simple passwords if that makes the architecture considerably cleaner.

Do **not** weaken unrelated security unnecessarily, though.

If passwordless graphical login can be implemented safely and narrowly for only explicitly eligible local gaming accounts through PAM/SDDM/systemd/etc., investigate that approach.

Do not make SSH/root authentication passwordless just because graphical login is.

## Controller support

The selector needs to work with common Xbox-compatible/XInput-style controllers supported by Linux.

Minimum controls:

- D-pad / left stick: move between users
- A: select
- visually show which user is currently selected

Ideally controller hotplug should work too.

Keyboard support can exist for development/fallback, but **controller-only operation is a core requirement**.

The eventual physical machine will normally have no keyboard or mouse attached.

## User discovery / avatars

Please investigate how KDE/SDDM/Bazzite stores user metadata and avatars.

The selector should dynamically enumerate normal login users.

Do not hardcode usernames.

Potential sources worth investigating include:

- AccountsService
- `/var/lib/AccountsService/`
- `/etc/passwd`
- user UID ranges
- SDDM configuration
- KDE user/account configuration

Use the most appropriate supported mechanism you find.

Exclude things such as:

- root
- service accounts
- system users
- nobody
- daemon users
- dedicated internal application users

If an avatar cannot be found, generate/show a clean default circular avatar.

## Architecture

Do not blindly start coding the UI first.

First inspect the machine and determine how Bazzite Desktop KDE currently handles:

- display manager
- graphical sessions
- Wayland/X11
- SDDM
- KDE Plasma startup
- Steam startup
- autologin
- user switching
- logind sessions
- immutable/atomic filesystem considerations
- systemd user services
- system-level systemd services

This is Bazzite, so remember that it is an **Atomic Fedora-based system**. Avoid solutions that depend on casually modifying immutable system files if there is a persistent/supported alternative.

Investigate whether the best architecture is:

### Option A — custom SDDM greeter/theme

Replace/customise the standard SDDM greeter with our controller-oriented UI.

The greeter selects a user and initiates their session.

### Option B — dedicated launcher/greeter process before the user session

Have some minimal session/service own the display first, then launch/switch to the selected user.

### Option C — another architecture

If Linux/systemd/SDDM provides a cleaner mechanism, explain it and use it.

I am open to whichever implementation is most robust.

The important requirements are:

- real separate Linux users
- controller-friendly selector
- hide login/session startup
- Steam Big Picture appears when ready
- persistent across normal reboots
- reproducible on another Bazzite installation

## Switching users later

The immediate priority is the **boot → choose user → Steam Big Picture** flow.

However, please design things so we can later add a "Switch Player" action accessible from Steam Big Picture.

That could potentially:

```text
Miguel Steam
   ↓
Switch Player
   ↓
Miguel session logs out/stops
   ↓
our fullscreen selector appears
   ↓
Steph selected
   ↓
Getting things ready...
   ↓
Steph Steam
```

We do not need to keep both graphical user sessions running simultaneously.

It is perfectly acceptable, and possibly preferable, for changing player to completely terminate the previous gaming user's session.

Do not spend too much time implementing this secondary flow until the initial boot/login flow is working, but avoid an architecture that makes it unnecessarily difficult later.

## Steam

This is **normal Bazzite Desktop KDE**, not the Bazzite Deck/Gaming Mode image.

Therefore Steam should ultimately start in normal **Big Picture Mode**.

Investigate the cleanest launch mechanism.

We want Steam to run as the selected user, obviously — never as root/system.

Steam should preferably launch automatically as part of that user's gaming session rather than via ugly global startup hacks.

If necessary, create a dedicated per-user systemd user service or appropriate autostart configuration.

Be careful that Steam does not get launched multiple times.

## Readiness detection

One particularly important requirement is that our "Getting things ready..." UI should not disappear merely because `steam` has been executed.

Investigate a reasonable way to determine that Steam/Big Picture is actually ready enough to show.

That could involve things such as:

- Steam process state
- window detection
- Wayland/X11 window/application state
- DBus
- logs
- Steam IPC
- Gamescope/window information
- another reliable signal you discover

It does not need to be mathematically perfect, but avoid arbitrary fixed sleeps like:

```bash
sleep 20
```

unless used only as a fallback/time-out.

We should also have a reasonable timeout/error state such as:

```text
Steam failed to start

Retry
Return to player selection
```

## VM limitations

This is currently running in a Proxmox VM.

The VM may not accurately represent:

- NVIDIA hardware
- final display resolution
- controller hardware
- Steam/game rendering performance
- GPU acceleration

That's okay.

The VM's purpose is primarily to validate:

- Linux user/session architecture
- SDDM/login mechanics
- the UI
- Steam startup
- configuration persistence
- installation/deployment

Do not get stuck trying to perfect GPU-specific behaviour in the VM.

Where controller hardware isn't available, create/test keyboard equivalents and structure the implementation so controller input can be tested on the physical machine later.

## VERY IMPORTANT — deployment/reproducibility

Do not make a pile of undocumented manual changes.

Everything we determine is necessary must ultimately be reproducible.

Create a project/work directory for this experiment and maintain documentation as you work.

At minimum I want:

```text
README.md
install.sh
uninstall.sh
```

Potentially also:

```text
src/
systemd/
sddm/
config/
assets/
docs/
```

depending on the architecture.

### `install.sh`

The install script should perform everything necessary to turn a fresh compatible Bazzite Desktop KDE installation into this setup.

It should be:

- safe
- well commented
- reasonably idempotent
- able to detect already-configured pieces
- explicit when reboot/logout is required

It may install packages or deploy files if required.

Where Bazzite requires `rpm-ostree`, `ujust`, Flatpak, `/etc`, `/var`, systemd units, or another persistent mechanism, use the appropriate Bazzite/Fedora method.

Do not assume changes made to normally immutable locations will survive updates.

### `uninstall.sh`

Provide a way to restore the machine to a normal Bazzite login experience.

This is especially important when modifying SDDM/PAM/session configuration.

The uninstall/rollback process must avoid leaving the machine unable to log in.

### Documentation

`README.md` should explain:

- what the project does
- architecture chosen
- why that architecture was chosen
- components/files installed
- required packages
- how users are detected
- how authentication works
- how controller input works
- how the selected user's session is started
- how Steam Big Picture is launched
- how readiness is detected
- how to install
- how to uninstall
- how to troubleshoot it
- how to recover from a broken login configuration
- VM limitations
- what still needs testing on the physical NVIDIA machine

## Safety / recovery

Because this experiment touches the login stack, be conservative.

Before replacing/changing important SDDM/PAM configuration:

1. inspect the current configuration
2. save/back up anything being modified
3. document the original state
4. ensure there is a recovery mechanism

Avoid making changes that could prevent SSH access unless absolutely necessary.

Assume I can revert the Proxmox VM if we completely break it, but the eventual installer needs to be safe enough to run on a physical machine.

## Development approach

Please proceed iteratively.

Start by inspecting the VM and report back what you find about:

- exact Bazzite version/image
- KDE/Plasma version
- display manager
- session types
- SDDM configuration
- available login/session APIs
- user/avatar storage
- Steam installation
- immutable filesystem considerations

Then propose the architecture you think is best.

You can implement/prototype directly on this VM.

Do not assume my proposed technical implementation is necessarily correct. If you discover a substantially cleaner Linux-native way of achieving the same UX, use it.

Keep the final user experience as the primary goal:

**Power on → controller-friendly player selection → select real Linux user → attractive loading screen → that user's Steam Big Picture, with no normal desktop/login UI exposed.**

If you reach a decision where there are genuinely meaningful trade-offs that require my preference, ask me before committing to that particular design choice.