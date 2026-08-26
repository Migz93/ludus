#!/usr/bin/env python3
"""Report capacity for each Ludus shared library. Read-only. GPL-3.0-or-later.

This makes no change to the system.  It reads the configured library list and
reports the backing device and free space for each one, so the WebUI can show
disk usage without parsing human-readable command output.
"""
import json
import os
import subprocess
import sys

LIBRARIES = "/etc/ludus/libraries.conf"


def library_paths():
    try:
        with open(LIBRARIES, encoding="utf-8") as file:
            return [line.strip() for line in file if line.strip() and not line.startswith("#")]
    except FileNotFoundError:
        return []


def backing_mount(path):
    """The device and filesystem type the given path lives on."""
    try:
        output = subprocess.check_output(
            ["findmnt", "-rn", "-o", "SOURCE,FSTYPE", "-T", path],
            text=True, timeout=15, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return "", ""
    fields = output.split("\n")[0].split()
    if len(fields) < 2:
        return "", ""
    return fields[0], fields[-1]


def entry(path):
    device, fstype = backing_mount(path)
    record = {"path": path, "device": device, "fstype": fstype, "total": None, "free": None}
    try:
        stats = os.statvfs(path)
    except OSError:
        return record
    # f_bavail is what is actually usable, excluding the reserved blocks.
    record["total"] = stats.f_blocks * stats.f_frsize
    record["free"] = stats.f_bavail * stats.f_frsize
    return record


if len(sys.argv) != 1:
    raise SystemExit("usage: ludus-storage")
print(json.dumps([entry(path) for path in library_paths()]))
