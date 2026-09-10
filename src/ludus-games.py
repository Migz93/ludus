#!/usr/bin/env python3
"""Read installed Steam app manifests from Ludus shared libraries."""
import concurrent.futures
import grp
import json
import os
import pwd
import re
import stat
import sys
import tempfile
import time
import urllib.parse
import urllib.request

LIBRARIES = "/etc/ludus/libraries.conf"
MANIFEST = re.compile(r"appmanifest_([0-9]+)\.acf\Z")
TOKENS = re.compile(r'"((?:\\.|[^"\\])*)"|([{}])')
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_ARTWORK_BYTES = 5 * 1024 * 1024
ARTWORK_CACHE = "/var/cache/ludus/game-art"
ARTWORK_RETRY_SECONDS = 24 * 60 * 60
CDN_HOSTS = {"shared.cloudflare.steamstatic.com", "shared.akamai.steamstatic.com",
             "shared.steamstatic.com"}


def parse_keyvalues(text):
    """Parse the quoted subset of Valve KeyValues used by app manifests."""
    matches = list(TOKENS.finditer(text))
    tokens = [match.group(1) if match.group(1) is not None else match.group(2)
              for match in matches]
    # Reject non-whitespace outside recognised tokens instead of silently
    # accepting a partly parsed or syntactically damaged manifest.
    cursor = 0
    for match in matches:
        if text[cursor:match.start()].strip():
            raise ValueError("unrecognised KeyValues content")
        cursor = match.end()
    if text[cursor:].strip():
        raise ValueError("unrecognised KeyValues content")

    def unquote(value):
        return value.replace(r'\"', '"').replace(r'\\', '\\')

    def block(index):
        output = {}
        while index < len(tokens) and tokens[index] != "}":
            key = unquote(tokens[index])
            index += 1
            if index >= len(tokens):
                raise ValueError("incomplete KeyValues entry")
            if tokens[index] == "{":
                value, index = block(index + 1)
            elif tokens[index] == "}":
                raise ValueError("missing KeyValues value")
            else:
                value = unquote(tokens[index])
                index += 1
            if key in output:
                raise ValueError(f"duplicate KeyValues key: {key}")
            output[key] = value
        if index >= len(tokens):
            raise ValueError("unclosed KeyValues block")
        return output, index + 1

    if len(tokens) < 2 or tokens[1] != "{":
        raise ValueError("unrecognised KeyValues document")
    root, end = block(2)
    if end != len(tokens):
        raise ValueError("trailing KeyValues data")
    return {unquote(tokens[0]): root}


def configured_libraries(path=LIBRARIES):
    try:
        with open(path, encoding="utf-8") as source:
            return [line.strip() for line in source
                    if line.strip() and not line.lstrip().startswith("#")]
    except FileNotFoundError:
        return []


def error_row(library, path, filename_appid, message):
    return {"appid": filename_appid, "name": "", "library": library,
            "manifest": path, "install_dir": "", "installed_bytes": None,
            "last_updated": None, "status": "error", "message": message}


