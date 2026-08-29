#!/usr/bin/env python3
"""Narrow root API for the unprivileged Ludus WebUI. GPL-3.0-or-later."""
import grp
import hashlib
import json
import os
import pwd
import socket
import struct
import subprocess
import time

SOCKET = "/run/ludus/backend.sock"
GROUP = "ludus-web"
CTL = "/usr/local/bin/ludusctl"
PAM_HELPER = "/usr/local/lib/ludus/ludus-pam-auth"
WEB_CONFIG = "/etc/ludus/webui.json"
MQTT_CONFIG = "/etc/ludus/mqtt.json"
MQTT_STATUS = "/run/ludus/mqtt-status.json"
MQTT_HELPER = "/usr/local/lib/ludus/ludus-mqtt"
VSCODE_POLICY = "/usr/local/lib/ludus/ludus_vscode_ssh.pp"
GREETER_DISPLAY_CONFIG = "/etc/ludus/greeter-display.json"
READ = {
    "status": ["status"], "doctor": ["doctor"],
    # Read-only structured reporting for the WebUI. Neither command changes
    # any system state; both take no argument.
    "doctor.json": ["doctor", "--json"],
    "storage": ["storage"],
    "users.list": ["users", "list"],
    "users.personal_libraries": ["users", "personal-libraries"],
    "libraries.list": ["libraries", "list"], "libraries.default": ["libraries", "default"], "libraries.candidates": ["libraries", "candidates"],
    "libraries.check": ["libraries", "check"],
    "disks.list": ["disks", "list"],
}
WRITE = {
    "users.enroll": ["users", "enroll"], "users.remove": ["users", "remove"],
    "users.remove_personal_library": ["users", "remove-personal-library"],
    "libraries.add": ["libraries", "add"], "libraries.add_default": ["libraries", "add-default"], "libraries.remove": ["libraries", "remove"], "libraries.set_default": ["libraries", "set-default"], "libraries.label": ["libraries", "label"],
    "libraries.repair": ["libraries", "repair"], "repair": ["repair"],
    "disks.mount": ["disks", "mount"],
}


def peer_ok(connection):
    """Only the dedicated WebUI account/group may use this root socket."""
    credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
    _pid, uid, _gid = struct.unpack("3i", credentials)
    account = pwd.getpwuid(uid)
    groups = os.getgrouplist(account.pw_name, account.pw_gid)
    return grp.getgrnam(GROUP).gr_gid in groups


def receive(connection):
    deadline = time.monotonic() + 5
    chunks, size = [], 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("request timed out")
        connection.settimeout(remaining)
        chunk = connection.recv(min(8192 - size + 1, 4096))
        if not chunk:
            raise RuntimeError("incomplete request")
        chunks.append(chunk)
        size += len(chunk)
        if size > 8192:
            raise RuntimeError("invalid request size")
        data = b"".join(chunks)
        if b"\n" in data:
            frame, trailing = data.split(b"\n", 1)
            if trailing.strip():
                raise RuntimeError("invalid request framing")
            break
    if not frame:
        raise RuntimeError("invalid request size")
    request = json.loads(frame)
    if not isinstance(request, dict):
        raise RuntimeError("invalid request")
    return request


def rotate_credentials(argument):
    if not isinstance(argument, dict):
        raise RuntimeError("invalid credential request")
    username, password = argument.get("username"), argument.get("password")
    if not isinstance(username, str) or not username or len(username) > 64 or any(c.isspace() or c == ":" for c in username):
        raise RuntimeError("username must be 1-64 characters without spaces or colons")
    if not isinstance(password, str) or not password or len(password) > 1024:
        raise RuntimeError("password is required and may be at most 1024 characters")
    with open(WEB_CONFIG, encoding="utf-8") as config_file:
        config = json.load(config_file)
    config["username"] = username
    config["password_sha256"] = hashlib.sha256(password.encode()).hexdigest()
    # Saving local credentials must not silently replace a selected pam+local
    # mode.  The Settings selector owns the authentication policy.
    config["auth_mode"] = config.get("auth_mode", "local")
    write_config(config)
    return {"ok": True, "output": "WebUI password authentication enabled and updated."}


def write_config(config):
    temporary = WEB_CONFIG + ".new"
    with open(temporary, "w", encoding="utf-8") as config_file:
        json.dump(config, config_file, separators=(",", ":"))
        config_file.write("\n")
    os.chown(temporary, 0, grp.getgrnam(GROUP).gr_gid)
    os.chmod(temporary, 0o640)
    os.replace(temporary, WEB_CONFIG)


