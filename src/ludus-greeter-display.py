#!/usr/bin/env python3
"""Apply Ludus' optional display override inside the Plasma Login session."""
import json
import os
import subprocess
import sys

CONFIG = "/etc/ludus/greeter-display.json"
KSCREEN_DOCTOR = "/usr/bin/kscreen-doctor"


def message(text):
    print(f"ludus-greeter-display: {text}", file=sys.stderr)


def configured_display():
    try:
        with open(CONFIG, encoding="utf-8") as source:
            value = json.load(source)
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    width, height, refresh, scale = (value.get(key) for key in ("width", "height", "refresh", "scale"))
    if (not isinstance(width, int) or not isinstance(height, int)
            or not isinstance(refresh, (int, float)) or isinstance(refresh, bool)
            or not isinstance(scale, (int, float)) or isinstance(scale, bool)):
        return None
    if not (640 <= width <= 8192 and 480 <= height <= 8192 and 23 <= refresh <= 360):
        return None
    if scale not in {1, 1.25, 1.5, 1.75, 2}:
        return None
    return width, height, float(refresh), float(scale)


def main():
    wanted = configured_display()
    if wanted is None:
        return
    width, height, refresh, scale = wanted
    try:
        report = subprocess.run([KSCREEN_DOCTOR, "--json"], text=True, capture_output=True,
                                timeout=10, check=True)
        outputs = json.loads(report.stdout).get("outputs", [])
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        message(f"could not inspect greeter outputs: {error}; using the display default")
        return

    arguments = []
    for output in outputs:
        name = output.get("name")
        if not (output.get("connected") and output.get("enabled") and isinstance(name, str)
                and name.replace("-", "").replace("_", "").isalnum()):
            continue
        candidates = [mode for mode in output.get("modes", [])
                      if mode.get("size", {}).get("width") == width
                      and mode.get("size", {}).get("height") == height
                      and isinstance(mode.get("refreshRate"), (int, float))]
        if candidates:
            mode = min(candidates, key=lambda item: abs(item["refreshRate"] - refresh))
            if abs(mode["refreshRate"] - refresh) <= 1:
                arguments.append(f"output.{name}.mode.{mode['id']}")
            else:
                message(f"{name} has no {width}x{height} mode near {refresh:g} Hz; keeping its mode")
        else:
            message(f"{name} does not support {width}x{height}; keeping its mode")
        arguments.append(f"output.{name}.scale.{scale:g}")

    if not arguments:
        message("no enabled outputs were available; using the display default")
        return
    try:
        result = subprocess.run([KSCREEN_DOCTOR, *arguments], text=True, capture_output=True,
                                timeout=15, check=False)
    except OSError as error:
        message(f"could not apply display settings: {error}; using the display default")
        return
    if result.returncode:
        message(f"could not apply display settings: {result.stderr.strip() or result.stdout.strip()}")


if __name__ == "__main__":
    main()
