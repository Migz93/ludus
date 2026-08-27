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

## Safety Rules

- All parent directories must be traversable by members of the `ludus` group
- Repair applies only to the Ludus-managed layout, never unrelated directories
- Removing a library from Ludus does not delete game files
- Removing a player does not delete their Linux account or home directory
- A stale active-session marker is reconciled only when its matching Ludus or
  Steam process is gone; normal session teardown owns unmounting