def disable_authentication():
    with open(WEB_CONFIG, encoding="utf-8") as config_file:
        config = json.load(config_file)
    config["auth_mode"] = "none"
    write_config(config)
    return {"ok": True, "output": "WebUI authentication disabled."}

def set_authentication_mode(argument):
    if argument not in {"none", "local", "pam", "pam+local"}:
        raise RuntimeError("invalid authentication mode")
    with open(WEB_CONFIG, encoding="utf-8") as config_file:
        config = json.load(config_file)
    if argument in {"local", "pam+local"} and not config.get("username"):
        raise RuntimeError("set a local username and password before enabling local authentication")
    config["auth_mode"] = argument
    write_config(config)
    return {"ok": True, "output": "WebUI authentication mode updated."}

def vscode_policy_installed():
    """Return whether the optional VS Code SELinux policy is active."""
    result = subprocess.run(["semodule", "-l"], text=True, capture_output=True,
                            timeout=30, check=False)
    return result.returncode == 0 and any(
        line.split(maxsplit=1)[0] == "ludus_vscode_ssh"
        for line in result.stdout.splitlines() if line.split()
    )

def set_vscode_forwarding(argument):
    if not isinstance(argument, bool): raise RuntimeError("invalid VS Code setting")
    if argument:
        subprocess.run(["semodule", "-i", VSCODE_POLICY], check=True, timeout=30)
    else:
        subprocess.run(["semodule", "-r", "ludus_vscode_ssh"], check=False, timeout=30)
    with open(WEB_CONFIG, encoding="utf-8") as config_file: config = json.load(config_file)
    config["vscode_ssh_forwarding"] = argument
    write_config(config)
    return {"ok": True, "output": "VS Code Remote SSH forwarding setting updated."}

def repair_vscode_forwarding():
    """Restore the policy only when the administrator has opted into it."""
    with open(WEB_CONFIG, encoding="utf-8") as config_file:
        config = json.load(config_file)
    if not config.get("vscode_ssh_forwarding", False):
        raise RuntimeError("VS Code Remote SSH forwarding is turned off in Settings")
    subprocess.run(["semodule", "-i", VSCODE_POLICY], check=True, timeout=30)
    if not vscode_policy_installed():
        raise RuntimeError("the VS Code SELinux policy could not be confirmed after repair")
    return {"ok": True, "output": "VS Code Remote SSH forwarding policy restored."}


def greeter_display_settings():
    try:
        with open(GREETER_DISPLAY_CONFIG, encoding="utf-8") as source:
            config = json.load(source)
    except (OSError, ValueError):
        config = {}
    return {"ok": True, "configured": bool(config), "width": config.get("width"),
            "height": config.get("height"), "refresh": config.get("refresh"),
            "scale": config.get("scale")}


def save_greeter_display_settings(argument):
    if not isinstance(argument, dict):
        raise RuntimeError("invalid login display configuration")
    width, height, refresh, scale = (argument.get(key) for key in ("width", "height", "refresh", "scale"))
    if (not isinstance(width, int) or not isinstance(height, int)
            or not isinstance(refresh, (int, float)) or isinstance(refresh, bool)
            or not isinstance(scale, (int, float)) or isinstance(scale, bool)):
        raise RuntimeError("resolution, refresh rate and scale are required")
    if not (640 <= width <= 8192 and 480 <= height <= 8192):
        raise RuntimeError("invalid login resolution")
    if not 23 <= refresh <= 360:
        raise RuntimeError("refresh rate must be between 23 and 360 Hz")
    if scale not in {1, 1.25, 1.5, 1.75, 2}:
        raise RuntimeError("invalid login display scale")
    config = {"width": width, "height": height, "refresh": refresh, "scale": scale}
    temporary = GREETER_DISPLAY_CONFIG + ".new"
    with open(temporary, "w", encoding="utf-8") as target:
        json.dump(config, target, separators=(",", ":")); target.write("\n")
    os.chown(temporary, 0, 0); os.chmod(temporary, 0o644); os.replace(temporary, GREETER_DISPLAY_CONFIG)
    return {"ok": True, "output": "Login screen display settings saved. They apply the next time Plasma Login starts."}

def pam_authentication(argument):
    if not isinstance(argument, dict): raise RuntimeError("invalid PAM credentials")
    username, password = argument.get("username"), argument.get("password")
    if not isinstance(username, str) or not username or len(username) > 64 or not username.replace("-", "").replace("_", "").isalnum(): raise RuntimeError("invalid username")
    if not isinstance(password, str) or not password or len(password) > 1024: raise RuntimeError("invalid password")
    result = subprocess.run([PAM_HELPER, username], input=password + "\n", text=True, capture_output=True, timeout=15, check=False)
    return {"ok": result.returncode == 0, "error": "invalid administrator credentials" if result.returncode else ""}


