#!/usr/bin/env bash
# Install conservatively: build first, make login changes only after success.
set -Eeuo pipefail

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
install_root=/usr/local/lib/ludus
unit_dir=/etc/systemd/system
config_dir=/etc/ludus

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
  echo "A deployment is already staged. Reboot into it before rerunning this installer."
  exit 0
fi

# A deployment reboot is required before any login configuration is changed.
# Complete upstream Plasma Login build closure on Fedora/Bazzite 44.
# Keep this list together so a fresh install needs only one deployment reboot.
needed=(rpm-build cmake ninja-build pam-devel systemd-devel libXau-devel qt6-qtbase-devel qt6-qtdeclarative-devel qt6-qtshadertools-devel extra-cmake-modules kf6-kconfig-devel kf6-kcoreaddons-devel kf6-kpackage-devel kf6-kwindowsystem-devel kf6-ki18n-devel kf6-kdbusaddons-devel kf6-kcmutils-devel kf6-kauth-devel kf6-kio-devel libplasma-devel libkscreen-devel plasma-workspace-devel layer-shell-qt-devel)
missing=()
for package in "${needed[@]}"; do rpm -q "$package" &>/dev/null || missing+=("$package"); done
if ((${#missing[@]})); then
  echo "Staging build dependencies in the next rpm-ostree deployment: ${missing[*]}"
  rpm-ostree install "${missing[@]}"
  echo "Reboot into that deployment, then rerun this installer. No login files were changed."
  exit 0
fi

backup=/var/lib/ludus/backups/$(date +%Y%m%d-%H%M%S)
install -d -m 0700 "$backup" "$config_dir"
install -d -m 0755 "$install_root"
install -d -m 0755 /etc/systemd/user/plasma-login.service.d /usr/local/share/wayland-sessions
for file in /etc/pam.d/plasmalogin /etc/pam.d/plasmalogin-ludus /etc/systemd/user/plasma-login.service.d/ludus.conf "$unit_dir/ludus.service" /usr/local/share/wayland-sessions/ludus.desktop; do
  [[ -e "$file" ]] && install -D -m 0600 "$file" "$backup$file"
done

build_dir=$(mktemp -d /var/tmp/ludus-build.XXXXXX)
trap 'rm -rf "$build_dir"' EXIT
git clone --depth 1 --branch "v$expected_plasma_login" https://invent.kde.org/plasma/plasma-login-manager.git "$build_dir/source"
install -m 0644 "$project_dir/src/Main.qml" "$build_dir/source/src/frontend/greeter/qml/Main.qml"
git -C "$build_dir/source" apply "$project_dir/patches/0001-only-show-ludus-members.patch"
cmake -S "$build_dir/source" -B "$build_dir/build" -GNinja -DCMAKE_BUILD_TYPE=Release
ninja -C "$build_dir/build" plasma-login-greeter
install -m 0755 "$build_dir/build/bin/plasma-login-greeter" "$install_root/plasma-login-greeter"
install -m 0755 "$project_dir/src/ludus-greeter" "$install_root/ludus-greeter"
cc -O2 -Wall -Wextra -o "$install_root/ludus-controller-bridge" "$project_dir/src/controller-bridge.c"
cmake -S "$project_dir/src/splash" -B "$build_dir/splash" -GNinja -DCMAKE_BUILD_TYPE=Release
ninja -C "$build_dir/splash"
install -m 0755 "$build_dir/splash/ludus-splash" "$install_root/ludus-splash"
install -m 0644 "$project_dir/src/splash/Splash.qml" "$install_root/Splash.qml"
install -m 0755 "$project_dir/src/ludus-session" "$install_root/ludus-session"
install -m 0755 "$project_dir/src/ludus-overlay" "$install_root/ludus-overlay"
install -m 0755 "$project_dir/src/ludus-steam" "$install_root/ludus-steam"
install -m 0644 "$project_dir/systemd/ludus.service" "$unit_dir/ludus.service"
install -m 0644 "$project_dir/sessions/ludus.desktop" /usr/local/share/wayland-sessions/ludus.desktop
install -m 0644 "$project_dir/config/plasmalogin-ludus.pam" /etc/pam.d/plasmalogin-ludus
install -m 0644 "$project_dir/systemd/plasma-login.service.d/ludus.conf" /etc/systemd/user/plasma-login.service.d/ludus.conf

getent group ludus >/dev/null || groupadd --system ludus
# Steam's normal per-user autostart races the Ludus launcher. Disable it
# only for explicitly enrolled Ludus accounts; the custom session owns Steam.
for user in $(getent group ludus | awk -F: '{print $4}' | tr ',' ' '); do
  home_dir=$(getent passwd "$user" | cut -d: -f6)
  [[ -n "$home_dir" && -d "$home_dir" ]] || continue
  install -d -o "$user" -g "$(id -gn "$user")" -m 0755 "$home_dir/.config/autostart"
  if [[ -f "$home_dir/.config/autostart/steam.desktop" ]] && ! grep -q '^Hidden=true$' "$home_dir/.config/autostart/steam.desktop"; then
    install -D -m 0600 "$home_dir/.config/autostart/steam.desktop" "$backup$home_dir/.config/autostart/steam.desktop"
  fi
  printf '%s\n' '[Desktop Entry]' 'Hidden=true' > "$home_dir/.config/autostart/steam.desktop"
  chown "$user:$(id -gn "$user")" "$home_dir/.config/autostart/steam.desktop"
  chmod 0644 "$home_dir/.config/autostart/steam.desktop"
done
# Insert an idempotent, narrowly scoped PAM include before password-auth.
if [[ ! -e /etc/pam.d/plasmalogin ]]; then
  install -m 0644 /usr/lib/pam.d/plasmalogin /etc/pam.d/plasmalogin
  : > "$config_dir/created-pam-override"
fi
if ! grep -q 'plasmalogin-ludus' /etc/pam.d/plasmalogin; then
  sed -i '/^auth[[:space:]].*substack[[:space:]]*password-auth/i auth        include      plasmalogin-ludus' /etc/pam.d/plasmalogin
fi
systemctl daemon-reload
systemctl enable ludus.service
echo "Ludus installed. Add intended users to ludus, then restart plasmalogin or reboot to activate it."
echo "Backup: $backup"