def manifest_row(library, entry):
    path = os.path.join(library, "steamapps", entry.name)
    match = MANIFEST.fullmatch(entry.name)
    filename_appid = match.group(1)
    try:
        details = entry.stat(follow_symlinks=False)
        if not stat.S_ISREG(details.st_mode):
            raise ValueError("manifest is not a regular file")
        if details.st_size > MAX_MANIFEST_BYTES:
            raise ValueError("manifest is larger than 2 MiB")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, encoding="utf-8", errors="strict") as source:
            opened = os.fstat(source.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise ValueError("manifest is not a regular file")
            document = parse_keyvalues(source.read(MAX_MANIFEST_BYTES + 1))
        app = document.get("AppState")
        if not isinstance(app, dict):
            raise ValueError("missing AppState block")
        appid = app.get("appid")
        if not isinstance(appid, str) or not appid.isdigit():
            raise ValueError("missing numeric appid")
        if appid != filename_appid:
            raise ValueError(f"manifest appid {appid} does not match filename appid {filename_appid}")
        name = app.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("missing game name")
        installed_bytes = app.get("SizeOnDisk")
        if not isinstance(installed_bytes, str) or not installed_bytes.isdigit():
            installed_bytes = None
        else:
            installed_bytes = int(installed_bytes)
        last_updated = app.get("LastUpdated")
        if not isinstance(last_updated, str) or not last_updated.isdigit():
            last_updated = None
        else:
            last_updated = int(last_updated)
        install_dir = app.get("installdir")
        if not isinstance(install_dir, str):
            install_dir = ""
        return {"appid": appid, "name": name.strip(), "library": library,
                "manifest": path, "install_dir": install_dir,
                "installed_bytes": installed_bytes, "last_updated": last_updated,
                "status": "installed", "message": "",
                "component": (name.startswith("Proton")
                              or name.startswith("Steam Linux Runtime"))}
    except (OSError, UnicodeError, ValueError) as error:
        return error_row(library, path, filename_appid, str(error))


def scan(libraries):
    rows = []
    for library in libraries:
        steamapps = os.path.join(library, "steamapps")
        try:
            with os.scandir(steamapps) as directory:
                entries = sorted(directory, key=lambda entry: entry.name)
        except OSError as error:
            rows.append(error_row(library, steamapps, "", f"cannot scan library: {error}"))
            continue
        for entry in entries:
            if MANIFEST.fullmatch(entry.name):
                rows.append(manifest_row(library, entry))

    by_appid = {}
    for row in rows:
        if row["appid"] and row["status"] == "installed":
            by_appid.setdefault(row["appid"], []).append(row)
    for appid_rows in by_appid.values():
        if len(appid_rows) > 1:
            for row in appid_rows:
                row["status"] = "duplicate"
                row["message"] = "the same app ID is installed in more than one managed library"
    return sorted(rows, key=lambda row: (row["name"].casefold() or "\uffff", row["appid"], row["library"]))


def enrolled_homes():
    try:
        members = grp.getgrnam("ludus").gr_mem
    except KeyError:
        return []
    homes = []
    for user in members:
        try:
            account = pwd.getpwnam(user)
        except KeyError:
            continue
        if account.pw_dir.startswith("/") and os.path.isdir(account.pw_dir):
            homes.append(account.pw_dir)
    return homes


def image_kind(data):
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    return ""


def read_image(path):
    try:
        details = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(details.st_mode) or details.st_size > MAX_ARTWORK_BYTES:
            return None
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as source:
            data = source.read(MAX_ARTWORK_BYTES + 1)
        return data if len(data) <= MAX_ARTWORK_BYTES and image_kind(data) else None
    except OSError:
        return None


def local_portrait(appid, homes):
    for home in homes:
        directory = os.path.join(home, ".local", "share", "Steam", "appcache",
                                 "librarycache", appid)
        direct = read_image(os.path.join(directory, "library_600x900.jpg"))
        if direct:
            return direct
        try:
            children = os.scandir(directory)
        except OSError:
            continue
        with children:
            for child in children:
                if not re.fullmatch(r"[0-9a-f]{40}", child.name):
                    continue
                candidate = read_image(os.path.join(directory, child.name,
                                                    "library_600x900.jpg"))
                if candidate:
                    return candidate
    return None


def download_artwork(appid, filename):
    url = ("https://shared.cloudflare.steamstatic.com/store_item_assets/steam/"
           f"apps/{appid}/{filename}")
    request = urllib.request.Request(url, headers={"User-Agent": "Ludus/1 game-artwork"})
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            hostname = urllib.parse.urlparse(response.geturl()).hostname
            if hostname not in CDN_HOSTS:
                return None
            data = response.read(MAX_ARTWORK_BYTES + 1)
        return data if len(data) <= MAX_ARTWORK_BYTES and image_kind(data) else None
    except (OSError, ValueError):
        return None


def ensure_artwork_cache():
    os.makedirs(ARTWORK_CACHE, mode=0o750, exist_ok=True)
    os.chown(ARTWORK_CACHE, 0, grp.getgrnam("ludus-web").gr_gid)
    os.chmod(ARTWORK_CACHE, 0o750)


def write_cached_art(appid, layout, data):
    ensure_artwork_cache()
    suffix = image_kind(data)
    destination = os.path.join(ARTWORK_CACHE, f"{appid}.{layout}.{suffix}")
    with tempfile.NamedTemporaryFile("wb", dir=ARTWORK_CACHE, delete=False) as temporary:
        temporary.write(data)
        temporary.flush()
        os.fsync(temporary.fileno())
        name = temporary.name
    try:
        os.chmod(name, 0o640)
        os.chown(name, 0, grp.getgrnam("ludus-web").gr_gid)
        os.replace(name, destination)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass
    return layout


def cached_layout(appid):
    for layout in ("portrait", "wide"):
        for suffix in ("jpg", "png"):
            if read_image(os.path.join(ARTWORK_CACHE, f"{appid}.{layout}.{suffix}")):
                return layout
    return ""


def resolve_artwork(appid, homes):
    layout = cached_layout(appid)
    if layout:
        return layout
    missing = os.path.join(ARTWORK_CACHE, f"{appid}.missing")
    try:
        if time.time() - os.stat(missing, follow_symlinks=False).st_mtime < ARTWORK_RETRY_SECONDS:
            return ""
    except OSError:
        pass
    data = local_portrait(appid, homes) or download_artwork(appid, "library_600x900.jpg")
    if data:
        return write_cached_art(appid, "portrait", data)
    data = download_artwork(appid, "library_hero.jpg")
    if data:
        return write_cached_art(appid, "wide", data)
    try:
        descriptor = os.open(missing, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o640)
        os.close(descriptor)
        os.chown(missing, 0, grp.getgrnam("ludus-web").gr_gid, follow_symlinks=False)
    except OSError:
        pass
    return ""


def ensure_artwork(rows):
    ensure_artwork_cache()
    homes = enrolled_homes()
    appids = sorted({row["appid"] for row in rows
                     if row["appid"] and row["status"] != "error"})
    layouts = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as workers:
        pending = {workers.submit(resolve_artwork, appid, homes): appid for appid in appids}
        for future in concurrent.futures.as_completed(pending):
            appid = pending[future]
            try:
                layouts[appid] = future.result()
            except (OSError, ValueError):
                layouts[appid] = ""
    for row in rows:
        row["artwork"] = layouts.get(row["appid"], "")


def main():
    if len(sys.argv) != 1:
        raise SystemExit("usage: ludus-games")
    rows = scan(configured_libraries())
    ensure_artwork(rows)
    print(json.dumps({"version": 1, "games": rows},
                     separators=(",", ":")))


if __name__ == "__main__":
    main()
