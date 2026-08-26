#!/usr/bin/env python3
"""List or safely remove a user's non-Ludus Steam library registrations."""
import json
import os
import pwd
import re
import shutil
import stat
import sys
import tempfile

LIBRARIES = "/etc/ludus/libraries.conf"
TOKENS = re.compile(r'"((?:\\.|[^"\\])*)"|([{}])')

def steam_files(user):
    home = pwd.getpwnam(user).pw_dir
    root = os.path.join(home, ".local", "share", "Steam")
    return [os.path.join(root, "config", "libraryfolders.vdf"), os.path.join(root, "steamapps", "libraryfolders.vdf")]

def shared_paths():
    try:
        with open(LIBRARIES, encoding="utf-8") as file:
            return {line.strip() for line in file if line.strip() and not line.startswith("#")}
    except FileNotFoundError:
        return set()

def parse(text):
    tokens = [(match.group(1) if match.group(1) is not None else match.group(2)) for match in TOKENS.finditer(text)]
    def unquote(value): return value.replace(r'\"', '"').replace(r'\\', '\\')
    def block(index):
        output = {}
        while index < len(tokens) and tokens[index] != "}":
            key = unquote(tokens[index]); index += 1
            if index >= len(tokens): raise ValueError("incomplete KeyValues entry")
            if tokens[index] == "{":
                value, index = block(index + 1)
            elif tokens[index] == "}":
                raise ValueError("missing KeyValues value")
            else:
                value = unquote(tokens[index]); index += 1
            output[key] = value
        if index >= len(tokens): raise ValueError("unclosed KeyValues block")
        return output, index + 1
    if len(tokens) < 2 or tokens[1] != "{": raise ValueError("unrecognised KeyValues document")
    root, end = block(2)
    if end != len(tokens): raise ValueError("trailing KeyValues data")
    return {unquote(tokens[0]): root}

def quote(value): return '"' + value.replace('\\', r'\\').replace('"', r'\"') + '"'
def render(value, depth=0):
    indent = "\t" * depth
    lines = []
    for key, item in value.items():
        if isinstance(item, dict): lines += [f"{indent}{quote(key)}", f"{indent}{{", render(item, depth + 1), f"{indent}}}"]
        else: lines.append(f"{indent}{quote(key)}\t\t{quote(item)}")
    return "\n".join(lines)

def entries(path):
    with open(path, encoding="utf-8") as file: document = parse(file.read())
    folders = document.get("libraryfolders")
    if not isinstance(folders, dict): raise ValueError("missing libraryfolders block")
    return document, folders

def paths_for(user):
    paths = set()
    for path in steam_files(user):
        if not os.path.isfile(path): continue
        _document, folders = entries(path)
        for key, entry in folders.items():
            if key.isdigit() and isinstance(entry, dict) and isinstance(entry.get("path"), str): paths.add(entry["path"])
    return sorted(paths - shared_paths())

def rewrite(path, document):
    backup = path + ".ludus.bak"
    shutil.copy2(path, backup)
    details = os.stat(path)
    directory = os.path.dirname(path)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory, delete=False) as temporary:
        temporary.write(render(document) + "\n"); temporary_name = temporary.name
    os.chmod(temporary_name, stat.S_IMODE(details.st_mode)); os.chown(temporary_name, details.st_uid, details.st_gid)
    os.replace(temporary_name, path)

def remove(user, requested):
    if requested in shared_paths(): raise ValueError("Ludus shared libraries cannot be removed from a user's Steam list here")
    changed = False
    for path in steam_files(user):
        if not os.path.isfile(path): continue
        document, folders = entries(path)
        kept = [(key, entry) for key, entry in folders.items() if not (key.isdigit() and isinstance(entry, dict) and entry.get("path") == requested)]
        if len(kept) == len(folders): continue
        replacement = {}
        next_key = 0
        for key, entry in kept:
            replacement[str(next_key) if key.isdigit() else key] = entry
            if key.isdigit(): next_key += 1
        document["libraryfolders"] = replacement
        rewrite(path, document); changed = True
    if not changed: raise ValueError("library is not registered for this user")

def make_default(user, requested):
    documents = []
    for path in steam_files(user):
        if not os.path.isfile(path): continue
        document, folders = entries(path)
        selected = next((entry for key, entry in folders.items() if key.isdigit() and isinstance(entry, dict) and entry.get("path") == requested), None)
        if selected is None: raise ValueError("library is not registered for this user")
        replacement, next_key = {"0": selected}, 1
        for key, entry in folders.items():
            if key.isdigit():
                if entry is selected: continue
                replacement[str(next_key)] = entry; next_key += 1
            else: replacement[key] = entry
        document["libraryfolders"] = replacement
        documents.append((path, document))
    if not documents: raise ValueError("Steam has not created a libraryfolders.vdf yet")
    for path, document in documents: rewrite(path, document)

def set_library_label(user, requested, label):
    changed = False
    for path in steam_files(user):
        if not os.path.isfile(path): continue
        document, folders = entries(path)
        selected = next((entry for key, entry in folders.items()
                         if key.isdigit() and isinstance(entry, dict) and entry.get("path") == requested), None)
        if selected is None: raise ValueError(f"library is not registered for {user}: {requested}")
        if selected.get("label") != label:
            selected["label"] = label
            rewrite(path, document)
            changed = True
    return changed

def set_shared_library_label(requested, label):
    marker = os.path.join(requested, "libraryfolder.vdf")
    if not os.path.isfile(marker): raise ValueError(f"Steam has not initialised this library: {marker} is missing")
    with open(marker, encoding="utf-8") as file: document = parse(file.read())
    folder = document.get("libraryfolder")
    if not isinstance(folder, dict): raise ValueError("unrecognised Steam library marker")
    if folder.get("label") == label: return False
    folder["label"] = label
    rewrite(marker, document)
    return True

