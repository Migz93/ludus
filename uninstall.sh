#!/usr/bin/env bash
set -Eeuo pipefail
if (( EUID != 0 )); then echo "Run as root: sudo $0" >&2; exit 1; fi
force=false
if (( $# > 1 )); then echo "Usage: sudo $0 [--force]" >&2; exit 2; fi
case ${1:-} in
  "") ;;
  --force) force=true ;;
  *) echo "Usage: sudo $0 [--force]" >&2; exit 2 ;;
esac

dpi_helper=/usr/local/lib/ludus/ludus-proton-dpi
if [[ -x "$dpi_helper" ]]; then
  set +e
  dpi_blockers=$("$dpi_helper" uninstall-check)
  dpi_status=$?
  set -e
  if (( dpi_status == 2 )); then
    echo "Some games still have Ludus-managed Proton DPI settings applied:" >&2
    python3 -c '
import json, sys
for item in json.load(sys.stdin):
    location = " in {}".format(item["library"]) if item.get("library") else ""
    print("  - player {}, Steam app {}{}".format(item["user"], item["appid"], location), file=sys.stderr)
' <<<"$dpi_blockers"
    echo "Recommended: disable those settings in the WebUI, then have each listed player log in and out once so Ludus can restore their original values." >&2
    if [[ "$force" != true ]]; then
      echo "Uninstall stopped. After restoration, rerun this command; or use --force to uninstall while leaving those DPI values changed." >&2
      exit 1
    fi
    echo "Warning: --force selected; uninstalling without restoring the listed Proton DPI values." >&2
  elif (( dpi_status != 0 )); then
    echo "Could not verify whether managed Proton DPI values remain." >&2
    if [[ "$force" != true ]]; then
      echo "Uninstall stopped. Resolve the check failure or use --force to continue." >&2
      exit 1
    fi
    echo "Warning: --force selected; continuing without a successful Proton DPI check." >&2
  fi
elif [[ -e /var/lib/ludus/proton-dpi/state.json ]]; then
  echo "Proton DPI recovery state exists, but the installed safety helper is unavailable." >&2
  if [[ "$force" != true ]]; then
    echo "Uninstall stopped. Repair the Ludus installation and restore managed values, or use --force to continue without checking them." >&2
    exit 1
  fi
  echo "Warning: --force selected; continuing without checking the retained Proton DPI state." >&2
fi
launch_helper=/usr/local/lib/ludus/ludus-launch-options
if [[ -x "$launch_helper" ]]; then
  launch_status=0
  launch_blockers=$("$launch_helper" uninstall-check) || launch_status=$?
  if (( launch_status != 0 )); then
    echo "Launch-options recovery needs attention: $launch_blockers" >&2
    echo "Remove launch management in the Games page, then let affected players log in and out. Resolve conflicts or accept their manual overrides before retrying." >&2
    if [[ "$force" != true ]]; then
      echo "Uninstall stopped. Use --force only to leave the current launch options in place." >&2
      exit 1
    fi
    echo "Warning: leaving launch options unchanged; private recovery records are retained." >&2
  fi
elif [[ -e /var/lib/ludus/launch-options/users.json && "$force" != true ]]; then
  echo "Launch-options recovery records exist but the helper is missing. Repair the installation before removing it, or use --force to leave launch options unchanged." >&2
  exit 1
