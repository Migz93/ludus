#!/usr/bin/env python3
"""Root-only Ludus bind-mount service. SPDX-License-Identifier: GPL-3.0-or-later"""
import grp
import json
import os
import pwd
import socket
import stat
import subprocess
import time

SOCKET = "/run/ludus-mount/mount.sock"
ACTIVE_USER = "/run/ludus-mount/active-user"
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

def session_live(user):
    """Whether the recorded user still owns the session that uses the binds."""
    try:
        uid = str(pwd.getpwnam(user).pw_uid)
    except KeyError:
        return False
    # ludus-steam covers the short startup window before Steam itself appears.
    return subprocess.run(
        ["pgrep", "-u", uid, "-f", r"(^|/)(ludus-steam|steam|steamwebhelper|bazzite-steam)( |$)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    ).returncode == 0

def mount_for(user):
    if os.path.exists(ACTIVE_USER):
        with open(ACTIVE_USER, encoding="utf-8") as file:
            active = file.read().strip()
        if active and active != user:
            if session_live(active):
                raise RuntimeError(f"another Ludus session is active: {active}")
            # A forced logout can bypass ludus-steam's EXIT trap.  Recover on
            # the next legitimate login rather than leaving the console stuck.
            unmount_for(active)
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

def unmount_active():
    """Privileged recovery/remote-control cleanup for the recorded session."""
    try:
        with open(ACTIVE_USER, encoding="utf-8") as file:
            user = file.read().strip()
    except FileNotFoundError:
        return
    if user:
        unmount_for(user)

def peer_user(connection):
    credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
    pid = int.from_bytes(credentials[0:4], "little")
    uid = int.from_bytes(credentials[4:8], "little")
    del pid
    return pwd.getpwuid(uid).pw_name

def receive(connection):
    deadline = time.monotonic() + 5
    chunks, size = [], 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("request timed out")
        connection.settimeout(remaining)
        chunk = connection.recv(min(4096 - size + 1, 4096))
        if not chunk:
            raise RuntimeError("incomplete request")
        chunks.append(chunk)
        size += len(chunk)
        if size > 4096:
            raise RuntimeError("invalid request size")
        data = b"".join(chunks)
        if b"\n" in data:
            frame, trailing = data.split(b"\n", 1)
            if trailing.strip():
                raise RuntimeError("invalid request framing")
            break
    if not frame:
        raise RuntimeError("invalid request")
    request = json.loads(frame.decode("utf-8"))
    if not isinstance(request, dict):
        raise RuntimeError("invalid request")
    return request

def handle(connection):
    user = peer_user(connection)
    try:
        request = receive(connection)
        action = request.get("action")
        # Normal users may only mount/unmount their own session. The one
        # additional operation is root-only and is used after logind has
        # terminated a remote session, when its shell EXIT trap may not run.
        if action == "unmount-active" and user == "root":
            unmount_active()
        elif action not in {"mount", "unmount"} or not member(user):
            raise RuntimeError("request is not permitted")
        elif action == "mount": mount_for(user)
        else: unmount_for(user)
        response = {"ok": True}
    except Exception as error:
        response = {"ok": False, "error": str(error)}
    try:
        connection.settimeout(5)
        connection.sendall(json.dumps(response).encode("utf-8"))
    except OSError:
        # A group member may close its local client early. Do not let that
        # terminate the serial mount daemon after the request was handled.
        pass

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
