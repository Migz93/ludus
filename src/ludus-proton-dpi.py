#!/usr/bin/env python3
"""Reconcile Ludus-managed Wine DPI values in the active player's prefixes."""
import grp
import fcntl
import hashlib
import json
import os
import pwd
import re
import stat
import sys
import tempfile
import time
import uuid

CONFIG = "/etc/ludus/game-settings.json"
LIBRARIES = "/etc/ludus/libraries.conf"
STATE_DIR = "/var/lib/ludus/proton-dpi"
STATE = os.path.join(STATE_DIR, "state.json")
BACKUPS = os.path.join(STATE_DIR, "backups")
ACTIVE_USER = "/run/ludus-mount/active-user"
SCALES = {100: "00000060", 125: "00000078", 150: "00000090",
          175: "000000a8", 200: "000000c0", 250: "000000f0"}
APPID = re.compile(r"[0-9]+\Z")
MANIFEST = re.compile(r"appmanifest_([0-9]+)\.acf\Z")
SECTION = re.compile(r"^\[Control Panel\\\\Desktop\](?:\s.*)?$")
ANY_SECTION = re.compile(r"^\[.*\](?:\s.*)?$")
LOGPIXELS = re.compile(r'^"LogPixels"=dword:([0-9a-fA-F]{8})\s*$')


def default_config():
    return {"version": 1, "global": {"proton_overlay_dpi": None}, "games": {}}


def validate_config(value):
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("unsupported game-settings schema")
    global_settings, games = value.get("global"), value.get("games")
    if not isinstance(global_settings, dict) or not isinstance(games, dict):
        raise ValueError("invalid game-settings schema")
    if set(value) != {"version", "global", "games"} or set(global_settings) - {"proton_overlay_dpi", "launch_options"}:
        raise ValueError("unknown game-settings field")
    dpi = global_settings.get("proton_overlay_dpi")
    if dpi is not None and dpi not in SCALES:
        raise ValueError("invalid global Proton overlay DPI")
    for appid, settings in games.items():
        if not isinstance(appid, str) or not APPID.fullmatch(appid) or not isinstance(settings, dict):
            raise ValueError("invalid per-game settings")
        if set(settings) - {"proton_overlay_dpi", "launch_options"}:
            raise ValueError(f"unknown setting for app {appid}")
        policy = settings.get("proton_overlay_dpi", "inherit")
        if policy not in ({"inherit", "disabled"} | set(SCALES)):
            raise ValueError(f"invalid Proton overlay DPI for app {appid}")
    if "launch_options" in global_settings or any("launch_options" in item for item in games.values()):
        import importlib.machinery
        import importlib.util
        path = os.path.join(os.path.dirname(__file__), "ludus-launch-options")
        if not os.path.exists(path): path += ".py"
        loader = importlib.machinery.SourceFileLoader("launch_options", path)
        spec = importlib.util.spec_from_loader("launch_options", loader)
        launch = importlib.util.module_from_spec(spec)
        loader.exec_module(launch)
        launch.validate_policy(global_settings.get("launch_options", {}))
        for item in games.values():
            launch.validate_policy(item.get("launch_options", {}), game=True)
    return value


def read_json(path, fallback):
    try:
        with open(path, encoding="utf-8") as source:
            return json.load(source)
    except FileNotFoundError:
        return fallback


def load_config(path=CONFIG):
    return validate_config(read_json(path, default_config()))


def effective_dpi(config, appid):
    policy = config["games"].get(str(appid), {}).get("proton_overlay_dpi", "inherit")
    if policy == "disabled":
        return None
    if policy == "inherit":
        return config["global"].get("proton_overlay_dpi")
    return policy


def atomic_json(path, value, mode=0o600, gid=0):
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory, delete=False) as target:
        json.dump(value, target, separators=(",", ":"), sort_keys=True)
        target.write("\n"); target.flush(); os.fsync(target.fileno())
        temporary = target.name
    try:
        os.chmod(temporary, mode); os.chown(temporary, 0, gid)
        os.replace(temporary, path)
        descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
    finally:
        try: os.unlink(temporary)
        except FileNotFoundError: pass