def mqtt_settings():
    try:
        with open(MQTT_CONFIG, encoding="utf-8") as source: config = json.load(source)
    except (OSError, ValueError): config = {}
    try:
        with open(MQTT_STATUS, encoding="utf-8") as source: status = json.load(source)
    except (OSError, ValueError): status = {}
    return {"ok": True, "enabled": bool(config.get("enabled", False)),
            "host": str(config.get("host", "")), "port": config.get("port", 1883),
            "username": str(config.get("username", "")), "password_set": bool(config.get("password", "")),
            "tls": bool(config.get("tls", False)), "ca_cert": str(config.get("ca_cert", "")),
            "topic_prefix": str(config.get("topic_prefix", "")), "status": status}


def save_mqtt_settings(argument):
    if not isinstance(argument, dict): raise RuntimeError("invalid MQTT configuration")
    enabled, tls = argument.get("enabled"), argument.get("tls")
    host, username, prefix, ca_cert = (argument.get("host"), argument.get("username"),
                                       argument.get("topic_prefix"), argument.get("ca_cert", ""))
    if not isinstance(enabled, bool) or not isinstance(tls, bool): raise RuntimeError("invalid MQTT setting")
    if not all(isinstance(value, str) for value in (host, username, prefix, ca_cert)):
        raise RuntimeError("invalid MQTT setting")
    try: port = int(argument.get("port", 1883))
    except (TypeError, ValueError): raise RuntimeError("MQTT port must be a number")
    if not 1 <= port <= 65535: raise RuntimeError("MQTT port must be between 1 and 65535")
    if len(host) > 255 or any(char.isspace() for char in host) or (enabled and not host):
        raise RuntimeError("MQTT broker host is required and cannot contain spaces")
    if len(username) > 256 or any(char in username for char in "\x00\r\n"):
        raise RuntimeError("invalid MQTT username")
    if len(prefix) > 255 or prefix.startswith("/") or prefix.endswith("/") or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-/" for char in prefix):
        raise RuntimeError("MQTT topic prefix may contain only letters, numbers, hyphens, underscores and slashes")
    if ca_cert and (not ca_cert.startswith("/") or len(ca_cert) > 4096 or "\x00" in ca_cert):
        raise RuntimeError("CA certificate must be an absolute path")
    try:
        with open(MQTT_CONFIG, encoding="utf-8") as source: old = json.load(source)
    except (OSError, ValueError): old = {}
    password = argument.get("password")
    if password is not None:
        if not isinstance(password, str) or len(password) > 1024: raise RuntimeError("invalid MQTT password")
    else:
        password = old.get("password", "")
    config = {"enabled": enabled, "host": host, "port": port, "username": username,
              "password": password, "tls": tls, "ca_cert": ca_cert, "topic_prefix": prefix}
    temporary = MQTT_CONFIG + ".new"
    with open(temporary, "w", encoding="utf-8") as target:
        json.dump(config, target, separators=(",", ":")); target.write("\n")
    os.chmod(temporary, 0o600); os.replace(temporary, MQTT_CONFIG)
    subprocess.run(["systemctl", "enable", "--now", "ludus-mqtt.service"], check=True, timeout=30)
    subprocess.run(["systemctl", "restart", "ludus-mqtt.service"], check=True, timeout=30)
    return {"ok": True, "output": "MQTT settings saved and service restarted."}


def test_mqtt():
    completed = subprocess.run([MQTT_HELPER, "--test"], text=True, capture_output=True,
                               timeout=20, check=False)
    return {"ok": completed.returncode == 0, "output": completed.stdout, "error": completed.stderr}


