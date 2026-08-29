#!/usr/bin/env python3
"""Small authenticated management UI; privileged actions go via ludus-backend."""
import base64, hashlib, hmac, ipaddress, json, os, secrets, socket, subprocess, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONF = "/etc/ludus/webui.json"
SOCK = "/run/ludus/backend.sock"
ASSETS = os.path.join(os.path.dirname(os.path.realpath(__file__)), "web")
MAX_BODY = 8192
MAX_HTTP_WORKERS = 16
HTTP_SOCKET_TIMEOUT = 15
BACKEND_OPERATION_TIMEOUT = 3610
PAM_RETRY_INTERVAL = 2
PAM_SUCCESS_TTL = 300
PAM_FAILURES = {}
PAM_SUCCESSES = {}
PAM_FAILURES_LOCK = threading.Lock()

def allow_pam_attempt(address):
    """Limit expensive root-side PAM checks from any one LAN peer."""
    now = time.monotonic()
    with PAM_FAILURES_LOCK:
        previous = PAM_FAILURES.get(address, 0)
        if now - previous < PAM_RETRY_INTERVAL:
            return False
        # Keep this small, bounded state even if a hostile LAN sends many
        # distinct source addresses.
        if len(PAM_FAILURES) >= 1024 and address not in PAM_FAILURES:
            PAM_FAILURES.pop(next(iter(PAM_FAILURES)))
        PAM_FAILURES[address] = now
        return True

def clear_pam_failure(address):
    with PAM_FAILURES_LOCK:
        PAM_FAILURES.pop(address, None)

def recent_pam_success(address, authorization):
    """Accept parallel browser requests after one PAM check has succeeded.

    Basic authentication attaches the same Authorization value to every API
    request.  The dashboard loads several APIs together, so treating a second
    valid request as a retry makes browsers such as Edge show another password
    prompt.  Keep only a short hash, bound to the client address, in memory.
    """
    fingerprint = hashlib.sha256(authorization.encode()).digest()
    now = time.monotonic()
    with PAM_FAILURES_LOCK:
        expiry = PAM_SUCCESSES.get((address, fingerprint), 0)
        if expiry > now:
            return True
        PAM_SUCCESSES.pop((address, fingerprint), None)
        return False

def remember_pam_success(address, authorization):
    fingerprint = hashlib.sha256(authorization.encode()).digest()
    with PAM_FAILURES_LOCK:
        PAM_FAILURES.pop(address, None)
        if len(PAM_SUCCESSES) >= 1024:
            PAM_SUCCESSES.pop(next(iter(PAM_SUCCESSES)))
        PAM_SUCCESSES[(address, fingerprint)] = time.monotonic() + PAM_SUCCESS_TTL

def cfg():
    with open(CONF, encoding="utf-8") as file:
        return json.load(file)

def call(operation, argument=None):
    request = json.dumps({"operation": operation, "argument": argument}).encode() + b"\n"
    with socket.socket(socket.AF_UNIX) as client:
        # Some safe administration operations (disk adoption and repair) are
        # intentionally allowed to take up to an hour in the root backend.
        # Keep the local client alive for their documented operation window.
        client.settimeout(BACKEND_OPERATION_TIMEOUT)
        client.connect(SOCK); client.sendall(request); client.shutdown(socket.SHUT_WR)
        chunks = []
        while data := client.recv(8192): chunks.append(data)
    return json.loads(b"".join(chunks))

def build_page():
    """Inline the local stylesheet and script into one self-contained document.

    The assets stay as ordinary files so the interface is easy to edit, but the
    server never maps a request path onto the filesystem: it reads three known
    names once at start-up and serves the result from memory.
    """
    def read(name):
        with open(os.path.join(ASSETS, name), encoding="utf-8") as file:
            return file.read()
    return read("index.html").replace("{{CSS}}", read("app.css")).replace("{{JS}}", read("app.js"))

PAGE = build_page()

