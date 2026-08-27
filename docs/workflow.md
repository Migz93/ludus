<!-- shared: structure — keep headings aligned across Migz93 self-hosted apps -->

# Workflow

## Branches And Pull Requests

`main` is the stable branch. Create a focused work branch using a semantic
prefix such as `feat/`, `fix/`, `chore/`, `docs/`, or `ci/`. Use a matching
semantic PR title and state any installation, login, PAM, systemd, SELinux,
Steam, WebUI, firewall, or MQTT impact.

## Review

Before asking to open a pull request, review the changed paths and run the
static checks relevant to them. For significant changes, offer the user a
choice between cross-AI review, a CodeRabbit CLI review, or proceeding to the
PR. Do not open the PR until the user asks to proceed.

Use CodeRabbit with the repository context when available:

```bash
coderabbit review --agent --base main -c AGENTS.md
```

## Releases

Before a release, verify the installer and uninstaller from a clean local
checkout on a supported Bazzite Desktop KDE system where practical. Record the
Bazzite/Plasma Login version used for validation, update lasting technical docs,
and ensure recovery behaviour is still documented.

## Logs And Comments

- Write operational logs that identify the failed Ludus subsystem and actionable
  next step.
- Do not log passwords, MQTT secrets, tokens, or unnecessary player data.
- Keep code comments focused on security boundaries, unusual platform
  constraints, or reasoning that cannot be made obvious in the code.
