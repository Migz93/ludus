#!/usr/bin/env python3
"""Home Assistant MQTT integration for Ludus. GPL-3.0-or-later.

The broker is intentionally optional.  When not configured this service stays
local, writes an explicit disabled health record, and opens no network socket.
"""
import argparse
import json
import os
import pwd
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

CONFIG = Path("/etc/ludus/mqtt.json")
STATUS = Path("/run/ludus/mqtt-status.json")
REQUEST = Path("/run/ludus/mqtt-login.json")
ACTIVE_USER = Path("/run/ludus-mount/active-user")
MOUNT_SOCKET = "/run/ludus-mount/mount.sock"
GROUP = "ludus"
INACTIVE = "Inactive"


def load_config():
    try:
        with CONFIG.open(encoding="utf-8") as source:
            value = json.load(source)
    except (OSError, ValueError):
        value = {}
    return value if isinstance(value, dict) else {}


def enrolled_users():
    try:
        import grp
        group = grp.getgrnam(GROUP)
    except KeyError:
        return []
    names = set(group.gr_mem)
    for entry in pwd.getpwall():
        if entry.pw_gid == group.gr_gid:
            names.add(entry.pw_name)
    result = []
    for name in sorted(names):
        try:
            if pwd.getpwnam(name).pw_uid >= 1000:
                result.append(name)
        except KeyError:
            # A stale supplementary-group entry must not make the MQTT
            # service fail; Ludusctl doctor reports that enrolment separately.
            continue
    return result


def greeter_running():
    # Linux limits the short process name to 15 characters, while Plasma
    # Login's greeter is longer.  Match its full command line instead; `-x`
    # silently never finds it and leaves remote starts stuck at booting.
    return subprocess.run(["pgrep", "-f", "plasma-login-greeter"], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, check=False).returncode == 0


def active_user():
    try:
        value = ACTIVE_USER.read_text(encoding="utf-8").strip()
        return value if value in enrolled_users() else ""
    except OSError:
        return ""


def machine_id():
    try:
        return Path("/etc/machine-id").read_text(encoding="utf-8").strip()
    except OSError:
        return socket.gethostname()


def atomic_json(path, value, mode=0o644):
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temp:
        json.dump(value, temp, separators=(",", ":")); temp.write("\n"); name = temp.name
    os.chmod(name, mode)
    os.replace(name, path)


def unmount_active_session():
    """Ask the root-only mount daemon to clear the recorded active session."""
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(10)
        client.connect(MOUNT_SOCKET)
        client.sendall(b'{"action":"unmount-active"}\n')
        client.shutdown(socket.SHUT_WR)
        reply = json.loads(client.recv(4096).decode("utf-8"))
        client.close()
        return bool(reply.get("ok"))
    except (OSError, ValueError, json.JSONDecodeError):
        return False


