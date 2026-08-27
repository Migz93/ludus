<!-- shared: structure — keep headings aligned across Migz93 self-hosted apps -->

# Contributing

Thanks for taking an interest in Ludus.

## Workflow

`main` is the stable branch. Please create a focused branch for your change and
open a pull request against `main` unless a maintainer asks otherwise.

## Pull Requests

Please keep pull requests focused and practical.

- Use semantic PR titles such as `feat:`, `fix:`, `docs:`, `chore:`,
  `refactor:`, or `ci:`
- Explain what changed and why
- Mention anything a reviewer should verify on Bazzite Desktop KDE
- Call out login, PAM, systemd, SELinux, Steam, firewall, WebUI, MQTT, or
  filesystem impact where relevant

## Local Development

Ludus targets normal Bazzite Desktop KDE. Most static checks can run on a
regular Linux development machine, but installation and runtime validation need
a suitable Bazzite system.

Useful checks:

```bash
bash -n install.sh uninstall.sh src/ludusctl src/ludus-*
python3 -m py_compile src/*.py
```

Run `sudo ./install.sh` only from a local checkout on a test system. On a fresh
Bazzite installation, the first run may layer dependencies and require a reboot
before the second run completes installation.

## Technical Docs

See [docs/README.md](docs/README.md) for the technical reference area.

If you change architecture, login/session behaviour, deployment, shared
libraries, the WebUI, or MQTT, update the relevant `docs/*.md` page in the same
branch/PR.

## Coding Notes

- Keep changes scoped to the task at hand
- Preserve the least-privilege model; do not weaken unrelated authentication or
  disable SELinux
- Make install, repair, and removal operations idempotent and conservative
- Avoid committing generated output, local-only files, credentials, or VM data
- Prefer updating docs when operational behaviour changes

## Reporting Bugs And Requesting Features

If the repository has Discussions or issue templates enabled, use those first.
Otherwise, open a clear issue with reproduction steps, expected behaviour, your
Bazzite version, and relevant logs or screenshots.