def parse_logpixels(text):
    lines = text.splitlines(keepends=True)
    in_section, found = False, []
    for index, line in enumerate(lines):
        plain = line.rstrip("\r\n")
        if ANY_SECTION.fullmatch(plain):
            in_section = bool(SECTION.fullmatch(plain))
        elif in_section:
            match = LOGPIXELS.fullmatch(plain)
            if match: found.append((index, match.group(1).lower()))
    if len(found) > 1:
        raise ValueError("duplicate LogPixels values in Control Panel\\\\Desktop")
    return lines, found[0] if found else None


def update_logpixels(text, value):
    lines, found = parse_logpixels(text)
    desired = value.lower() if value is not None else None
    if found and found[1] == desired:
        return text, False
    if found:
        index = found[0]
        if desired is None:
            del lines[index]
        else:
            ending = "\r\n" if lines[index].endswith("\r\n") else "\n"
            lines[index] = f'"LogPixels"=dword:{desired}{ending}'
        return "".join(lines), True
    if desired is None:
        return text, False
    section_index = None
    for index, line in enumerate(lines):
        if SECTION.fullmatch(line.rstrip("\r\n")):
            section_index = index
            break
    if section_index is None:
        raise ValueError("missing exact Control Panel\\\\Desktop section")
    insert = len(lines)
    for index in range(section_index + 1, len(lines)):
        if ANY_SECTION.fullmatch(lines[index].rstrip("\r\n")):
            insert = index
            break
    ending = "\r\n" if any(line.endswith("\r\n") for line in lines) else "\n"
    lines.insert(insert, f'"LogPixels"=dword:{desired}{ending}')
    return "".join(lines), True


def safe_user_reg(library, appid):
    if not isinstance(appid, str) or not APPID.fullmatch(appid):
        raise ValueError("app ID must contain digits only")
    root = os.path.realpath(os.path.join(library, "steamapps", "compatdata"))
    path = os.path.join(root, appid, "pfx", "user.reg")
    cursor = root
    for component in (appid, "pfx", "user.reg"):
        cursor = os.path.join(cursor, component)
        try: details = os.lstat(cursor)
        except FileNotFoundError: return None
        if stat.S_ISLNK(details.st_mode):
            raise ValueError(f"refusing symlink in Proton prefix: {cursor}")
    resolved = os.path.realpath(path)
    if resolved != path or os.path.commonpath((root, resolved)) != root:
        raise ValueError("resolved Proton prefix path escaped compatdata")
    details = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(details.st_mode):
        raise ValueError("user.reg is not a regular file")
    return path