class LudusMqtt:
    def __init__(self, config):
        self.config = config
        self.prefix = str(config.get("topic_prefix") or "ludus/" + machine_id()).strip("/")
        self.connected = False
        self.last_error = ""
        self.last_event = "MQTT is disabled"
        self.pending = ""
        self.dispatched_at = 0.0
        self.client = None

    def topic(self, suffix):
        return self.prefix + "/" + suffix

    def status(self):
        current = active_user()
        if current:
            lifecycle = "Big Picture Ready" if subprocess.run(
                ["pgrep", "-u", current, "-x", "steam"], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, check=False).returncode == 0 else "Starting Session"
        elif greeter_running():
            lifecycle = "Login Requested" if self.pending and self.dispatched_at else "Ready to Sign In"
        else:
            lifecycle = "Starting Up"
        return {"enabled": bool(self.config.get("enabled", False)), "connected": self.connected,
                "broker": str(self.config.get("host", "")), "topic_prefix": self.prefix,
                "active_player": current or INACTIVE, "session_active": bool(current),
                "state": lifecycle, "pending_player": self.pending or INACTIVE,
                "last_error": self.last_error, "last_event": self.last_event,
                "updated_at": int(time.time())}

    def write_status(self):
        atomic_json(STATUS, self.status())

    def publish(self, topic, payload, retain=True):
        if self.client and self.connected:
            self.client.publish(self.topic(topic), payload, qos=1, retain=retain)

    def publish_state(self):
        state = self.status()
        self.publish("state/status", json.dumps(state, separators=(",", ":")))
        self.publish("state/active", "ON" if state["session_active"] else "OFF")
        self.publish("state/player", state["active_player"])
        self.publish("state/lifecycle", state["state"])
        self.publish("state/requested_player", state["pending_player"])
        self.publish("state/last_error", state["last_error"] or "None")
        self.publish("state/availability", "online" if self.connected else "offline")
        self.write_status()

    def clear_start_command(self):
        # The player select deliberately publishes retained commands so a
        # request survives a powered-off PC.  Once handled or rejected, erase
        # that retained user value; otherwise it would be replayed after a
        # later reboot and could unexpectedly start another session.
        self.publish("command/start_player", "", retain=True)

    def clear_lifecycle_command(self, command):
        """Erase a retained destructive command after seeing it."""
        self.publish("command/" + command, "", retain=True)

    def end_session(self, user):
        """Terminate the user and confirm Ludus's private mounts are cleared."""
        subprocess.run(["loginctl", "terminate-user", user], check=False, timeout=30)
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if not active_user():
                return True
            # A forced logind termination can skip ludus-steam's EXIT trap.
            # The mount daemon verifies and performs the same unmount work.
            if unmount_active_session() and not active_user():
                return True
            time.sleep(0.5)
        return not active_user()

    def discovery(self):
        device = {"identifiers": ["ludus_" + machine_id()], "name": "Ludus",
                  "manufacturer": "Ludus", "model": "Bazzite lounge console"}
        availability = {"topic": self.topic("state/availability"), "payload_available": "online",
                        "payload_not_available": "offline"}
        base = "homeassistant"
        node = "ludus_" + machine_id()
        def config(component, object_id, payload, use_availability=True):
            payload.update({"unique_id": node + "_" + object_id, "device": device})
            # A retained player selection must be possible while the lounge
            # PC is off.  Do not attach broker availability to that one
            # command entity; every status/control entity still correctly
            # becomes unavailable whenever Ludus is offline.
            if use_availability:
                payload["availability"] = [availability]
            self.client.publish(f"{base}/{component}/{node}/{object_id}/config",
                                json.dumps(payload, separators=(",", ":")), qos=1, retain=True)
        config("select", "start_player", {"name": "Start player", "command_topic": self.topic("command/start_player"),
               "state_topic": self.topic("state/requested_player"), "options": [INACTIVE, *enrolled_users()], "retain": True},
               use_availability=False)
        config("binary_sensor", "session_active", {"name": "Session active", "state_topic": self.topic("state/active"),
               "payload_on": "ON", "payload_off": "OFF", "device_class": "running"})
        config("sensor", "active_player", {"name": "Active player", "state_topic": self.topic("state/player")})
        config("sensor", "state", {"name": "State", "state_topic": self.topic("state/lifecycle"), "icon": "mdi:gamepad-variant"})
        config("sensor", "last_error", {"name": "Last error", "state_topic": self.topic("state/last_error"), "icon": "mdi:alert-circle-outline"})
        for command, title, icon in (("sign_out", "Sign out", "mdi:logout"), ("reboot", "Restart", "mdi:restart"), ("shutdown", "Shut down", "mdi:power")):
            config("button", command, {"name": title, "command_topic": self.topic("command/" + command),
                   "payload_press": "PRESS", "icon": icon})

    def set_pending(self, user):
        if user == INACTIVE:
            self.pending = ""
            self.dispatched_at = 0.0
            REQUEST.unlink(missing_ok=True)
            self.last_event = "Pending remote start cleared"
            self.publish_state()
            return
        if user not in enrolled_users():
            self.last_error = "Requested player is not enrolled in Ludus"
            self.last_event = "Remote start rejected"
            self.clear_start_command()
            self.publish_state()
            return
        if active_user():
            self.last_error = "A Ludus player session is already active"
            self.last_event = "Remote start rejected"
            self.clear_start_command()
            self.publish_state()
            return
        self.pending = user
        self.dispatched_at = 0.0
        self.last_error = ""
        self.last_event = f"Remote start requested for {user}"
        self.publish_state()

    def command(self, topic, payload, retained=False):
        suffix = topic.rsplit("/", 1)[-1]
        value = payload.decode("utf-8", "replace").strip()
        if suffix == "start_player":
            self.set_pending(value or INACTIVE)
        elif suffix == "sign_out":
            if retained or value != "PRESS":
                self.last_error, self.last_event = "Sign out requires a non-retained PRESS command", "Remote command rejected"
                if retained: self.clear_lifecycle_command(suffix)
                self.publish_state()
                return
            user = active_user()
            if not user:
                self.last_error, self.last_event = "No Ludus session is active", "Sign out rejected"
            elif self.end_session(user):
                self.last_error, self.last_event = "", f"Signed out {user} and cleared private session data"
            else:
                self.last_error, self.last_event = "Could not confirm private session cleanup", "Sign out needs attention"
            self.clear_lifecycle_command(suffix)
            self.publish_state()
        elif suffix in {"reboot", "shutdown"}:
            if retained or value != "PRESS":
                self.last_error, self.last_event = f"{suffix.capitalize()} requires a non-retained PRESS command", "Remote command rejected"
                if retained: self.clear_lifecycle_command(suffix)
                self.publish_state()
                return
            user = active_user()
            if user and not self.end_session(user):
                self.last_error = "Could not confirm private session cleanup; power action cancelled"
                self.last_event = "Remote power action needs attention"
                self.publish_state()
                return
            self.last_event, self.last_error = ("Remote restart requested", "") if suffix == "reboot" else ("Remote shutdown requested", "")
            self.clear_lifecycle_command(suffix)
            self.publish_state()
            subprocess.Popen(["systemctl", "reboot" if suffix == "reboot" else "poweroff"])

    def on_connect(self, _client, _userdata, _flags, reason_code, _properties=None):
        if int(reason_code) != 0:
            self.last_error = f"MQTT broker refused connection ({reason_code})"
            self.write_status(); return
        self.connected = True
        self.last_error = ""; self.last_event = "Connected to MQTT broker"
        self.client.subscribe(self.topic("command/#"), qos=1)
        self.discovery(); self.publish_state()

    def on_disconnect(self, _client, _userdata, *args):
        # paho-mqtt 1.x calls this (client, userdata, rc), whereas 2.x adds
        # flags and properties.  Supporting both keeps the Bazzite package
        # version an implementation detail rather than a compatibility trap.
        reason_code = args[-2] if len(args) >= 2 else (args[0] if args else 0)
        self.connected = False
        if reason_code:
            self.last_error = f"MQTT disconnected ({reason_code})"
        self.write_status()

    def run(self):
        if not self.config.get("enabled", False):
            self.write_status()
            while True: time.sleep(60)
        if mqtt is None:
            self.last_error = "python3-paho-mqtt is not installed"; self.write_status()
            while True: time.sleep(60)
        host = str(self.config.get("host", "")).strip()
        try: port = int(self.config.get("port", 1883))
        except (TypeError, ValueError): port = 1883
        if not host or not 1 <= port <= 65535:
            self.last_error = "MQTT broker host or port is invalid"; self.write_status()
            while True: time.sleep(60)
        self.client = mqtt.Client(client_id="ludus-" + machine_id(), protocol=mqtt.MQTTv311)
        username = self.config.get("username", "")
        if username: self.client.username_pw_set(str(username), str(self.config.get("password", "")))
        if self.config.get("tls", False): self.client.tls_set(ca_certs=self.config.get("ca_cert") or None)
        self.client.will_set(self.topic("state/availability"), "offline", qos=1, retain=True)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = lambda _client, _userdata, message: self.command(message.topic, message.payload, message.retain)
        self.client.connect_async(host, port, keepalive=30)
        self.client.loop_start()
        while True:
            if self.pending and not active_user() and greeter_running() and not self.dispatched_at:
                atomic_json(REQUEST, {"user": self.pending, "requested_at": int(time.time())})
                self.dispatched_at = time.monotonic()
                self.last_event = f"Login handed to the Ludus greeter for {self.pending}"
                self.publish_state()
            # Plasma Login exits as it hands a successful login to the session.
            if self.pending and self.dispatched_at and not greeter_running():
                REQUEST.unlink(missing_ok=True)
                self.last_event = f"Ludus login started for {self.pending}"
                self.clear_start_command()
                self.pending = ""; self.dispatched_at = 0.0
                self.publish_state()
            elif self.pending and self.dispatched_at and time.monotonic() - self.dispatched_at > 120:
                REQUEST.unlink(missing_ok=True)
                self.last_error = "The Ludus greeter did not complete the remote login within two minutes"
                self.last_event = "Remote start timed out"
                self.clear_start_command()
                self.pending = ""; self.dispatched_at = 0.0
                self.publish_state()
            else:
                self.write_status()
            time.sleep(1)


def test_connection(config):
    if mqtt is None: raise RuntimeError("python3-paho-mqtt is not installed")
    host = str(config.get("host", "")).strip(); port = int(config.get("port", 1883))
    if not host or not 1 <= port <= 65535: raise RuntimeError("MQTT broker host or port is invalid")
    client = mqtt.Client(client_id="ludus-test-" + machine_id(), protocol=mqtt.MQTTv311)
    if config.get("username"): client.username_pw_set(str(config["username"]), str(config.get("password", "")))
    if config.get("tls", False): client.tls_set(ca_certs=config.get("ca_cert") or None)
    result = {"ok": False}; event = threading.Event()
    def connected(_client, _userdata, _flags, reason_code, _properties=None):
        result["ok"] = int(reason_code) == 0; result["reason"] = str(reason_code); event.set()
    client.on_connect = connected; client.connect_async(host, port, keepalive=10); client.loop_start(); event.wait(12); client.loop_stop()
    if not result["ok"]: raise RuntimeError("MQTT connection was not accepted (" + result.get("reason", "timeout") + ")")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--test", action="store_true"); args = parser.parse_args()
    config = load_config()
    if args.test:
        test_connection(config); print("MQTT broker connection succeeded")
    else:
        LudusMqtt(config).run()
