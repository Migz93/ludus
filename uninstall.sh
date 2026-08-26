#!/usr/bin/env bash
set -Eeuo pipefail
if (( EUID != 0 )); then echo "Run as root: sudo $0" >&2; exit 1; fi
if pgrep -x steam >/dev/null 2>&1 || pgrep -x steamwebhelper >/dev/null 2>&1; then
  echo "Steam is still running. Sign out of Ludus and close Steam before uninstalling." >&2
  exit 1
fi
# Remove only Ludus' per-session bind mounts. Shared libraries and every user's
# private Steam data are intentionally left in place.
if [[ -r /etc/ludus/libraries.conf ]]; then
  while IFS= read -r library || [[ -n "$library" ]]; do
    [[ -z "$library" || "$library" == \#* ]] && continue
    for name in compatdata shadercache; do
      target="$library/steamapps/$name"
      [[ -d "$target" ]] || continue
      if nsenter --mount=/proc/1/ns/mnt -- mountpoint -q "$target"; then
        nsenter --mount=/proc/1/ns/mnt -- umount "$target"
      fi
    done
  done < /etc/ludus/libraries.conf
fi
systemctl disable --now ludus.service ludus-mount.service ludus-backend.service ludus-web.service ludus-web-firewall.service 2>/dev/null || true
if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
  firewall-cmd --permanent --zone=ludus --remove-port=9876/tcp >/dev/null 2>&1 || true
  firewall-cmd --reload >/dev/null 2>&1 || true
fi
rm -f /etc/systemd/system/plasmalogin.service.d/ludus.conf
rm -f /etc/systemd/user/plasma-login.service.d/ludus.conf
rm -f /etc/systemd/system/ludus.service
rm -f /etc/systemd/system/ludus-mount.service
rm -f /etc/systemd/system/ludus-backend.service
rm -f /etc/systemd/system/ludus-web.service
rm -f /etc/systemd/system/ludus-web-firewall.service
rm -f /usr/local/share/wayland-sessions/ludus.desktop
rm -f /etc/pam.d/plasmalogin-ludus
if [[ -e /etc/ludus/created-pam-override ]]; then
  rm -f /etc/pam.d/plasmalogin /etc/ludus/created-pam-override
elif [[ -f /etc/pam.d/plasmalogin ]]; then
  sed -i '/^[[:space:]]*auth[[:space:]].*plasmalogin-ludus[[:space:]]*$/d' /etc/pam.d/plasmalogin
  sed -i '\|ludus-steam-session-mount|d' /etc/pam.d/plasmalogin
fi
rm -f /usr/local/bin/ludusctl
rm -rf /usr/local/lib/ludus /etc/ludus
systemctl daemon-reload
echo "Ludus removed. Normal Plasma Login is restored; restart plasmalogin or reboot when safe."