def dispatch(request):
    operation = request.get("operation")
    if operation == "webui.settings":
        with open(WEB_CONFIG, encoding="utf-8") as config_file:
            config = json.load(config_file)
        # The username is not a secret (it is sent openly on every sign-in
        # attempt); exposing it lets the WebUI pre-fill the credentials form.
        # The password hash is never returned.
        return {"ok": True, "auth_mode": config.get("auth_mode", "none"),
                # The saved choice and the live SELinux state can differ after
                # an administrative policy rebuild.  Return both so the UI
                # never presents an unavailable rule as working.
                "vscode_ssh_forwarding_requested": config.get("vscode_ssh_forwarding", False),
                "vscode_ssh_forwarding": vscode_policy_installed(),
                "username": config.get("username", "")}
    if operation == "mqtt.settings": return mqtt_settings()
    if operation == "greeter.display.settings": return greeter_display_settings()
    if operation == "greeter.display.save": return save_greeter_display_settings(request.get("argument"))
    if operation == "mqtt.save": return save_mqtt_settings(request.get("argument"))
    if operation == "mqtt.test": return test_mqtt()
    if operation == "webui.rotate":
        return rotate_credentials(request.get("argument"))
    if operation == "webui.disable_auth":
        return disable_authentication()
    if operation == "webui.set_auth_mode":
        return set_authentication_mode(request.get("argument"))
    if operation == "webui.set_vscode_forwarding":
        return set_vscode_forwarding(request.get("argument"))
    if operation == "webui.repair_vscode_forwarding":
        return repair_vscode_forwarding()
    if operation == "webui.pam_auth":
        return pam_authentication(request.get("argument"))
    argv = READ.get(operation) or WRITE.get(operation)
    if not argv:
        raise RuntimeError("unsupported operation")
    argument = request.get("argument")
    if operation == "disks.mount":
        if not isinstance(argument, dict):
            raise RuntimeError("invalid disk mount request")
        path, mountpoint = argument.get("path"), argument.get("mountpoint", "/mnt/games")
        if not isinstance(path, str) or not path or not isinstance(mountpoint, str) or not mountpoint:
            raise RuntimeError("invalid disk mount request")
        argv = [*argv, path, mountpoint]
        completed = subprocess.run([CTL, *argv], text=True, capture_output=True, timeout=3600, check=False)
        return {"ok": completed.returncode == 0, "output": completed.stdout, "error": completed.stderr}
    if operation == "users.remove_personal_library":
        if not isinstance(argument, dict): raise RuntimeError("invalid personal library removal request")
        user, path = argument.get("user"), argument.get("path")
        if not isinstance(user, str) or not user or not isinstance(path, str) or not path.startswith("/") or len(path) > 4096 or "\x00" in path:
            raise RuntimeError("invalid personal library removal request")
        completed = subprocess.run([CTL, *argv, user, path], text=True, capture_output=True, timeout=3600, check=False)
        return {"ok": completed.returncode == 0, "output": completed.stdout, "error": completed.stderr}
    if operation == "libraries.label":
        if not isinstance(argument, dict): raise RuntimeError("invalid shared library label request")
        path, label = argument.get("path"), argument.get("label")
        if not isinstance(path, str) or not path.startswith("/") or len(path) > 4096 or "\x00" in path:
            raise RuntimeError("invalid shared library path")
        if not isinstance(label, str) or len(label) > 64 or any(character in label for character in ('\x00', '\n', '\r', '"', '\\')):
            raise RuntimeError("invalid shared library label")
        completed = subprocess.run([CTL, *argv, path, label], text=True, capture_output=True, timeout=3600, check=False)
        return {"ok": completed.returncode == 0, "output": completed.stdout, "error": completed.stderr}
    needs_argument = operation in WRITE and operation not in {"libraries.repair", "repair"}
    if needs_argument:
        if not isinstance(argument, str) or not argument or len(argument) > 4096 or "\x00" in argument:
            raise RuntimeError("invalid argument")
        argv = [*argv, argument]
    completed = subprocess.run([CTL, *argv], text=True, capture_output=True, timeout=3600, check=False)
    return {"ok": completed.returncode == 0, "output": completed.stdout, "error": completed.stderr}


def handle(connection):
    try:
        if not peer_ok(connection):
            raise RuntimeError("unauthorised local client")
        response = dispatch(receive(connection))
    except Exception as error:
        response = {"ok": False, "error": str(error)}
    try:
        connection.settimeout(5)
        connection.sendall(json.dumps(response).encode())
    except OSError:
        # The WebUI may abandon a long-running request. Its operation can
        # still complete safely; losing the reply must not kill this daemon.
        pass


def main():
    os.makedirs("/run/ludus", exist_ok=True)
    try:
        os.unlink(SOCKET)
    except FileNotFoundError:
        pass
    server = socket.socket(socket.AF_UNIX)
    server.bind(SOCKET)
    os.chown(SOCKET, 0, grp.getgrnam(GROUP).gr_gid)
    os.chmod(SOCKET, 0o660)
    server.listen()
    while True:
        client, _address = server.accept()
        with client:
            handle(client)


if __name__ == "__main__":
    main()
