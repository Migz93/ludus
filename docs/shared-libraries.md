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
each affected player and completes it on that player's next login.

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
