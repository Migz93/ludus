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
READ = {
    "status": ["status"], "doctor": ["doctor"],
    "users.list": ["users", "list"],
    "libraries.list": ["libraries", "list"], "libraries.candidates": ["libraries", "candidates"],
    "libraries.check": ["libraries", "check"],
    "disks.list": ["disks", "list"],
}
WRITE = {
    "users.enroll": ["users", "enroll"], "users.remove": ["users", "remove"],
    "libraries.add": ["libraries", "add"], "libraries.add_default": ["libraries", "add-default"], "libraries.remove": ["libraries", "remove"],
    "libraries.repair": ["libraries", "repair"], "repair": ["repair"],
    "libraries.migrate": ["libraries", "migrate"],
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
        return {"ok": True, "auth_mode": config.get("auth_mode", "none")}
    if operation == "webui.rotate":
        return rotate_credentials(request.get("argument"))
    if operation == "webui.disable_auth":
        return disable_authentication()
    if operation == "webui.set_auth_mode":
        return set_authentication_mode(request.get("argument"))
    if operation == "webui.pam_auth":
        return pam_authentication(request.get("argument"))
    argv = READ.get(operation) or WRITE.get(operation)
    if not argv:
        raise RuntimeError("unsupported operation")
    argument = request.get("argument")
    needs_argument = operation in WRITE and operation not in {"libraries.repair", "repair"}
    if needs_argument:
        if not isinstance(argument, str) or not argument or len(argument) > 4096 or "\x00" in argument:
            raise RuntimeError("invalid argument")
        argv = [*argv, argument]
    if operation == "libraries.migrate":
        argv.append("--yes")
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
