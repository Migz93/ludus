<!-- shared: structure — headings kept in sync across Migz93 self-hosted apps, content is app-specific -->

# Maintenance

## Current Housekeeping Responsibilities

Ludus does not run a generic scheduled cleanup job. Its ongoing maintenance is
conservative and command-driven:

| Operation | Owner | What it does |
|---|---|---|
| Health check | `ludusctl doctor` | Reports service, mount, Steam launcher, firewall, MQTT, and SELinux state |
| Library validation/repair | `ludusctl libraries check|repair` | Checks and restores the managed shared-library layout only |
| Stale session reconciliation | `ludusctl` and mount daemon | Clears a stale marker and private binds only after the related process has gone |
| Installer upgrade | `install.sh` | Replaces installed entry points and restarts applicable Ludus services |

## Data Retention

| Data | Retained | Controlled by |
|---|---|---|
| Ludus install backups | Yes | `/var/lib/ludus/backups` |
| Linux accounts and home data | Yes | Never removed by Ludus uninstall |
| Shared game files | Yes | Never removed by library removal/uninstall |
| Steam registrations | Yes | Left intact on uninstall |
| Runtime sockets and session markers | Until reboot/service stop | `/run` and owning systemd service |

## Adding New Maintenance Work

When adding cleanup, repair, or consistency checks:

1. Keep it idempotent and limited to Ludus-owned paths.
2. Do not infer that an unrecognised path is safe to change.
3. Refuse structural shared-library changes while Steam is running.
4. Log enough context to diagnose a failure without logging credentials.
5. Prefer a check/report operation before an automatic destructive repair.
6. Update this document and the subsystem document in the same change.

## Safety Rules

- Never delete player accounts, home directories, or game data as cleanup.
- Do not remove recovery backups automatically.
- A failed external check is a reason to warn or stop, not to force repair.
- Keep SELinux enforcing and configuration recovery reversible.
