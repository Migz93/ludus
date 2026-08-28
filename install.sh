#!/usr/bin/env bash
# Install conservatively: build first, make login changes only after success.
set -Eeuo pipefail

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
install_root=/usr/local/lib/ludus
unit_dir=/etc/systemd/system
config_dir=/etc/ludus
install_completed=false

cleanup_install() {
  local status=$?
  rm -rf "$build_dir"
  if (( status != 0 )) && [[ "$install_completed" != true ]]; then
    echo "Installation did not complete. No automatic rollback was attempted; after resolving the error, rerun sudo ./install.sh or sudo ./uninstall.sh." >&2
  fi
  exit "$status"
}

reboot_into_staged_deployment() {
  echo
  echo "Ludus has not changed the login stack. A reboot is required to use the staged dependencies."
  echo "After it has booted, return to this checkout and run: sudo ./install.sh"
  if [[ -t 0 ]]; then
    local answer
    read -r -p "Reboot now? [y/N] " answer
    if [[ "$answer" =~ ^[Yy]([Ee][Ss])?$ ]]; then
      echo "Rebooting into the staged deployment..."
      systemctl reboot
    fi
  fi
}

restart_plasmalogin() {
  echo
  echo "The installation is complete. Plasma Login must be restarted to load the Ludus greeter."
  echo "This returns the graphical display to the login screen; it does not require a full reboot."
  if [[ -t 0 ]]; then
    local answer
    read -r -p "Restart Plasma Login now? [Y/n] " answer
    if [[ ! "$answer" =~ ^[Nn]([Oo])?$ ]]; then
      systemctl restart plasmalogin
      echo "Plasma Login restarted. Ludus is now active."
      return
    fi
  fi
  echo "To activate Ludus later, run: sudo systemctl restart plasmalogin"
}

if (( EUID != 0 )); then
  echo "Run as root: sudo $0" >&2; exit 1
fi
if ! grep -q '^ID=bazzite$' /etc/os-release; then
  echo "This installer is intentionally limited to Bazzite." >&2; exit 1
fi
expected_plasma_login=$(rpm -q --qf '%{VERSION}' plasma-login-manager 2>/dev/null || true)
if [[ -z "$expected_plasma_login" ]]; then
  echo "plasma-login-manager is not installed. Refusing private-protocol mismatch." >&2
  exit 1
fi

# rpm-ostree cannot amend a completed staged deployment.  Do not misleadingly
# attempt another transaction before it has been booted.
if rpm-ostree status --json | jq -e '.deployments[] | select(.staged == true)' >/dev/null; then
  echo "A previous run has already staged an rpm-ostree deployment."
  reboot_into_staged_deployment
  exit 0
fi