def label_home_library(user, label="DO NOT USE"):
    """Label Steam's mandatory per-user library without changing its path.

    This library contains the client and account-specific state, so it must
    remain registered.  The label simply prevents it being mistaken for a
    Ludus shared install location.
    """
    home = pwd.getpwnam(user).pw_dir
    steam_root = os.path.realpath(os.path.join(home, ".local", "share", "Steam"))
    changed = False
    for path in steam_files(user):
        if not os.path.isfile(path): continue
        document, folders = entries(path)
        for key, entry in folders.items():
            if not key.isdigit() or not isinstance(entry, dict) or not isinstance(entry.get("path"), str): continue
            if os.path.realpath(entry["path"]) == steam_root and entry.get("label") != label:
                entry["label"] = label
                changed = True
        if changed:
            rewrite(path, document)
    return changed

def check(user):
    """Report the Ludus entries in both Steam VDF locations without editing.

    Returns (ok, records); each record is (severity, code, subject, data,
    message).  The message text is what the human-readable mode prints, so both
    modes stay in step.
    """
    shared = shared_paths()
    problems = False
    records = []
    missing_by_file = {}
    ok_files = []
    for path in steam_files(user):
        if not os.path.isfile(path):
            records.append(("WARNING", "steam-registration.absent", user, f"file={path}",
                            f"Steam registration {user}: VDF not created yet: {path}"))
            continue
        try:
            _document, folders = entries(path)
        except (OSError, ValueError) as error:
            records.append(("ERROR", "steam-registration.unreadable", user, f"file={path}",
                            f"Steam registration {user}: cannot read {path}: {error}"))
            problems = True
            continue
        registered = {entry.get("path") for key, entry in folders.items()
                      if key.isdigit() and isinstance(entry, dict) and isinstance(entry.get("path"), str)}
        missing = sorted(shared - registered)
        if missing:
            missing_by_file[path] = missing
        else:
            ok_files.append(path)

    # Ludus writes every Steam configuration file identically, so the same
    # gap in each one is a single real problem, not one per file. Only report
    # them separately if the files have genuinely drifted apart from each
    # other, which is itself worth knowing.
    if missing_by_file:
        distinct_gaps = {tuple(gap) for gap in missing_by_file.values()}
        if len(distinct_gaps) == 1:
            gap = list(next(iter(distinct_gaps)))
            files = ", ".join(missing_by_file)
            records.append(("WARNING", "steam-registration.missing-paths", user,
                            f"file={files}|missing={', '.join(gap)}",
                            f"Steam registration {user}: {files} is missing shared path(s): {', '.join(gap)}"))
        else:
            for path, gap in missing_by_file.items():
                records.append(("WARNING", "steam-registration.missing-paths", user,
                                f"file={path}|missing={', '.join(gap)}",
                                f"Steam registration {user}: {path} is missing shared path(s): {', '.join(gap)}"))

    for path in ok_files:
        records.append(("HEALTHY", "steam-registration.complete", user,
                        f"file={path}",
                        f"Steam registration {user}: {path} has all shared libraries"))
    return not problems, records

if len(sys.argv) < 3 or sys.argv[1] not in {"list", "list-many", "remove", "make-default", "set-library-label", "set-shared-library-label", "label-home-library", "check", "check-records"}: raise SystemExit("usage: ludus-steam-user-libraries list <user> | list-many <user>... | remove <user> <path> | make-default <user> <path> | set-library-label <user> <path> <label> | set-shared-library-label <path> <label> | label-home-library <user> | check <user> | check-records <user>")
try:
    action = sys.argv[1]
    if action != "set-shared-library-label":
        for user in sys.argv[2:] if action == "list-many" else [sys.argv[2]]: pwd.getpwnam(user)
    if action == "list": print(json.dumps(paths_for(sys.argv[2])))
    elif action == "list-many": print(json.dumps([{"user": user, "paths": paths_for(user)} for user in sys.argv[2:]]))
    elif action == "remove":
        if len(sys.argv) != 4: raise ValueError("a library path is required")
        remove(sys.argv[2], sys.argv[3]); print("removed Steam library registration; no files were deleted")
    elif action == "set-library-label":
        if len(sys.argv) != 5: raise ValueError("a library path and label are required")
        print("updated Steam library label" if set_library_label(sys.argv[2], sys.argv[3], sys.argv[4]) else "Steam library label already set")
    elif action == "set-shared-library-label":
        if len(sys.argv) != 4: raise ValueError("a library path and label are required")
        print("updated shared library label" if set_shared_library_label(sys.argv[2], sys.argv[3]) else "shared library label already set")
    elif action == "label-home-library":
        if len(sys.argv) != 3: raise ValueError("label-home-library accepts one user")
        print("labelled mandatory Steam library" if label_home_library(sys.argv[2]) else "mandatory Steam library already labelled")
    else:
        if action in {"check", "check-records"}:
            if len(sys.argv) != 3: raise ValueError("check accepts one user")
            ok, records = check(sys.argv[2])
            for severity, code, subject, data, message in records:
                print("\t".join((severity, code, subject, data, message)) if action == "check-records" else f"{severity} {message}")
            if not ok: raise ValueError("one or more Steam VDF files are invalid")
        else:
            if len(sys.argv) != 4: raise ValueError("a library path is required")
            make_default(sys.argv[2], sys.argv[3]); print("updated Steam default library")
except (OSError, ValueError) as error:
    raise SystemExit(f"ludus-steam-user-libraries: {error}")
