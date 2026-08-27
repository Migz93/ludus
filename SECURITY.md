<!-- shared: structure — keep headings aligned across Migz93 self-hosted apps -->

# Security Policy

## Reporting A Vulnerability

Please do not open a public GitHub issue for security-sensitive problems.

If you find a vulnerability in Ludus, report it privately through GitHub's
private vulnerability reporting flow for this repository if it is enabled. If
that is not available, contact the maintainer directly through a private channel
before disclosing details publicly.

When reporting an issue, please include:

- a short description of the problem
- the affected version or commit if known
- clear reproduction steps
- the expected impact
- any suggested mitigation if you have one

## Disclosure Expectations

- Please allow time for the issue to be investigated and fixed before public
  disclosure.
- I will try to acknowledge reports promptly and keep you updated on the status.
- Once a fix is available, the goal is to disclose the issue responsibly with
  enough detail for users to protect themselves.

## Scope

Security reports are especially helpful for issues involving:

- Plasma Login, PAM, or session handling
- privilege escalation or unsafe privileged IPC
- token, password, or MQTT secret exposure
- WebUI authentication, network exposure, or firewall configuration
- SELinux policy or file-label bypasses
- unsafe shared-library mounts, ownership, or repair behaviour
- remote code execution or unsafe default configuration

## Supported Versions

Ludus is still early in development. Until a stable release policy is
documented, security fixes are handled on the latest supported code line.

---

## Security Scanning

Run the static checks in [AGENTS.md](AGENTS.md) before opening a pull request.
Where available, use tools appropriate to the changed files, such as
ShellCheck for shell scripts, Ruff for Python, and Gitleaks for secrets. A
change to installation, PAM, systemd, SELinux, mounts, or network access also
needs review on a Bazzite Desktop KDE test machine.

### Philosophy — Fix Vs Ignore

We take security seriously, but we do not fix things for the sake of fixing
them.

**Fix it** if it is a genuine vulnerability with a realistic attack path, or
the fix improves correctness without compromising clarity.

**Mark as Won't Fix** only when the finding is demonstrably a false positive or
the proposed workaround would make the code less safe or less understandable.
Document the reasoning in the issue or pull request.
