#!/usr/bin/env bash
set -Eeuo pipefail
if (( EUID != 0 )); then echo "Run as root: sudo $0" >&2; exit 1; fi
systemctl disable --now ludus.service 2>/dev/null || true
rm -f /etc/systemd/system/plasmalogin.service.d/ludus.conf
rm -f /etc/systemd/user/plasma-login.service.d/ludus.conf
rm -f /etc/systemd/system/ludus.service
rm -f /usr/local/share/wayland-sessions/ludus.desktop
rm -f /etc/pam.d/plasmalogin-ludus
if [[ -e /etc/ludus/created-pam-override ]]; then
  rm -f /etc/pam.d/plasmalogin /etc/ludus/created-pam-override
elif [[ -f /etc/pam.d/plasmalogin ]]; then
  sed -i '/^[[:space:]]*auth[[:space:]].*plasmalogin-ludus[[:space:]]*$/d' /etc/pam.d/plasmalogin
fi
rm -rf /usr/local/lib/ludus /etc/ludus
systemctl daemon-reload
echo "Ludus removed. Normal Plasma Login is restored; restart plasmalogin or reboot when safe."