fi
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
systemctl disable --now ludus.service ludus-mount.service ludus-backend.service ludus-web.service ludus-web-firewall.service ludus-mqtt.service 2>/dev/null || true
# Restore only the Steam autostart files this installer explicitly took over.
# The preserved copy retains the original owner and mode; if none existed,
# Ludus created the file and it is simply removed.
if [[ -r /etc/ludus/steam-autostart-users ]]; then
  while IFS=$'\t' read -r user home_dir; do
    [[ "$user" =~ ^[a-z_][a-z0-9_-]*\$?$ && "$home_dir" == /* ]] || continue
    current_home=$(getent passwd "$user" | cut -d: -f6 || true)
    [[ "$current_home" == "$home_dir" && -d "$home_dir" ]] || continue
    autostart_file="$home_dir/.config/autostart/steam.desktop"
    preserved="/etc/ludus/steam-autostart-backups/$user/steam.desktop"
    if [[ -f "$preserved" ]]; then
      install -d -o "$user" -g "$(id -gn "$user")" -m 0755 "$home_dir/.config/autostart"
      cp -a -- "$preserved" "$autostart_file"
    else
      rm -f "$autostart_file"
    fi
  done < /etc/ludus/steam-autostart-users
fi
# Remove only the fstab records written by ludus-disks.  The data and current
# mount are deliberately left alone, but Ludus must not claim the disk after
# it has been removed.
if [[ -f /etc/fstab ]] && grep -q '^# Ludus managed shared-library disk$' /etc/fstab; then
  fstab_tmp=$(mktemp /etc/fstab.ludus.XXXXXX)
  awk '
    $0 == "# Ludus managed shared-library disk" { marker = 1; next }
    marker {
      marker = 0
      if ($1 ~ /^UUID=/ && $2 ~ /^\//) next
      print "# Ludus managed shared-library disk"
    }
    { print }
    END { if (marker) print "# Ludus managed shared-library disk" }
  ' /etc/fstab > "$fstab_tmp"
  chmod 0644 "$fstab_tmp"
  mv -f "$fstab_tmp" /etc/fstab
fi
if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
  if [[ -r /etc/ludus/webui-firewall-zone && -e /etc/ludus/webui-firewall-port-owned ]]; then
    firewall-cmd --permanent --zone="$(cat /etc/ludus/webui-firewall-zone)" --remove-port=9304/tcp >/dev/null 2>&1 || true
  fi
  firewall-cmd --reload >/dev/null 2>&1 || true
fi
rm -f /etc/systemd/system/plasmalogin.service.d/ludus.conf
rm -f /etc/systemd/user/plasma-login.service.d/ludus.conf
rm -f /etc/systemd/system/ludus.service
rm -f /etc/systemd/system/ludus-mount.service
rm -f /etc/systemd/system/ludus-backend.service
rm -f /etc/systemd/system/ludus-web.service
rm -f /etc/systemd/system/ludus-web-firewall.service
rm -f /etc/systemd/system/ludus-mqtt.service
rm -f /etc/ludus/webui-firewall-zone /etc/ludus/webui-firewall-port-owned /etc/pam.d/ludus-web
semodule -r ludus_vscode_ssh >/dev/null 2>&1 || true
semodule -r ludus_controller >/dev/null 2>&1 || true
semanage fcontext -d /usr/local/lib/ludus/ludus-controller-bridge >/dev/null 2>&1 || true
rm -f /usr/local/share/wayland-sessions/ludus.desktop
rm -f /etc/pam.d/plasmalogin-ludus
if [[ -e /etc/ludus/created-pam-override ]]; then
  rm -f /etc/pam.d/plasmalogin /etc/ludus/created-pam-override
elif [[ -f /etc/pam.d/plasmalogin ]]; then
  sed -i '/^[[:space:]]*auth[[:space:]].*plasmalogin-ludus[[:space:]]*$/d' /etc/pam.d/plasmalogin
  sed -i '\|ludus-steam-session-mount|d' /etc/pam.d/plasmalogin
fi
if [[ -e /etc/ludus/created-ludus-web-user ]] && id ludus-web >/dev/null 2>&1; then
  if ! userdel ludus-web; then
    echo "Warning: could not remove installer-created ludus-web user; remove it manually after its processes exit." >&2
  fi
fi
if [[ -e /etc/ludus/created-ludus-web-group ]] && ! getent passwd ludus-web >/dev/null && getent group ludus-web >/dev/null; then
  if ! groupdel ludus-web; then
    echo "Warning: could not remove installer-created ludus-web group; it may still be in use." >&2
  fi
fi
rm -f /usr/local/bin/ludusctl
rm -rf /usr/local/lib/ludus /etc/ludus
rm -rf /var/cache/ludus
systemctl daemon-reload
echo "Ludus removed. Normal Plasma Login is restored; restart plasmalogin or reboot when safe."
echo "Ludus build dependencies layered with rpm-ostree were intentionally kept. To remove only packages you no longer need, run rpm-ostree status, then sudo rpm-ostree uninstall <package...> and reboot."
