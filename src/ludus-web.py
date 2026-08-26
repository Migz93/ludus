#!/usr/bin/env python3
"""Small authenticated management UI; privileged actions go via ludus-backend."""
import base64, hashlib, hmac, json, socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONF = "/etc/ludus/webui.json"
SOCK = "/run/ludus/backend.sock"
MAX_BODY = 8192

def cfg():
    with open(CONF, encoding="utf-8") as file:
        return json.load(file)

def call(operation, argument=None):
    request = json.dumps({"operation": operation, "argument": argument}).encode()
    with socket.socket(socket.AF_UNIX) as client:
        client.connect(SOCK); client.sendall(request)
        chunks = []
        while data := client.recv(8192): chunks.append(data)
    return json.loads(b"".join(chunks))

PAGE = r'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Ludus</title><style>
body{font:16px system-ui,sans-serif;max-width:1050px;margin:2rem auto;padding:0 1rem;background:#12151b;color:#ecf0f5}nav{display:flex;gap:.5rem;flex-wrap:wrap}button,input{font:inherit;padding:.55rem}button{cursor:pointer;background:#2876d1;color:white;border:0;border-radius:.3rem}button.warn{background:#a35422}.card{background:#202631;border-radius:.5rem;padding:1rem;margin:1rem 0}pre{white-space:pre-wrap;background:#101318;padding:1rem;border-radius:.3rem;overflow:auto}.bad{color:#ff9c91}.ok{color:#9ee493}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:.55rem;border-bottom:1px solid #3a4250}form{display:flex;gap:.5rem;flex-wrap:wrap;margin:.75rem 0}input{flex:1;min-width:12rem}small{color:#b8c1ce}</style>
<h1>Ludus management</h1><nav><button onclick="show('dashboard')">Dashboard</button><button onclick="show('users')">Users</button><button onclick="show('libraries')">Libraries</button><button onclick="show('tools')">Tools</button><button onclick="show('health')">Health &amp; repair</button><button onclick="show('settings')">Settings</button></nav><main id="app"><p>Loading…</p></main><script>
const app=document.querySelector('#app'),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),js=s=>esc(JSON.stringify(String(s)));
async function api(url,body){let r=await fetch(url,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined}),d=await r.json().catch(()=>({ok:false,error:'Invalid server response'}));if(!r.ok)throw Error(d.error||'Request failed');return d}function result(d){return `<pre class="${d.ok?'ok':'bad'}">${esc(d.output||d.error||'Done.')}${d.error&&d.output?'\n'+esc(d.error):''}</pre>`}
async function show(p){app.innerHTML='<p>Loading…</p>';try{if(p==='dashboard'){let[s,u,l]=await Promise.all([api('/api/status'),api('/api/users'),api('/api/libraries')]);app.innerHTML=`<section class=card><h2>Dashboard</h2>${result(s)}<p><b>Players:</b> ${esc((u.output||'').trim()||'None')}<br><b>Libraries:</b> ${esc((l.output||'').trim()||'None')}</p></section>`}else if(p==='users'){let d=await api('/api/users'),rows=(d.output||'').trim().split('\n').filter(Boolean).map(x=>{let[a,n,...h]=x.split(/\s+/);return `<tr><td>${esc(n)}</td><td>${esc(a)}</td><td>${esc(h.join(' '))}</td><td><button class=warn onclick="mutate('/api/users/remove',{user:${js(n)}},'users')">Remove</button></td></tr>`}).join('');app.innerHTML=`<section class=card><h2>Users</h2><p>Removal never deletes a Linux account or home data.</p><form onsubmit="event.preventDefault();mutate('/api/users/enroll',{user:this.user.value},'users')"><input name=user required placeholder="Existing local username"><button>Enroll player</button></form><table><tr><th>User</th><th>Ludus status</th><th>Home</th><th></th></tr>${rows||'<tr><td colspan=4>No eligible local users found.</td></tr>'}</table></section>`}else if(p==='libraries'){let d=await api('/api/libraries'),rows=(d.output||'').trim().split('\n').filter(Boolean).map(x=>{let[,path]=x.split('\t');return `<tr><td><code>${esc(path)}</code></td><td><button class=warn onclick="mutate('/api/libraries/remove',{path:${js(path)}},'libraries')">Remove</button></td></tr>`}).join('');app.innerHTML=`<section class=card><h2>Shared libraries</h2><p>Removal only stops Ludus managing this path; it does not remove games.</p><form onsubmit="event.preventDefault();mutate('/api/libraries/add',{path:this.path.value},'libraries')"><input name=path required placeholder="/absolute/existing/directory"><button>Add library</button></form><table><tr><th>Path</th><th></th></tr>${rows||'<tr><td colspan=2>No libraries configured.</td></tr>'}</table></section>`}else if(p==='health'){let d=await api('/api/doctor');app.innerHTML=`<section class=card><h2>Health &amp; repair</h2>${result(d)}<button onclick="mutate('/api/repair',{},'health')">Repair safe library permissions</button><p><small>Repair refuses while Steam is active and never deletes game or home data.</small></p></section>`}else app.innerHTML=`<section class=card><h2>Rotate WebUI credentials</h2><form onsubmit="event.preventDefault();mutate('/api/credentials',{username:this.username.value,password:this.password.value},'credentials')"><input name=username required maxlength=64 placeholder="Administrator username"><input name=password required minlength=16 type=password placeholder="New password (16+ characters)"><button>Save credentials</button></form></section>`}catch(e){app.innerHTML=`<pre class=bad>${esc(e.message)}</pre>`}}
async function mutate(url,body,page){if(url.includes('/remove')&&!confirm('Continue? This does not delete game or home data.'))return;if(url==='/api/disks/mount'&&!confirm('Mount this existing filesystem and add it to /etc/fstab for boot persistence? Nothing will be formatted or erased.'))return;try{let d=await api(url,body);if(!d.ok){app.insertAdjacentHTML('afterbegin',result(d));return}await show(page)}catch(e){app.insertAdjacentHTML('afterbegin',`<pre class=bad>${esc(e.message)}</pre>`)}}
const oldShow=show;show=async p=>{if(p==='settings'){app.innerHTML='<p>Loading…</p>';try{let s=await api('/api/settings'),m=s.auth_mode||'none',local=m==='local'||m==='pam+local';app.innerHTML=`<section class=card><h2>Settings</h2><p>Choose how the Ludus WebUI authenticates administrators.</p><form onsubmit="event.preventDefault();mutate('/api/settings/auth-mode',{mode:this.mode.value},'settings')"><select name=mode><option value=none ${m==='none'?'selected':''}>None</option><option value=pam ${m==='pam'?'selected':''}>PAM (wheel users)</option><option value=local ${m==='local'?'selected':''}>Local Ludus account</option><option value=pam+local ${m==='pam+local'?'selected':''}>PAM + local account</option></select><button>Apply authentication mode</button></form>${local?`<form onsubmit="event.preventDefault();mutate('/api/credentials',{username:this.username.value,password:this.password.value},'settings')"><input name=username required maxlength=64 placeholder="Local administrator username"><input name=password required type=password placeholder="Local password"><button>Save local account</button></form>`:''}<p><small>PAM accepts only members of the Linux <code>wheel</code> group. Local account credentials are stored only as a password hash.</small></p></section>`}catch(e){app.innerHTML=`<pre class=bad>${esc(e.message)}</pre>`}return}if(p==='tools'){app.innerHTML='<p>Loading…</p>';try{let d=await api('/api/disks'),items=JSON.parse(d.output||'[]'),rows=items.map(x=>`<tr><td>${esc(x.path)}</td><td>${esc(x.fstype)}</td><td>${esc(x.label||x.uuid)}</td><td>${esc(x.mountpoint)}</td><td><button onclick="mutate('/api/disks/mount',{path:${js(x.path)}},'tools')">Mount for Ludus</button></td></tr>`).join('');app.innerHTML=`<section class=card><h2>Disk tools</h2><p>Only existing, unmounted ext4, XFS, or Btrfs partitions are shown. This does not format or erase anything. Mounting adds a persistent <code>/etc/fstab</code> entry.</p><table><tr><th>Partition</th><th>Filesystem</th><th>Name</th><th>Mount at</th><th></th></tr>${rows||'<tr><td colspan=5>No eligible unmounted partitions found.</td></tr>'}</table></section>`}catch(e){app.innerHTML=`<pre class=bad>${esc(e.message)}</pre>`}return}if(p!=='users'&&p!=='libraries')return oldShow(p);app.innerHTML='<p>Loading…</p>';try{if(p==='users'){let d=await api('/api/users'),rows=(d.output||'').trim().split('\n').filter(Boolean).map(x=>{let[a,n,h,state]=x.split('\t'),setup=state==='steam-ready'?'<span class=ok>Steam ready</span>':'<span class=bad>Steam has not been logged into yet. Shared libraries will be registered after their first Steam login.</span>';return `<tr><td>${esc(n)}</td><td>${esc(a)}</td><td>${esc(h)}</td><td>${setup}</td><td><button class=warn onclick="mutate('/api/users/remove',{user:${js(n)}},'users')">Remove</button></td></tr>`}).join('');app.innerHTML=`<section class=card><h2>Users</h2><p>Removal never deletes a Linux account or home data.</p><form onsubmit="event.preventDefault();mutate('/api/users/enroll',{user:this.user.value},'users')"><input name=user required placeholder="Existing local username"><button>Enroll player</button></form><table><tr><th>User</th><th>Ludus status</th><th>Home</th><th>Steam setup</th><th></th></tr>${rows||'<tr><td colspan=5>No eligible local users found.</td></tr>'}</table></section>`}else{let[d,c]=await Promise.all([api('/api/libraries'),api('/api/libraries/candidates')]),rows=(d.output||'').trim().split('\n').filter(Boolean).map(x=>{let[,path]=x.split('\t');return `<tr><td><code>${esc(path)}</code></td><td><button class=warn onclick="mutate('/api/libraries/remove',{path:${js(path)}},'libraries')">Remove</button></td></tr>`}).join(''),choices=(c.output||'').trim().split('\n').filter(Boolean).map(x=>{let[m,dev,fs,path]=x.split('\t');return `<option value="${esc(m)}">${esc(dev)} at ${esc(m)} (${esc(fs)}) → ${esc(path)}</option>`}).join('');app.innerHTML=`<section class=card><h2>Shared libraries</h2><p>Choose a mounted disk and Ludus creates a standard <code>steam-library</code> directory there. Shared games live there; Proton and shader files remain private in each player’s home.</p><form onsubmit="event.preventDefault();mutate('/api/libraries/add-default',{mount:this.mount.value},'libraries')"><select name=mount required>${choices||'<option value="">No suitable mounted filesystem found</option>'}</select><button>Add on selected disk</button></form><p>Advanced: use an existing directory.</p><form onsubmit="event.preventDefault();mutate('/api/libraries/add',{path:this.path.value},'libraries')"><input name=path required placeholder="/absolute/existing/directory"><button>Add exact path</button></form><table><tr><th>Path</th><th></th></tr>${rows||'<tr><td colspan=2>No libraries configured.</td></tr>'}</table></section>`}}catch(e){app.innerHTML=`<pre class=bad>${esc(e.message)}</pre>`}};show('dashboard');</script>'''

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
            try: return call("webui.pam_auth", {"username": username, "password": password}).get("ok", False)
            except (OSError, ValueError): return False
        return False
    def send(self, response, code=200, content_type="application/json"):
        body = response.encode() if isinstance(response, str) else json.dumps(response).encode()
        self.send_response(code); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store"); self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("X-Frame-Options", "DENY"); self.end_headers(); self.wfile.write(body)
    def require_auth(self):
        if self.authenticated(): return True
        self.send_response(401); self.send_header("WWW-Authenticate", 'Basic realm="Ludus"'); self.send_header("Cache-Control", "no-store"); self.end_headers(); return False
    def do_GET(self):
        if not self.require_auth(): return
        routes = {"/api/status":"status", "/api/doctor":"doctor", "/api/users":"users.list", "/api/libraries":"libraries.list", "/api/libraries/candidates":"libraries.candidates", "/api/libraries/check":"libraries.check", "/api/disks":"disks.list", "/api/settings":"webui.settings"}
        if self.path in ("/", "/index.html"): self.send(PAGE, content_type="text/html; charset=utf-8")
        elif self.path in routes: self.send(call(routes[self.path]))
        else: self.send({"ok":False,"error":"not found"}, 404)
    def do_POST(self):
        if not self.require_auth(): return
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json": self.send({"ok":False,"error":"Content-Type must be application/json"},415); return
        try:
            length = int(self.headers.get("Content-Length", "-1")); assert 0 < length <= MAX_BODY
            body = json.loads(self.rfile.read(length)); assert isinstance(body, dict)
        except (ValueError, json.JSONDecodeError, AssertionError): self.send({"ok":False,"error":"invalid JSON request"},400); return
        routes = {"/api/users/enroll":("users.enroll","user"),"/api/users/remove":("users.remove","user"),"/api/libraries/add":("libraries.add","path"),"/api/libraries/add-default":("libraries.add_default","mount"),"/api/libraries/remove":("libraries.remove","path"),"/api/disks/mount":("disks.mount","path"),"/api/repair":("repair",None),"/api/credentials":("webui.rotate",None),"/api/settings/auth-mode":("webui.set_auth_mode","mode")}
        route = routes.get(self.path)
        if not route: self.send({"ok":False,"error":"not found"},404); return
        operation, field = route; self.send(call(operation, body if field is None else body.get(field)))

def main():
    config = cfg(); ThreadingHTTPServer((config.get("listen", "0.0.0.0"), int(config.get("port", 9876))), Handler).serve_forever()

if __name__ == "__main__": main()
