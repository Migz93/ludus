#!/usr/bin/env python3
"""Small authenticated management UI; privileged actions go via ludus-backend."""
import hashlib, hmac, ipaddress, json, os, re, secrets, socket, stat, subprocess, threading, time
from http.cookies import SimpleCookie, CookieError
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONF = "/etc/ludus/webui.json"
SOCK = "/run/ludus/backend.sock"
ASSETS = os.path.join(os.path.dirname(os.path.realpath(__file__)), "web")
ARTWORK_CACHE = "/var/cache/ludus/game-art"
MAX_ARTWORK_BYTES = 5 * 1024 * 1024
MAX_BODY = 8192
MAX_HTTP_WORKERS = 16
HTTP_SOCKET_TIMEOUT = 15
BACKEND_OPERATION_TIMEOUT = 3610
PAM_RETRY_INTERVAL = 2
SESSION_TTL = 15 * 60
SESSION_COOKIE = "ludus_session"
SESSIONS = {}
SESSIONS_LOCK = threading.Lock()
PAM_FAILURES = {}
PAM_FAILURES_LOCK = threading.Lock()
PAM_IN_FLIGHT = {}

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

def pam_check(address, authorization, username, password, reserved=False):
    """Run one root-side PAM check per credential; parallel requests share it.

    Simultaneous form submissions should not trigger duplicate PAM checks.
    """
    key = (address, hashlib.sha256(authorization.encode()).digest())
    with PAM_FAILURES_LOCK:
        pending = PAM_IN_FLIGHT.get(key)
        if pending is None:
            pending = PAM_IN_FLIGHT[key] = {"done": threading.Event(), "ok": False}
            owner = True
        else:
            owner = False
    if not owner:
        pending["done"].wait(20)
        return pending["ok"]
    try:
        if not reserved and not allow_pam_attempt(address): return False
        try:
            pending["ok"] = call("webui.pam_auth", {"username": username, "password": password}).get("ok", False)
        except (OSError, ValueError):
            pending["ok"] = False
        if pending["ok"]: clear_pam_failure(address)
        return pending["ok"]
    finally:
        with PAM_FAILURES_LOCK:
            PAM_IN_FLIGHT.pop(key, None)
        pending["done"].set()