def read_registry(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("user.reg is not a regular file")
        data = source.read()
    return metadata, data, data.decode("utf-8")


def atomic_registry(path, text, metadata):
    directory = os.path.dirname(path)
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
    if os.path.realpath(f"/proc/self/fd/{directory_fd}") != directory:
        os.close(directory_fd)
        raise ValueError("Proton prefix directory changed during validation")
    temporary = ".ludus-dpi-" + uuid.uuid4().hex
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             stat.S_IMODE(metadata.st_mode), dir_fd=directory_fd)
        with os.fdopen(descriptor, "wb") as target:
            target.write(text.encode("utf-8")); target.flush(); os.fsync(target.fileno())
            os.fchown(target.fileno(), metadata.st_uid, metadata.st_gid)
            os.fchmod(target.fileno(), stat.S_IMODE(metadata.st_mode))
        os.replace(temporary, os.path.basename(path),
                   src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        try: os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError: pass
        os.close(directory_fd)


def installed_apps(libraries):
    apps = {}
    for library in libraries:
        steamapps = os.path.join(library, "steamapps")
        try: names = os.listdir(steamapps)
        except OSError: continue
        for name in names:
            match = MANIFEST.fullmatch(name)
            if match: apps.setdefault(match.group(1), []).append(library)
    return apps


def library_identity(library):
    return hashlib.sha256(os.path.realpath(library).encode()).hexdigest()[:16]


def instance_records(app_record):
    instances = app_record.get("instances") if isinstance(app_record, dict) else None
    if isinstance(instances, dict):
        records = list(instances.values())
        if isinstance(app_record.get("legacy"), dict):
            records.append(app_record["legacy"])
        return records
    return [app_record]


def ensure_instances(app_record, app_libraries):
    """Migrate legacy per-app state when its library identity is unambiguous."""
    if isinstance(app_record.get("instances"), dict):
        return app_record["instances"]
    legacy = dict(app_record)
    app_record.clear()
    app_record["instances"] = {}
    if len(app_libraries) == 1:
        library = os.path.realpath(app_libraries[0])
        legacy["library"] = library
        app_record["instances"][library_identity(library)] = legacy
    elif legacy.get("managed") or legacy.get("pending_restore"):
        # Old releases collapsed duplicate prefixes into one record, so there
        # is no safe way to infer which original value belongs to which file.
        app_record["legacy"] = legacy
        app_record["migration_error"] = (
            "legacy managed state is ambiguous across duplicate libraries")
    return app_record["instances"]


def reconcile_one(user, appid, library, target, record, backup_root=BACKUPS):
    now = int(time.time())
    try:
        path = safe_user_reg(library, appid)
        if path is None:
            record.update(status="no-prefix", error="", updated=now)
            return
        metadata, original_bytes, text = read_registry(path)
        if target is None and not record.get("managed") and not record.get("pending_restore"):
            record.update(status="disabled", error="", updated=now)
            return
        _lines, current = parse_logpixels(text)
        if not record.get("original_recorded"):
            backup = os.path.join(backup_root, user, appid,
                                  library_identity(library), "user.reg")
            os.makedirs(os.path.dirname(backup), mode=0o700, exist_ok=True)
            descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "wb") as destination:
                destination.write(original_bytes); destination.flush(); os.fsync(destination.fileno())
            record.update(original_recorded=True, original_present=current is not None,
                          original_value=current[1] if current else None, backup=backup)
        restoring = target is None
        desired = record.get("original_value") if restoring and record.get("original_present") else (None if restoring else SCALES[target])
        changed_text, changed = update_logpixels(text, desired)
        if changed: atomic_registry(path, changed_text, metadata)
        record.update(managed=not restoring, pending_restore=False,
                      status="restored" if restoring else ("applied" if changed else "current"),
                      dpi=None if restoring else target, error="", updated=now)
    except Exception as error:
        record.update(status="error", error=str(error), updated=now)


def load_libraries(path=LIBRARIES):
    try:
        with open(path, encoding="utf-8") as source:
            return [line.strip() for line in source if line.strip() and not line.lstrip().startswith("#")]
    except FileNotFoundError: return []


def reconcile(user, config_path=CONFIG, state_path=STATE, libraries_path=LIBRARIES):
    account = pwd.getpwnam(user)
    if account.pw_uid == 0 or user not in grp.getgrnam("ludus").gr_mem:
        raise ValueError("user is not an enrolled Ludus player")
    try:
        with open(ACTIVE_USER, encoding="utf-8") as source: active = source.read().strip()
    except FileNotFoundError: active = ""
    if active != user: raise ValueError("player is not the active mounted user")
    config, state = load_config(config_path), read_json(state_path, {"version": 1, "users": {}})
    records = state.setdefault("users", {}).setdefault(user, {})
    apps = installed_apps(load_libraries(libraries_path))
    for appid in sorted(set(apps) | set(records), key=int):
        app_record = records.setdefault(appid, {})
        app_libraries = apps.get(appid, [])
        instances = ensure_instances(app_record, app_libraries)
        if app_record.get("migration_error"):
            continue
        active_keys = set()
        for library in app_libraries:
            library = os.path.realpath(library)
            key = library_identity(library)
            active_keys.add(key)
            record = instances.setdefault(key, {"library": library})
            record["library"] = library
            target = None if record.get("pending_restore") else effective_dpi(config, appid)
            reconcile_one(user, appid, library, target, record)
        for key, record in instances.items():
            if key not in active_keys:
                record.update(status="not-installed", error="",
                              updated=int(time.time()))
    atomic_json(state_path, state)
    return state


