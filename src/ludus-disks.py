#!/usr/bin/env python3
"""Safely adopt existing, unmounted Linux filesystems for Ludus. GPL-3.0-or-later."""
import json, os, re, subprocess, sys, tempfile

ALLOWED = {"btrfs", "ext4", "xfs"}

def size_of(device):
    # -b reports SIZE in bytes; older util-linux versions still emit a string.
    try: return int(device.get("size"))
    except (TypeError, ValueError): return None

def candidates():
    data = json.loads(subprocess.check_output(["lsblk", "-J", "-b", "-o", "PATH,TYPE,FSTYPE,UUID,LABEL,SIZE,MOUNTPOINTS"], text=True))
    result = []
    for device in data["blockdevices"]:
        if device["type"] != "part" or device["fstype"] not in ALLOWED or not device["uuid"] or any(device["mountpoints"]): continue
        result.append({"path":device["path"], "fstype":device["fstype"], "uuid":device["uuid"], "label":device["label"] or "", "size":size_of(device), "mountpoint":"/mnt/games"})
    return result

def mount(path, requested_target="/mnt/games"):
    device = next((item for item in candidates() if item["path"] == path), None)
    if not device: raise RuntimeError("not an eligible unmounted partition")
    if not isinstance(requested_target, str) or not requested_target.startswith("/") or "\x00" in requested_target:
        raise RuntimeError("mount point must be an absolute path")
    target = os.path.abspath(os.path.normpath(requested_target))
    if target in {"/", "/mnt", "/var/mnt"} or not (target.startswith("/mnt/") or target.startswith("/var/mnt/")):
        raise RuntimeError("mount point must be below /mnt or /var/mnt")
    if os.path.exists(target):
        raise RuntimeError("mount point must be a new directory")
    parent = os.path.dirname(target)
    resolved_parent = os.path.realpath(parent)
    # On Bazzite /mnt is intentionally a link to /var/mnt, its writable
    # persistent location. Permit that standard layout while rejecting other
    # symlinked parents, which could make the chosen mount location misleading.
    bazzite_mnt = parent == "/mnt" and resolved_parent == "/var/mnt"
    if not os.path.isdir(parent) or (resolved_parent != parent and not bazzite_mnt):
        raise RuntimeError("mount point parent must be an existing non-symlinked directory")
    os.makedirs(target, mode=0o755)
    try:
        subprocess.run(["mount", "-t", device["fstype"], "UUID=" + device["uuid"], target], check=True)
        # Mounting an existing filesystem replaces the empty mount-point
        # directory with that filesystem's own root permissions. Give Ludus
        # players traversal only, so a private filesystem root cannot prevent
        # a later shared library below it from being reached. This exposes
        # neither directory listings nor file contents.
        subprocess.run(["setfacl", "-m", "g:ludus:--x", target], check=True)
        line = f"UUID={device['uuid']} {target} {device['fstype']} defaults,nofail,x-systemd.device-timeout=10 0 2\n"
        with open("/etc/fstab", encoding="utf-8") as source: content = source.read()
        if "UUID=" + device["uuid"] not in content:
            with tempfile.NamedTemporaryFile("w", dir="/etc", delete=False, encoding="utf-8") as temporary:
                temporary.write(content + ("\n" if content and not content.endswith("\n") else "") + "# Ludus managed shared-library disk\n" + line); name = temporary.name
            os.chmod(name, 0o644); os.replace(name, "/etc/fstab")
        subprocess.run(["systemctl", "daemon-reload"], check=True)
    except Exception:
        subprocess.run(["umount", target], check=False); os.rmdir(target); raise
    print(target)

if os.geteuid() != 0: raise SystemExit("ludus-disks: must run as root")
try:
    if len(sys.argv) == 2 and sys.argv[1] == "list": print(json.dumps(candidates()))
    elif len(sys.argv) in {3, 4} and sys.argv[1] == "mount": mount(sys.argv[2], sys.argv[3] if len(sys.argv) == 4 else "/mnt/games")
    else: raise RuntimeError("usage: ludus-disks list|mount <partition> [mount-point]")
except RuntimeError as error:
    raise SystemExit(f"ludus-disks: {error}")
