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

SOCKET = "/run/ludus/backend.sock"
GROUP = "ludus-web"
CTL = "/usr/local/bin/ludusctl"
PAM_HELPER = "/usr/local/lib/ludus/ludus-pam-auth"
WEB_CONFIG = "/etc/ludus/webui.json"
VSCODE_POLICY = "/usr/local/lib/ludus/ludus_vscode_ssh.pp"
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
    data = connection.recv(8193)
    if not data or len(data) > 8192:
        raise RuntimeError("invalid request size")
    request = json.loads(data)
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

def pam_authentication(argument):
    if not isinstance(argument, dict): raise RuntimeError("invalid PAM credentials")
    username, password = argument.get("username"), argument.get("password")
    if not isinstance(username, str) or not username or len(username) > 64 or not username.replace("-", "").replace("_", "").isalnum(): raise RuntimeError("invalid username")
    if not isinstance(password, str) or not password or len(password) > 1024: raise RuntimeError("invalid password")
    result = subprocess.run([PAM_HELPER, username], input=password + "\n", text=True, capture_output=True, timeout=15, check=False)
    return {"ok": result.returncode == 0, "error": "invalid administrator credentials" if result.returncode else ""}


def dispatch(request):
    operation = request.get("operation")
    if operation == "webui.settings":
        with open(WEB_CONFIG, encoding="utf-8") as config_file:
            config = json.load(config_file)
        # The username is not a secret (it is sent openly on every sign-in
        # attempt); exposing it lets the WebUI pre-fill the credentials form.
        # The password hash is never returned.
        return {"ok": True, "auth_mode": config.get("auth_mode", "none"), "vscode_ssh_forwarding": config.get("vscode_ssh_forwarding", False), "username": config.get("username", "")}
    if operation == "webui.rotate":
        return rotate_credentials(request.get("argument"))
    if operation == "webui.disable_auth":
        return disable_authentication()
    if operation == "webui.set_auth_mode":
        return set_authentication_mode(request.get("argument"))
    if operation == "webui.set_vscode_forwarding":
        return set_vscode_forwarding(request.get("argument"))
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
    connection.sendall(json.dumps(response).encode())


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
