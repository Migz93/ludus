# Shared Steam Libraries

## Model

Ludus shares installed Steam game content, not account ownership. Every player
still needs the relevant entitlement on their own Steam account.

Each player keeps Steam's mandatory private library at
`~/.local/share/Steam`. It contains the Steam client, account state, and other
private data and must not be turned into shared storage.

Managed shared libraries use `root:ludus` ownership, group-write access, and
setgid directories. Their `steamapps/compatdata` and `steamapps/shadercache`
paths are bind-mounted to the active player's private directories only for that
player's Ludus session.

## Administration

Use the WebUI or `sudo ludusctl`:

```text
ludusctl users list|enroll|remove
ludusctl libraries list|candidates|add|add-default|remove|default|set-default|label|check|repair
ludusctl doctor [--json]
```

The WebUI and CLI use the same backend rules. Before a command changes a
library's path, manifests, registration, ownership, or layout, it verifies that
Steam is not running for any enrolled user.

## Registration And Defaults

When a library is added, Ludus creates Steam's `libraryfolder.vdf` marker with
a unique positive numeric content ID and registers the same path, ID, and
optional label in each Steam-ready player's two `libraryfolders.vdf` files.

Ludus records the administrator's preferred library in
`/etc/ludus/default-library.conf`. Steam's actual default install choice is
per player, so select the library in Steam's Storage UI for each Steam-ready
player. Other configured libraries remain available as alternate locations.

## Installed Game Inventory

The WebUI Games page reads `steamapps/appmanifest_<appid>.acf` from every
configured shared library. It shows games and Steam components with their app
ID, name, install directory, recorded size and update time without starting
Steam or using the network.
Compatibility components whose names begin with `Proton` or
`Steam Linux Runtime` remain in the inventory data for diagnostics but are
hidden from the playable-game poster grid.
Malformed, mismatched and duplicate manifests are reported separately and do
not prevent valid games from appearing.

The Games page uses Steam's cached `library_600x900` portrait from an enrolled
player when one already exists locally. Otherwise the privileged inventory
helper requests the fixed portrait URL for that numeric app ID from Steam's
official CDN, then tries the wide library hero as a fallback. It validates the
size and image signature and copies only the image bytes into
`/var/cache/ludus/game-art`; the WebUI never receives a path into a player's
private home. Failed lookups are retried after 24 hours rather than on every
page load.

`/etc/ludus/game-settings.json` is the versioned console-wide policy store for
managed game features. Its optional Proton overlay DPI policy is disabled by
default and supports 100%, 125%, 150%, 175%, 200%, and 250%, with per-game
inherit, disabled, or explicit override choices.

After the active player's private `compatdata` mounts are established and
before Steam starts, Ludus reconciles only an existing numeric app ID path at
`steamapps/compatdata/<appid>/pfx/user.reg`. It edits only the exact
`Control Panel\\Desktop` `LogPixels` DWORD, does not create prefixes, and
reports missing prefixes. A first-change whole-file backup is retained under
root-private `/var/lib/ludus/proton-dpi`, but restoration changes or removes
only the originally recorded `LogPixels` value so later unrelated registry
changes survive. Disabling management queues restoration independently for
each affected player and completes it on that player's next login. Recovery
state and backups are separate for every player, app ID, and managed library,
so duplicate installations cannot exchange original registry values.

## Managed Launch Options

The Games page can enable ScopeBuddy globally, with per-game Follow default, enable,
or disable choices. Launch management is off by default. Enabled ScopeBuddy
uses a profile, available globally or as an explicit per-game override:

| Profile | Launch command wrapper |
|---|---|
| Adaptive native (default) | `SCB_AUTO_RES=1 SCB_AUTO_HDR=1 SCB_AUTO_VRR=1 scb -f -- %command%` |
| Upscale from 720p, 1080p, or 1440p | As above plus `-w W -h H -F nis\|fsr` and optional `--sharpness 0-20` |
| Custom | `scb <ScopeBuddy Arguments> -- %command%` (plain `scb -- %command%` when empty) |

Everything is written directly into the Steam launch command. ScopeBuddy reads
`SCB_*` values from the environment and passes its arguments to Gamescope, so
Ludus generates no ScopeBuddy configuration files. A player's own ScopeBuddy
configuration is sourced after the environment and may still override
`SCB_AUTO_*`. Adaptive native uses the active KDE output resolution and leaves
upscaling to the game. Upscale profiles render at a fixed resolution and apply
NVIDIA Image Scaling or FSR 1.0 to the final frame; on a smaller display or
stream they downscale instead, so the WebUI warns when one is chosen globally.
Ludus does not detect the output resolution of the current session.