class Handler(BaseHTTPRequestHandler):
    server_version = "LudusWeb/0.1"
    def log_message(self, _format, *_args): pass
    def authenticated(self):
        mode = cfg().get("auth_mode", "none")
        if mode == "none": return True
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Basic "): return False
        try:
            username, password = base64.b64decode(auth[6:], validate=True).decode().split(":", 1)
            config = cfg()
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, OSError): return False
        local = "username" in config and hmac.compare_digest(username, config["username"]) and hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), config["password_sha256"])
        if mode == "local" or mode == "password": return local
        if mode == "pam+local" and local: return True
        if mode in ("pam", "pam+local"):
            if recent_pam_success(self.client_address[0], auth): return True
            if not allow_pam_attempt(self.client_address[0]): return False
            try:
                result = call("webui.pam_auth", {"username": username, "password": password}).get("ok", False)
                if result: remember_pam_success(self.client_address[0], auth)
                return result
            except (OSError, ValueError): return False
        return False
    def send(self, response, code=200, content_type="application/json", extra=()):
        body = response.encode() if isinstance(response, str) else json.dumps(response).encode()
        self.send_response(code); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store"); self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("X-Frame-Options", "DENY"); self.send_header("Referrer-Policy", "no-referrer")
        for name, value in extra: self.send_header(name, value)
        self.end_headers(); self.wfile.write(body)
    def send_page(self):
        # The page carries no external resources, so everything except its own
        # nonce-tagged script and its inline styles can be refused outright.
        nonce = secrets.token_urlsafe(16)
        policy = ("default-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; "
                  f"img-src 'self' data:; style-src 'unsafe-inline'; script-src 'nonce-{nonce}'; connect-src 'self'")
        self.send(PAGE.replace("{{NONCE}}", nonce), content_type="text/html; charset=utf-8", extra=[("Content-Security-Policy", policy)])
    def require_auth(self):
        if self.authenticated(): return True
        self.send_response(401); self.send_header("WWW-Authenticate", 'Basic realm="Ludus"'); self.send_header("Cache-Control", "no-store"); self.end_headers(); return False
    def do_GET(self):
        if not self.require_auth(): return
        routes = {"/api/status":"status", "/api/doctor":"doctor", "/api/checks":"doctor.json", "/api/storage":"storage", "/api/users":"users.list", "/api/users/personal-libraries":"users.personal_libraries", "/api/libraries":"libraries.list", "/api/libraries/default":"libraries.default", "/api/libraries/candidates":"libraries.candidates", "/api/libraries/check":"libraries.check", "/api/disks":"disks.list", "/api/settings":"webui.settings", "/api/greeter-display":"greeter.display.settings", "/api/mqtt":"mqtt.settings"}
        if self.path in ("/", "/index.html"): self.send_page()
        elif self.path in routes: self.send(call(routes[self.path]))
        else: self.send({"ok":False,"error":"not found"}, 404)
    def do_POST(self):
        if not self.require_auth(): return
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json": self.send({"ok":False,"error":"Content-Type must be application/json"},415); return
        try:
            length = int(self.headers.get("Content-Length", "-1")); assert 0 < length <= MAX_BODY
            body = json.loads(self.rfile.read(length)); assert isinstance(body, dict)
        except (ValueError, json.JSONDecodeError, AssertionError): self.send({"ok":False,"error":"invalid JSON request"},400); return
        routes = {"/api/users/enroll":("users.enroll","user"),"/api/users/remove":("users.remove","user"),"/api/users/personal-libraries/remove":("users.remove_personal_library",None),"/api/libraries/add":("libraries.add","path"),"/api/libraries/add-default":("libraries.add_default","mount"),"/api/libraries/remove":("libraries.remove","path"),"/api/libraries/default":("libraries.set_default","path"),"/api/libraries/label":("libraries.label",None),"/api/disks/mount":("disks.mount","path"),"/api/repair":("repair",None),"/api/credentials":("webui.rotate",None),"/api/settings/auth-mode":("webui.set_auth_mode","mode"),"/api/settings/vscode-forwarding":("webui.set_vscode_forwarding","enabled"),"/api/settings/vscode-forwarding/repair":("webui.repair_vscode_forwarding",None),"/api/greeter-display":("greeter.display.save",None),"/api/mqtt":("mqtt.save",None),"/api/mqtt/test":("mqtt.test",None)}
        route = routes.get(self.path)
        if not route: self.send({"ok":False,"error":"not found"},404); return
        operation, field = route; self.send(call(operation, body if operation in {"disks.mount", "libraries.label"} or field is None else body.get(field)))

def main():
    config = cfg(); LanOnlyServer((config.get("listen", "0.0.0.0"), int(config.get("port", 9304))), Handler).serve_forever()

def private_lans():
    try:
        addresses = json.loads(subprocess.check_output(["ip", "-j", "-4", "addr", "show", "scope", "global"], text=True))
        return [ipaddress.ip_network(f"{entry['local']}/{entry['prefixlen']}", strict=False) for interface in addresses for entry in interface.get("addr_info", []) if entry.get("family") == "inet" and ipaddress.ip_address(entry["local"]).is_private]
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError): return []

class LanOnlyServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = MAX_HTTP_WORKERS
    def __init__(self, address, handler):
        self.private_lans = private_lans()
        self.workers = threading.BoundedSemaphore(MAX_HTTP_WORKERS)
        super().__init__(address, handler)
    def get_request(self):
        request, address = super().get_request()
        request.settimeout(HTTP_SOCKET_TIMEOUT)
        return request, address
    def process_request(self, request, client_address):
        if not self.workers.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.workers.release()
            raise
    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.workers.release()
    def verify_request(self, request, client_address):
        peer = ipaddress.ip_address(client_address[0])
        return peer.is_loopback or any(peer in network for network in self.private_lans)

if __name__ == "__main__": main()