def aggregate_record(app_record):
    if app_record.get("migration_error"):
        return {"status": "error", "error": app_record["migration_error"],
                "pending_restore": True}
    records = instance_records(app_record)
    if not records:
        return {}
    priority = {"error": 0, "pending-restore": 1, "no-prefix": 2,
                "not-installed": 3, "pending-apply": 4, "applied": 5,
                "current": 6, "restored": 7, "disabled": 8}
    chosen = min(records, key=lambda item: priority.get(item.get("status"), 9))
    allowed = ("status", "error", "updated", "dpi")
    result = {key: chosen[key] for key in allowed if key in chosen}
    result["pending_restore"] = any(record.get("pending_restore") for record in records)
    errors = sorted({record.get("error", "") for record in records if record.get("error")})
    if errors: result["error"] = "; ".join(errors)
    result["instances"] = len(records)
    return result


def public_settings(config_path=CONFIG, state_path=STATE):
    config = load_config(config_path)
    state = read_json(state_path, {"version": 1, "users": {}})
    visible = {}
    for user, records in state.get("users", {}).items():
        visible[user] = {appid: aggregate_record(record)
                         for appid, record in records.items()}
    return {"version": 1, "global": config["global"], "games": config["games"],
            "reconciliation": visible}


def save_policy(argument, config_path=CONFIG, state_path=STATE):
    if not isinstance(argument, dict): raise ValueError("invalid Proton DPI request")
    config = load_config(config_path)
    scope = argument.get("scope")
    if scope == "global":
        value = argument.get("dpi")
        if value is not None and value not in SCALES: raise ValueError("invalid Proton DPI")
        config["global"]["proton_overlay_dpi"] = value
    elif scope == "game":
        appid, value = argument.get("appid"), argument.get("policy")
        if not isinstance(appid, str) or not APPID.fullmatch(appid): raise ValueError("invalid app ID")
        if value not in ({"inherit", "disabled"} | set(SCALES)): raise ValueError("invalid game Proton DPI policy")
        if value == "inherit":
            config["games"].get(appid, {}).pop("proton_overlay_dpi", None)
        else: config["games"].setdefault(appid, {})["proton_overlay_dpi"] = value
    else: raise ValueError("invalid Proton DPI scope")
    validate_config(config)
    state = read_json(state_path, {"version": 1, "users": {}})
    for records in state.get("users", {}).values():
        for appid, app_record in records.items():
            for record in instance_records(app_record):
                if record.get("managed"):
                    if effective_dpi(config, appid) is None:
                        record["pending_restore"] = True
                        record["status"] = "pending-restore"
                    elif record.get("pending_restore"):
                        record["pending_restore"] = False
                        record["status"] = "pending-apply"
    atomic_json(config_path, config, 0o640, grp.getgrnam("ludus-web").gr_gid)
    atomic_json(state_path, state)
    return public_settings(config_path, state_path)


def uninstall_blockers(state_path=STATE):
    state = read_json(state_path, {"version": 1, "users": {}})
    blockers = []
    for user, records in state.get("users", {}).items():
        for appid, app_record in records.items():
            for record in instance_records(app_record):
                if record.get("managed") or record.get("pending_restore"):
                    blockers.append({"user": user, "appid": appid,
                                     "library": record.get("library", ""),
                                     "status": record.get("status", "managed")})
    return blockers


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "reconcile":
        reconcile(sys.argv[2]); return
    if len(sys.argv) == 2 and sys.argv[1] == "settings":
        print(json.dumps(public_settings(), separators=(",", ":"))); return
    if len(sys.argv) == 2 and sys.argv[1] == "save":
        argument = json.load(sys.stdin)
        print(json.dumps(save_policy(argument), separators=(",", ":"))); return
    if len(sys.argv) == 2 and sys.argv[1] == "uninstall-check":
        blockers = uninstall_blockers()
        print(json.dumps(blockers, separators=(",", ":")))
        raise SystemExit(2 if blockers else 0)
    raise SystemExit("usage: ludus-proton-dpi reconcile USER | settings | save | uninstall-check")


if __name__ == "__main__":
    # Serialize both features' read/modify/write operations on the shared policy.
    with open("/etc/ludus/game-settings.lock", "a") as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        main()
