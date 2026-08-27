# Management WebUI

## Access Model

The management WebUI listens on port `9304`. It is intended for a trusted wired
LAN, authenticated VPN, or TLS-terminating reverse proxy — never exposure to
the public internet or an untrusted Wi-Fi network.

The service only opens the port in a `home`, `internal`, `trusted`, or
`FedoraWorkstation` firewalld zone. The HTTP server accepts loopback and
directly connected private IPv4 subnets. If the active zone is unsupported,
configure it before enabling LAN access.

The built-in server is HTTP-only. HTTP Basic/PAM credentials are plaintext on
the network without an external TLS layer.

## Authentication

The default authentication mode is PAM for local `wheel` administrators. Sign
in with that administrator's regular Linux password. Settings can instead use a
local Ludus account or allow either method.

The frontend sends requests to the unprivileged HTTP service; it passes
privileged operations to the backend via `/run/ludus/backend.sock`. Do not add
an HTTP endpoint that directly shells out or bypasses the backend's validation.

## Capabilities

- enrol and remove players without deleting Linux accounts or home data
- manage shared-library records, labels, validation, and safe repair
- inspect Ludus services, mounts, storage, and `ludusctl doctor` results
- adopt an existing compatible disk without deleting its data
- rotate WebUI credentials and configure permitted authentication modes
- configure and test the optional Home Assistant MQTT integration

## Operational Checks

Run `sudo ludusctl doctor` to check the configuration, service sockets,
firewall state, Steam launcher, mount state, and SELinux policy. The WebUI
presents the same structured `ludusctl doctor --json` information.
