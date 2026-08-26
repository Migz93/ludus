#!/usr/bin/env python3
"""Root-only Ludus bind-mount service. SPDX-License-Identifier: GPL-3.0-or-later"""
import grp
import json
import os
import pwd
import socket
import stat
import subprocess

SOCKET = "/run/ludus/mount.sock"
ACTIVE_USER = "/run/ludus/active-user"
LIBRARIES = "/etc/ludus/libraries.conf"
GROUP = "ludus"

def libraries():
    try:
        with open(LIBRARIES, encoding="utf-8") as file:
            return [line.strip() for line in file if line.strip() and not line.startswith("#")]
    except FileNotFoundError:
        return []

def member(user):
    return user in grp.getgrnam(GROUP).gr_mem or pwd.getpwnam(user).pw_gid == grp.getgrnam(GROUP).gr_gid

def private_dir(user, library, name):
    home = pwd.getpwnam(user).pw_dir
    ident = __import__("hashlib").sha256(library.encode()).hexdigest()[:16]
    path = os.path.join(home, ".local", "share", "ludus", "steam-libraries", ident, name)
    os.makedirs(path, mode=0o700, exist_ok=True)
    account = pwd.getpwnam(user)
    os.chown(path, account.pw_uid, account.pw_gid)
    os.chmod(path, 0o700)
    return path

def mounted(target):
    return subprocess.run(["mountpoint", "-q", target], check=False).returncode == 0

def mount_for(user):
    if os.path.exists(ACTIVE_USER):
        with open(ACTIVE_USER, encoding="utf-8") as file:
            active = file.read().strip()
        if active and active != user:
            raise RuntimeError(f"another Ludus session is active: {active}")
    for library in libraries():
        for name in ("compatdata", "shadercache"):
            target = os.path.join(library, "steamapps", name)
            if not os.path.isdir(target):
                raise RuntimeError(f"missing Ludus private bind target: {target}")
            if mounted(target):
                subprocess.run(["umount", target], check=True)
            subprocess.run(["mount", "--bind", private_dir(user, library, name), target], check=True)
    with open(ACTIVE_USER, "w", encoding="utf-8") as file:
        file.write(user + "\n")
    os.chmod(ACTIVE_USER, 0o600)

def unmount_for(user):
    if os.path.exists(ACTIVE_USER):
        with open(ACTIVE_USER, encoding="utf-8") as file:
            active = file.read().strip()
        if active and active != user:
            raise RuntimeError("only the active Ludus user may remove its mounts")
    for library in libraries():
        for name in ("compatdata", "shadercache"):
            target = os.path.join(library, "steamapps", name)
            if mounted(target):
                subprocess.run(["umount", target], check=True)
    try: os.unlink(ACTIVE_USER)
    except FileNotFoundError: pass

def peer_user(connection):
    credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
    pid = int.from_bytes(credentials[0:4], "little")
    uid = int.from_bytes(credentials[4:8], "little")
    del pid
    return pwd.getpwuid(uid).pw_name

def handle(connection):
    user = peer_user(connection)
    try:
        request = json.loads(connection.recv(4096).decode("utf-8"))
        if request.get("action") not in {"mount", "unmount"} or not member(user):
            raise RuntimeError("request is not permitted")
        if request["action"] == "mount": mount_for(user)
        else: unmount_for(user)
        response = {"ok": True}
    except Exception as error:
        response = {"ok": False, "error": str(error)}
    connection.sendall(json.dumps(response).encode("utf-8"))

os.makedirs(os.path.dirname(SOCKET), mode=0o755, exist_ok=True)
try: os.unlink(SOCKET)
except FileNotFoundError: pass
server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
server.bind(SOCKET)
os.chown(SOCKET, 0, grp.getgrnam(GROUP).gr_gid)
os.chmod(SOCKET, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP)
server.listen(8)
while True:
    connection, _ = server.accept()
    with connection: handle(connection)
