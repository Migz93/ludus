#!/usr/bin/env python3
"""Unprivileged client for the Ludus mount service. SPDX-License-Identifier: GPL-3.0-or-later"""
import json, socket, sys
if len(sys.argv) != 2 or sys.argv[1] not in {"mount", "unmount"}:
    sys.exit("usage: ludus-mountctl mount|unmount")
client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
client.connect("/run/ludus-mount/mount.sock")
client.sendall(json.dumps({"action": sys.argv[1]}).encode("utf-8"))
client.shutdown(socket.SHUT_WR)
reply = json.loads(client.recv(4096).decode("utf-8"))
if not reply.get("ok"): sys.exit(f"ludus mount: {reply.get('error', 'request failed')}")