Game arguments go after `%command%`; per-game game arguments append to the
global ones. A per-game override may use **Console default** to keep the global
profile. Follow default uses only the global settings, and saving Follow default
or Disabled clears the per-game profile and arguments. Arguments must be plain
shell words (quoting spaces is supported), without shell operators, expansions,
or another `%command%`. ScopeBuddy arguments cannot contain another `--`
separator.

Policy is stored alongside Proton DPI in `/etc/ludus/game-settings.json`, in
optional `launch_options` objects under `global` and each `games.<appid>`.
Global fields are `scopebuddy` (boolean), `profile` (`adaptive`,
`upscale-720p`, `upscale-1080p`, `upscale-1440p`, `custom`), `upscale_filter`
(`nis` or `fsr`), `sharpness` (null or 0-20), `wrapper_args` (Custom only), and
`game_args`. Per-game fields are `mode` (`inherit`, `enabled`, `disabled`) and,
for `enabled`, the same profile fields with `profile` also accepting `default`.
A global policy saved without `profile` but with `wrapper_args` is treated as
Custom. Disabling a game disables all managed launch additions for
that game. Changing one feature preserves the other feature's settings.

At each Ludus login, after the private binds are active and before Steam starts,
a worker running as the selected Linux player edits only the Steam account's
`userdata/<accountid>/config/localconfig.vdf` launch-options values. Ludus
expects exactly one account in `loginusers.vdf`; unexpected extra account
folders or ambiguous configuration are reported and skipped. Only readable,
valid app manifests with existing installed directories in the managed shared
libraries or the player's mandatory Steam library qualify for new changes.
Steam components such as Proton and Steam Linux Runtime are excluded. Games
without a local configuration entry can receive an entry when installed; this
inventory check does not establish Steam account entitlement.

Existing simple wrappers and arguments are preserved. A bare existing
`scb -- %command%` is replaced by the managed wrapper rather than nested, and is
restored exactly later. Shell operators, backslash escapes, Gamescope or other
ScopeBuddy wrappers, ambiguous commands, and manual changes to a managed value
produce a conflict instead of an overwrite. Unsupported KeyValues syntax is
reported as an error and the file is left untouched. The WebUI shows the game
launch command and each player's reconciliation state.

Both saving and login require `scb` or `scopebuddy`, `gamescope`,
`kscreen-doctor`, and `jq` in `/usr/local/bin:/usr/bin:/bin`; the warning lists
whichever are missing. If only `scopebuddy` exists, the command uses that name.
If a requirement disappears, unchanged Ludus-managed values are restored to
their original values and a warning is shown; manual values remain untouched.
The saved policy can apply again when ScopeBuddy is available. Ludus does not
install ScopeBuddy or modify its configuration files.

Recovery records live in the player's private
`~/.local/state/ludus/launch-options/state.json` (mode 0600, directory 0700).
They record original absence separately from an empty string, the last managed
value, and a journal of any pending write. The journal is saved and synced before
an atomic Steam-file replacement, allowing the next login to recognise a write
interrupted before or after replacement. Unrelated Steam values and formatting
are preserved. Policy operations and worker state operations are serialized by
separate locks. Steam must be stopped, and a changed file is not overwritten.
Recovery state is player-owned, like the Steam configuration it protects; it is
not a security boundary against that player deliberately modifying it.

**Replace temporarily** approves the exact conflicting value shown at that
time. At the next login, if Steam still holds that value, Ludus records it as
the restoration value and writes the managed command without it. If the value
changed again, the approval lapses and the conflict is reported again. Removing
management restores the approved value exactly.

**Accept manual override** releases just that player's game from management,
clears the conflict, and leaves its current command untouched on later logins.
Other players continue following the console policy. **Resume management**
queues a new attempt at the next login and captures the then-current manual
value as the new restoration baseline. It does not overwrite an ambiguous
manual command merely because management was resumed.

**Remove management for this game** or **Remove all launch management** queues
restoration at each affected player's next login, including previously managed
games no longer installed. Restoration only proceeds if the value still matches
Ludus's last write; otherwise the conflict controls on the specific game's page
apply. Per-player application and recovery are not shown on the overall Games
page.
Accepted manual overrides survive resets and do not block uninstall. Uninstall
otherwise stops while managed values or interrupted writes remain, unless the
administrator explicitly uses `--force`. Private recovery records are retained.

## Safety Rules

- All parent directories must be traversable by members of the `ludus` group.
  When a managed library is below a private directory on its own mounted data
  filesystem, library add/repair grants the group traversal-only ACL access;
  it does not expose directory listings or file contents.
- Repair applies only to the Ludus-managed layout, never unrelated directories
- Removing a library from Ludus does not delete game files
- Removing a player does not delete their Linux account or home directory
- A stale active-session marker is reconciled only when its matching Ludus or
  Steam process is gone; normal session teardown owns unmounting
