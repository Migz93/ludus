<!-- shared: structure — keep headings aligned across Migz93 self-hosted apps -->

# Agent Guidelines

Read this file before doing any work in this repo.

Everything here is **always relevant**. Material that only matters for a
particular kind of work belongs in `docs/` instead.

> If a `LOCAL.md` file exists in this directory, read it — it contains
> machine-specific setup details. If it does not exist, ignore this note.

## Project Facts

| | |
|---|---|
| App name | `ludus` |
| Supported platform | Bazzite Desktop KDE on Fedora Atomic |
| Management WebUI port | `9876` |
| Primary configuration | `/etc/ludus` |
| Runtime state | `/run/ludus` and `/run/ludus-mount` |
| Installed program path | `/usr/local/lib/ludus` |
| Main administration command | `sudo ludusctl` |
| Checks to run before closing out work | `bash -n install.sh uninstall.sh src/ludusctl src/ludus-*`; `python3 -m py_compile src/*.py` |
| Integrations to flag in review | Plasma Login, PAM, systemd, SELinux, Steam, firewalld, Home Assistant MQTT |

## Before You Start — What To Read

| If you're about to… | Read |
|---|---|
| Change the login flow, session lifecycle, or a core subsystem | [docs/architecture.md](docs/architecture.md) |
| Change installation, systemd units, PAM, SELinux, firewalling, or filesystem paths | [docs/deployment.md](docs/deployment.md) |
| Change Steam libraries, mounts, user enrolment, or repairs | [docs/shared-libraries.md](docs/shared-libraries.md) |
| Change the management WebUI or its access controls | [docs/webui.md](docs/webui.md) |
| Change Home Assistant or MQTT behaviour | [docs/mqtt.md](docs/mqtt.md) |
| Open a PR, release, or use CodeRabbit | [docs/workflow.md](docs/workflow.md) |

[docs/README.md](docs/README.md) indexes the full technical reference.

## Safety Boundaries

- Ludus changes login, authentication, mounts, and system services. Treat every
  change as security-sensitive until it is shown otherwise.
- Preserve the single-active-player-session model. Do not add concurrent
  sessions or in-session player switching without explicit design work.
- Never weaken SSH, sudo, root, or unrelated PAM services to make the Ludus
  login flow work. Passwordless login is narrowly scoped to enrolled users at
  the local Plasma Login greeter.
- Keep SELinux enforcing. Add the smallest documented policy change needed;
  never solve a problem by disabling SELinux globally.
- Do not delete player accounts, home directories, game files, or shared Steam
  libraries as part of removal or repair. Operations must be conservative and
  idempotent.
- Steam must be stopped for every enrolled user before changing library paths,
  ownership, manifests, or Steam registrations.

## Platform And Installation

Ludus supports **normal Bazzite Desktop KDE**, not Bazzite Gaming Mode. It
uses the installed `/usr/bin/bazzite-steam` launcher and Plasma Login Manager.

The installer is run from a local checkout:

```bash
sudo ./install.sh
```

On a fresh system the first run layers build dependencies with `rpm-ostree` and
requires a reboot. Run the same command again after booting the staged
deployment. Do not claim an install or runtime change has been verified unless
it was tested on a suitable Bazzite KDE system.

`install.sh` builds a Plasma Login greeter matched to the installed package
version and writes only Ludus-owned files under `/usr/local/lib/ludus`,
`/etc/ludus`, and `/var/lib/ludus/backups`. The vendor greeter remains the
fallback if the custom build is incompatible after an OS update.

## Working Locally

Most source inspection and static checks can run anywhere. Installation,
Plasma Login, systemd, SELinux, controller, Steam, firewalld, and MQTT
validation require a Bazzite Desktop KDE machine with the relevant services.

Do not try to install packages, change the host login manager, restart Plasma
Login, or alter firewall/PAM/SELinux state merely to compensate for an
environment that cannot run the integration. State the missing validation step
instead.

Useful local checks:

```bash
bash -n install.sh uninstall.sh src/ludusctl src/ludus-*
python3 -m py_compile src/*.py
```

Run `sudo ludusctl doctor` on an installed target for the operational health
check. Use `sudo ludusctl doctor --json` for structured output.

## Repository Conventions

- Shell and Python entry points live in `src/`; installed systemd units live in
  `systemd/`; PAM configuration lives in `config/`; SELinux sources live in
  `selinux/`.
- Keep paths, ownership, modes, and SELinux labels explicit. Avoid broad
  recursive changes outside directories Ludus owns.
- Use `install.sh` as the single deployment path. Do not add instructions that
  ask users to copy individual runtime files into system paths by hand.
- Update the matching document under `docs/` when changing lasting runtime,
  security, integration, or operational behaviour.
- Keep generated build outputs, compiled SELinux modules, credentials, and VM
  artefacts out of the repository.

## GitHub Workflow

`main` is the stable branch. Create a focused work branch for changes; use a
semantic branch prefix such as `feat/`, `fix/`, `chore/`, `docs/`, or `ci/`.
Use semantic PR titles (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, or
`ci:`), explain deployment and security impact, and do not open a PR until the
user asks to proceed.

Before closing work, report which static checks ran and which Bazzite-only
validation remains outstanding. See [docs/workflow.md](docs/workflow.md) for
review and release conventions.