def auth_revision(config):
    """Invalidate sessions when credentials or the selected policy change."""
    return hashlib.sha256(json.dumps({key: config.get(key) for key in
        ("auth_mode", "username", "password_sha256")}, sort_keys=True).encode()).digest()

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
    def session_token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            return cookie[SESSION_COOKIE].value if SESSION_COOKIE in cookie else ""
        except CookieError:
            return ""
    def session(self, config):
        token = self.session_token()
        now = time.monotonic()
        with SESSIONS_LOCK:
            session = SESSIONS.get(token)
            if session and (session["expires"] <= now or session["revision"] != auth_revision(config)):
                SESSIONS.pop(token, None)
                session = None
            if session:
                session["expires"] = now + SESSION_TTL
            return session
    def authenticated(self):
        config = cfg()
        return config.get("auth_mode", "none") == "none" or self.session(config) is not None
    def same_origin(self):
        # Never trust forwarding headers supplied by a LAN peer. The proxy must
        # preserve Host. JSON-only POSTs and no CORS also block cross-site forms.
        if self.headers.get("Sec-Fetch-Site") == "cross-site": return False
        origin = self.headers.get("Origin")
        if origin is None: return True
        try:
            parsed = urlsplit(origin)
        except ValueError:
            return False
        return parsed.scheme in ("http", "https") and parsed.netloc == self.headers.get("Host") and not parsed.path and not parsed.query and not parsed.fragment
    def session_cookie(self, token):
        # HTTPS reverse proxies preserve the browser's Origin on POST requests.
        secure = self.headers.get("Origin", "").startswith("https://")
        return f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict" + ("; Secure" if secure else "") + ("; Max-Age=0" if not token else "")
    def login(self, body):
        username, password = body.get("username"), body.get("password")
        if not isinstance(username, str) or not isinstance(password, str) or not username or not password:
            self.send({"ok": False, "error": "Enter your username and password."}, 400); return
        config = cfg()
        mode = config.get("auth_mode", "none")
        local = False
        if mode in ("local", "password", "pam+local"):
            if not allow_pam_attempt(self.client_address[0]):
                self.send({"ok": False, "error": "Wait a moment before trying again."}, 429); return
            local = hmac.compare_digest(username.encode(), config.get("username", "").encode()) and hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), config.get("password_sha256", ""))
        valid = local or mode == "none"
        if not valid and mode in ("pam", "pam+local"):
            # pam_check owns the retry limit for PAM-only mode; the combined
            # mode already reserved this attempt above.
            fingerprint = json.dumps([username, password])
            valid = pam_check(self.client_address[0], fingerprint, username, password, reserved=mode == "pam+local")
        if not valid:
            self.send({"ok": False, "error": "Username or password was not accepted."}, 401); return
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with SESSIONS_LOCK:
            now = time.monotonic()
            for old in [key for key, value in SESSIONS.items() if value["expires"] <= now]: SESSIONS.pop(old)
            SESSIONS.pop(self.session_token(), None)
            if len(SESSIONS) >= 1024: SESSIONS.pop(next(iter(SESSIONS)))
            SESSIONS[token] = {"csrf": csrf, "revision": auth_revision(config), "expires": now + SESSION_TTL}
        clear_pam_failure(self.client_address[0])
        self.send({"ok": True, "csrf": csrf, "required": mode != "none"}, extra=[("Set-Cookie", self.session_cookie(token))])
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
    def send_poster(self, appid):
        for layout in ("portrait", "wide"):
            for suffix, content_type in (("jpg", "image/jpeg"), ("png", "image/png")):
                path = os.path.join(ARTWORK_CACHE, f"{appid}.{layout}.{suffix}")
                try:
                    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                    with os.fdopen(descriptor, "rb") as source:
                        details = os.fstat(source.fileno())
                        if not stat.S_ISREG(details.st_mode) or details.st_size > MAX_ARTWORK_BYTES:
                            continue
                        body = source.read(MAX_ARTWORK_BYTES + 1)
                    if len(body) > MAX_ARTWORK_BYTES:
                        continue
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "private, max-age=86400")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("X-Frame-Options", "DENY")
                    self.send_header("Referrer-Policy", "no-referrer")
                    self.end_headers(); self.wfile.write(body)
                    return
                except OSError:
                    continue
        self.send({"ok":False,"error":"poster not found"}, 404)
    def require_auth(self):
        if self.authenticated(): return True
        self.send({"ok": False, "error": "Sign in to continue."}, 401); return False
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_page(); return
        if not self.require_auth(): return
        if self.path == "/api/auth/session":
            config = cfg()
            session = self.session(config)
            self.send({"ok": True, "required": config.get("auth_mode", "none") != "none", "csrf": session["csrf"] if session else ""}); return
        routes = {"/api/status":"status", "/api/doctor":"doctor", "/api/checks":"doctor.json", "/api/storage":"storage", "/api/users":"users.list", "/api/users/personal-libraries":"users.personal_libraries", "/api/libraries":"libraries.list", "/api/libraries/default":"libraries.default", "/api/libraries/candidates":"libraries.candidates", "/api/libraries/check":"libraries.check", "/api/games":"games.list", "/api/games/proton-dpi":"proton_dpi.settings", "/api/games/launch-options":"launch_options.settings", "/api/disks":"disks.list", "/api/settings":"webui.settings", "/api/greeter-display":"greeter.display.settings", "/api/mqtt":"mqtt.settings"}
        poster = re.fullmatch(r"/api/games/([0-9]+)/poster", self.path)
        if self.path in routes: self.send(call(routes[self.path]))
        elif poster: self.send_poster(poster.group(1))
        else: self.send({"ok":False,"error":"not found"}, 404)
    def do_POST(self):
        if not self.same_origin():
            self.send({"ok": False, "error": "Cross-origin request refused."}, 403); return
        if self.path != "/api/auth/login":
            if not self.require_auth(): return
            config = cfg()
            session = self.session(config)
            if config.get("auth_mode", "none") != "none" and (not session or not hmac.compare_digest(self.headers.get("X-Ludus-CSRF", "").encode(), session["csrf"].encode())):
                self.send({"ok": False, "error": "Reload the page before trying again."}, 403); return
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json": self.send({"ok":False,"error":"Content-Type must be application/json"},415); return
        try:
            length = int(self.headers.get("Content-Length", "-1")); assert 0 < length <= MAX_BODY
            body = json.loads(self.rfile.read(length)); assert isinstance(body, dict)
        except (ValueError, json.JSONDecodeError, AssertionError): self.send({"ok":False,"error":"invalid JSON request"},400); return
        if self.path == "/api/auth/login":
            self.login(body); return
        if self.path == "/api/auth/logout":
            with SESSIONS_LOCK: SESSIONS.pop(self.session_token(), None)
            self.send({"ok": True}, extra=[("Set-Cookie", self.session_cookie(""))]); return
        routes = {"/api/users/enroll":("users.enroll","user"),"/api/users/remove":("users.remove","user"),"/api/users/personal-libraries/remove":("users.remove_personal_library",None),"/api/libraries/add":("libraries.add","path"),"/api/libraries/add-default":("libraries.add_default","mount"),"/api/libraries/remove":("libraries.remove","path"),"/api/libraries/default":("libraries.set_default","path"),"/api/libraries/label":("libraries.label",None),"/api/games/proton-dpi":("proton_dpi.save",None),"/api/games/launch-options":("launch_options.save",None),"/api/disks/mount":("disks.mount","path"),"/api/repair":("repair",None),"/api/credentials":("webui.rotate",None),"/api/settings/auth-mode":("webui.set_auth_mode","mode"),"/api/settings/vscode-forwarding":("webui.set_vscode_forwarding","enabled"),"/api/settings/vscode-forwarding/repair":("webui.repair_vscode_forwarding",None),"/api/greeter-display":("greeter.display.save",None),"/api/mqtt":("mqtt.save",None),"/api/mqtt/test":("mqtt.test",None)}
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
