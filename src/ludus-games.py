#!/usr/bin/env python3
"""Read installed Steam app manifests from Ludus shared libraries."""
import json
import os
import re
import stat
import sys

LIBRARIES = "/etc/ludus/libraries.conf"
MANIFEST = re.compile(r"appmanifest_([0-9]+)\.acf\Z")
TOKENS = re.compile(r'"((?:\\.|[^"\\])*)"|([{}])')
MAX_MANIFEST_BYTES = 2 * 1024 * 1024


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
                "status": "installed", "message": ""}
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


def main():
    if len(sys.argv) != 1:
        raise SystemExit("usage: ludus-games")
    print(json.dumps({"version": 1, "games": scan(configured_libraries())},
                     separators=(",", ":")))


if __name__ == "__main__":
    main()
