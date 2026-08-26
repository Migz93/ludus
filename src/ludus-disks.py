#!/usr/bin/env python3
"""Safely adopt existing, unmounted Linux filesystems for Ludus. GPL-3.0-or-later."""
import json, os, re, subprocess, sys, tempfile

ALLOWED = {"btrfs", "ext4", "xfs"}

def candidates():
    data = json.loads(subprocess.check_output(["lsblk", "-J", "-o", "PATH,TYPE,FSTYPE,UUID,LABEL,MOUNTPOINTS"], text=True))
    result = []
    for device in data["blockdevices"]:
        if device["type"] != "part" or device["fstype"] not in ALLOWED or not device["uuid"] or any(device["mountpoints"]): continue
        name = device["label"] if device["label"] and re.fullmatch(r"[A-Za-z0-9_-]{1,48}", device["label"]) else "disk-" + device["uuid"][:8]
        result.append({"path":device["path"], "fstype":device["fstype"], "uuid":device["uuid"], "label":device["label"] or "", "mountpoint":"/mnt/" + name})
    return result

def mount(path):
    device = next((item for item in candidates() if item["path"] == path), None)
    if not device: raise RuntimeError("not an eligible unmounted partition")
    target = device["mountpoint"]
    os.makedirs(target, mode=0o755)
    try:
        subprocess.run(["mount", "-t", device["fstype"], "UUID=" + device["uuid"], target], check=True)
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
if len(sys.argv) == 2 and sys.argv[1] == "list": print(json.dumps(candidates()))
elif len(sys.argv) == 3 and sys.argv[1] == "mount": mount(sys.argv[2])
else: raise SystemExit("usage: ludus-disks list|mount <partition>")