# A deployment reboot is required before any login configuration is changed.
# Complete upstream Plasma Login build closure on Fedora/Bazzite 44.
# Keep this list together so a fresh install needs only one deployment reboot.
needed=(git-core gcc checkpolicy policycoreutils-python-utils rpm-build cmake ninja-build pam-devel systemd-devel libXau-devel qt6-qtbase-devel qt6-qtdeclarative-devel qt6-qtshadertools-devel qt6-controllable extra-cmake-modules kf6-kconfig-devel kf6-kcoreaddons-devel kf6-kpackage-devel kf6-kwindowsystem-devel kf6-ki18n-devel kf6-kdbusaddons-devel kf6-kcmutils-devel kf6-kauth-devel kf6-kio-devel libplasma-devel libkscreen-devel plasma-workspace-devel layer-shell-qt-devel python3-paho-mqtt)
missing=()
for package in "${needed[@]}"; do rpm -q "$package" &>/dev/null || missing+=("$package"); done
if ((${#missing[@]})); then
  echo "Staging build dependencies in the next rpm-ostree deployment: ${missing[*]}"
  rpm-ostree install "${missing[@]}"
  reboot_into_staged_deployment
  exit 0
fi

backup=/var/lib/ludus/backups/$(date +%Y%m%d-%H%M%S)
install -d -m 0700 "$backup" /var/lib/ludus
install -d -m 0755 "$config_dir"
install -d -m 0755 "$install_root"
install -d -m 0755 /etc/systemd/user/plasma-login.service.d /usr/local/share/wayland-sessions
for file in /etc/pam.d/plasmalogin /etc/pam.d/plasmalogin-ludus /etc/systemd/user/plasma-login.service.d/ludus.conf "$unit_dir/ludus.service" /usr/local/share/wayland-sessions/ludus.desktop; do
  [[ -e "$file" ]] && install -D -m 0600 "$file" "$backup$file"
done

build_dir=$(mktemp -d /var/tmp/ludus-build.XXXXXX)
trap cleanup_install EXIT
git clone --depth 1 --branch "v$expected_plasma_login" https://invent.kde.org/plasma/plasma-login-manager.git "$build_dir/source"
install -m 0644 "$project_dir/src/Main.qml" "$build_dir/source/src/frontend/greeter/qml/Main.qml"
git -C "$build_dir/source" apply "$project_dir/patches/0001-only-show-ludus-members.patch"
git -C "$build_dir/source" apply "$project_dir/patches/0002-remote-mqtt-login-bridge.patch"
cmake -S "$build_dir/source" -B "$build_dir/build" -GNinja -DCMAKE_BUILD_TYPE=Release
ninja -C "$build_dir/build" plasma-login-greeter
install -m 0755 "$build_dir/build/bin/plasma-login-greeter" "$install_root/plasma-login-greeter"
install -m 0755 "$project_dir/src/ludus-greeter" "$install_root/ludus-greeter"
cmake -S "$project_dir/src/splash" -B "$build_dir/splash" -GNinja -DCMAKE_BUILD_TYPE=Release
ninja -C "$build_dir/splash"
install -m 0755 "$build_dir/splash/ludus-splash" "$install_root/ludus-splash"
install -m 0644 "$project_dir/src/splash/Splash.qml" "$install_root/Splash.qml"
install -m 0755 "$project_dir/src/ludus-session" "$install_root/ludus-session"
install -m 0755 "$project_dir/src/ludus-overlay" "$install_root/ludus-overlay"
install -m 0755 "$project_dir/src/ludus-steam" "$install_root/ludus-steam"
install -m 0755 "$project_dir/src/ludusctl" "$install_root/ludusctl"
install -m 0755 "$project_dir/src/ludus-disks.py" "$install_root/ludus-disks"
install -m 0755 "$project_dir/src/ludus-steam-register-libraries" "$install_root/ludus-steam-register-libraries"
install -m 0755 "$project_dir/src/ludus-steam-user-libraries.py" "$install_root/ludus-steam-user-libraries"
install -m 0755 "$project_dir/src/ludus-storage.py" "$install_root/ludus-storage"
install -m 0755 "$project_dir/src/ludus-mountd.py" "$install_root/ludus-mountd"
install -m 0755 "$project_dir/src/ludus-mountctl.py" "$install_root/ludus-mountctl"
install -m 0755 "$project_dir/src/ludus-backend.py" "$install_root/ludus-backend"
install -m 0755 "$project_dir/src/ludus-web.py" "$install_root/ludus-web"
install -m 0755 "$project_dir/src/ludus-mqtt.py" "$install_root/ludus-mqtt"
# The WebUI reads these three fixed names once at start-up and serves one
# self-contained page; no request path is ever mapped onto the filesystem.
install -d -m 0755 "$install_root/web"
install -m 0644 "$project_dir/src/web/index.html" "$install_root/web/index.html"
install -m 0644 "$project_dir/src/web/app.css" "$install_root/web/app.css"
install -m 0644 "$project_dir/src/web/app.js" "$install_root/web/app.js"
cc -O2 -Wall -Wextra -o "$install_root/ludus-pam-auth" "$project_dir/src/ludus-pam-auth.c" -lpam
install -m 0755 "$project_dir/src/ludus-web-firewall" "$install_root/ludus-web-firewall"
ln -sfn "$install_root/ludusctl" /usr/local/bin/ludusctl
install -m 0644 "$project_dir/systemd/ludus-mount.service" "$unit_dir/ludus-mount.service"
install -m 0644 "$project_dir/systemd/ludus-backend.service" "$unit_dir/ludus-backend.service"
install -m 0644 "$project_dir/systemd/ludus-web.service" "$unit_dir/ludus-web.service"
install -m 0644 "$project_dir/systemd/ludus-web-firewall.service" "$unit_dir/ludus-web-firewall.service"
install -m 0644 "$project_dir/systemd/ludus-mqtt.service" "$unit_dir/ludus-mqtt.service"
install -m 0644 "$project_dir/sessions/ludus.desktop" /usr/local/share/wayland-sessions/ludus.desktop
install -m 0644 "$project_dir/config/plasmalogin-ludus.pam" /etc/pam.d/plasmalogin-ludus
install -m 0644 "$project_dir/config/ludus-web.pam" /etc/pam.d/ludus-web
checkmodule -M -m -o "$build_dir/ludus_vscode_ssh.mod" "$project_dir/selinux/ludus-vscode-ssh.te"
semodule_package -o "$build_dir/ludus_vscode_ssh.pp" -m "$build_dir/ludus_vscode_ssh.mod"
install -m 0644 "$build_dir/ludus_vscode_ssh.pp" "$install_root/ludus_vscode_ssh.pp"
# Preserve the administrator's saved compatibility choice across a Ludus
# reinstall.  Previously every install removed this policy even when the UI
# still recorded it as enabled, leaving a misleading, broken setting.
if [[ -r "$config_dir/webui.json" ]] && python3 -c 'import json, sys; sys.exit(not json.load(open(sys.argv[1])).get("vscode_ssh_forwarding", False))' "$config_dir/webui.json"; then
  semodule -i "$install_root/ludus_vscode_ssh.pp"
else
  semodule -r ludus_vscode_ssh >/dev/null 2>&1 || true
fi
# Plasma Login's KWin compositor supplies normalised controller events directly
# to Main.qml. Remove the old external-uinput bridge during upgrades so it
# cannot duplicate navigation or activation events.
systemctl disable --now ludus.service >/dev/null 2>&1 || true
rm -f "$unit_dir/ludus.service" "$install_root/ludus-controller-bridge" "$install_root/ludus_controller.pp"
semodule -r ludus_controller >/dev/null 2>&1 || true
semanage fcontext -d "$install_root/ludus-controller-bridge" >/dev/null 2>&1 || true
install -m 0644 "$project_dir/systemd/plasma-login.service.d/ludus.conf" /etc/systemd/user/plasma-login.service.d/ludus.conf

getent group ludus >/dev/null || groupadd --system ludus
if ! getent group ludus-web >/dev/null; then
  groupadd --system ludus-web
  : > "$config_dir/created-ludus-web-group"
fi
if ! id ludus-web >/dev/null 2>&1; then
  useradd --system -g ludus-web -M -s /usr/sbin/nologin ludus-web
  : > "$config_dir/created-ludus-web-user"
fi
if [[ ! -e "$config_dir/webui.json" ]] || python3 -c 'import json, sys; sys.exit(json.load(open(sys.argv[1])).get("auth_mode") != "none")' "$config_dir/webui.json"; then
  # PAM service ludus-web authorizes only members of the local wheel group.
  # Upgrade old unauthenticated configurations to that secure default too.
  webui_config_tmp=$(mktemp "$config_dir/webui.XXXXXX")
  printf '%s\n' '{"auth_mode":"pam","listen":"0.0.0.0","port":9304}' > "$webui_config_tmp"
  chown root:ludus-web "$webui_config_tmp"; chmod 0640 "$webui_config_tmp"
  mv -f "$webui_config_tmp" "$config_dir/webui.json"
fi
# The port is not user-configurable through the WebUI.  Make upgrades follow
# the current supported endpoint without discarding authentication settings.
python3 - "$config_dir/webui.json" <<'PY'
import json
import os
import stat
import sys
import tempfile

path = sys.argv[1]
with open(path, encoding="utf-8") as source:
    config = json.load(source)
if not isinstance(config, dict):
    raise SystemExit("webui configuration must be a JSON object")
if config.get("port") != 9304:
    metadata = os.stat(path)
    config["port"] = 9304
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=os.path.dirname(path), delete=False) as temporary:
        json.dump(config, temporary, separators=(",", ":")); temporary.write("\n")
        name = temporary.name
    os.chmod(name, stat.S_IMODE(metadata.st_mode))
    os.chown(name, metadata.st_uid, metadata.st_gid)
    os.replace(name, path)
PY
[[ -e "$config_dir/libraries.conf" ]] || install -m 0644 /dev/null "$config_dir/libraries.conf"
if [[ ! -e "$config_dir/mqtt.json" ]]; then
  printf '%s\n' '{"enabled":false,"host":"","port":1883,"username":"","password":"","tls":false,"ca_cert":"","topic_prefix":""}' > "$config_dir/mqtt.json"
  chmod 0600 "$config_dir/mqtt.json"
fi
# Steam's normal per-user autostart races the Ludus launcher. Disable it
# only for explicitly enrolled Ludus accounts; the custom session owns Steam.
autostart_state="$config_dir/steam-autostart-users"
autostart_backups="$config_dir/steam-autostart-backups"
install -d -m 0700 "$autostart_backups"
while IFS=: read -r user _ _ _ _ home_dir _; do
  id -nG "$user" | tr ' ' '\n' | grep -Fxq ludus || continue
  [[ -n "$home_dir" && -d "$home_dir" ]] || continue
  install -d -o "$user" -g "$(id -gn "$user")" -m 0755 "$home_dir/.config/autostart"
  autostart_file="$home_dir/.config/autostart/steam.desktop"
  if ! grep -Fqx "$user"$'\t'"$home_dir" "$autostart_state" 2>/dev/null; then
    # Preserve the original exactly once.  A prior Ludus version kept this
    # only in its timestamped install backup, so import that copy on upgrade.
    legacy_backup=$(find /var/lib/ludus/backups -type f ! -path "$backup/*" -path "*/${home_dir#/}/.config/autostart/steam.desktop" -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 1 | cut -d' ' -f2- || true)
    if [[ -n "$legacy_backup" && -f "$legacy_backup" ]] && grep -Fqx 'Hidden=true' "$autostart_file" 2>/dev/null; then
      install -d -m 0700 "$autostart_backups/$user"
      cp -a -- "$legacy_backup" "$autostart_backups/$user/steam.desktop"
    elif [[ -f "$autostart_file" ]]; then
      install -D -m 0600 "$autostart_file" "$backup$home_dir/.config/autostart/steam.desktop"
      install -d -m 0700 "$autostart_backups/$user"
      cp -a -- "$autostart_file" "$autostart_backups/$user/steam.desktop"
    fi
    printf '%s\t%s\n' "$user" "$home_dir" >> "$autostart_state"
  fi
  printf '%s\n' '[Desktop Entry]' 'Hidden=true' > "$autostart_file"
  chown "$user:$(id -gn "$user")" "$autostart_file"
  chmod 0644 "$autostart_file"
done < <(getent passwd)
# Insert an idempotent, narrowly scoped PAM include before password-auth.
if [[ ! -e /etc/pam.d/plasmalogin ]]; then
  install -m 0644 /usr/lib/pam.d/plasmalogin /etc/pam.d/plasmalogin
  : > "$config_dir/created-pam-override"
fi
if ! grep -q 'plasmalogin-ludus' /etc/pam.d/plasmalogin; then
  sed -i '/^auth[[:space:]].*substack[[:space:]]*password-auth/i auth        include      plasmalogin-ludus' /etc/pam.d/plasmalogin
fi
# Mounting is handled by ludus-mount.service, requested by the selected user's
# launcher before Steam starts. Keeping it out of PAM avoids xdm_t SELinux
# restrictions while retaining a narrow, peer-credential-checked boundary.
sed -i '\|ludus-steam-session-mount|d' /etc/pam.d/plasmalogin
systemctl daemon-reload
systemctl enable --now ludus-mount.service
systemctl enable --now ludus-backend.service ludus-web.service ludus-web-firewall.service
systemctl enable --now ludus-mqtt.service
# An upgrade replaces entry points in place.  `enable --now` does not restart
# an already-active unit, so explicitly restart the services that keep those
# files in memory before declaring the deployment complete. MQTT is restarted
# before the backend: unlike the backend it does not own /run/ludus, avoiding
# removal of the backend's live Unix socket.
systemctl restart ludus-mqtt.service
systemctl restart ludus-backend.service ludus-web.service ludus-web-firewall.service
restart_plasmalogin
install_completed=true
echo "Backup: $backup"
