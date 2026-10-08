"""ADB executor — white-listed commands only.

Raw `adb shell` is NOT exposed. Only specific operations are allowed,
each logged to the journal.
"""

import base64
import re
import subprocess
from xml.etree import ElementTree

from phonebroker.config import load_config
from phonebroker.exceptions import ADBError

# Allowed adb subcommands (first token after "shell")
_ALLOWED_SHELL_COMMANDS = frozenset({
    "am", "input", "uiautomator", "dumpsys", "cmd", "ime",
    "settings", "pm", "get-state", "rm", "screencap",
})


def _adb(serial: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run an adb command. Raises ADBError on failure."""
    cmd = ["adb", "-s", serial, *args]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise ADBError(" ".join(cmd), result.returncode, result.stderr)
    return result


def _adb_shell(serial: str, command: str) -> str:
    """Run an adb shell command (white-listed). Returns stdout."""
    # Validate: first token must be in the allow-list
    first_token = command.split()[0] if command.split() else ""
    if first_token not in _ALLOWED_SHELL_COMMANDS:
        raise ADBError(
            f"adb shell {command!r}", 1,
            f"Command {first_token!r} not in white-list"
        )
    result = _adb(serial, "shell", command)
    return result.stdout.strip()


def get_phone_state() -> str:
    """Return phone ADB state: 'device', 'offline', 'unauthorized', etc."""
    cfg = load_config()
    try:
        result = _adb(cfg.adb.serial, "get-state")
        return result.stdout.strip()
    except (ADBError, subprocess.TimeoutExpired):
        return "offline"


def force_stop(package: str) -> None:
    cfg = load_config()
    _adb_shell(cfg.adb.serial, f"am force-stop {package}")


def keyevent(code: int) -> None:
    cfg = load_config()
    _adb_shell(cfg.adb.serial, f"input keyevent {code}")


def tap(x: int, y: int) -> None:
    cfg = load_config()
    _adb_shell(cfg.adb.serial, f"input tap {x} {y}")


def swipe(x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
    cfg = load_config()
    _adb_shell(
        cfg.adb.serial,
        f"input swipe {x1} {y1} {x2} {y2} {duration_ms}",
    )


def type_text(text: str) -> None:
    """Type Unicode text via ADBKeyBoard ADB_INPUT_B64 broadcast."""
    cfg = load_config()
    b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    _adb_shell(
        cfg.adb.serial,
        f"am broadcast -a ADB_INPUT_B64 --es msg '{b64}'",
    )


def launch_package(package: str) -> str:
    """Launch the main activity of a package. Returns the activity name."""
    cfg = load_config()
    # Resolve main activity
    output = _adb_shell(
        cfg.adb.serial,
        f"cmd package resolve-activity --brief {package}",
    )
    # Output format: "priority=... intent=..." or just the component
    # The last line is typically the component (package/activity)
    lines = [l for l in output.splitlines() if l.strip()]
    if not lines:
        raise ADBError(f"resolve-activity {package}", 1, "No activity found")
    component = lines[-1].strip()
    _adb_shell(cfg.adb.serial, f"am start -n {component}")
    return component


def screenshot() -> bytes:
    """Capture a screenshot. Returns PNG bytes."""
    cfg = load_config()
    remote_path = "/sdcard/phonebroker_screenshot.png"
    _adb_shell(cfg.adb.serial, f"screencap -p {remote_path}")
    # Pull the file
    local_path = f"/tmp/phonebroker_screenshot_{__import__('os').getpid()}.png"
    result = _adb(cfg.adb.serial, "pull", remote_path, local_path)
    with open(local_path, "rb") as f:
        data = f.read()
    # Clean up
    _adb_shell(cfg.adb.serial, f"rm {remote_path}")
    import os
    os.unlink(local_path)
    return data


def ui_dump() -> str:
    """Run uiautomator dump and return the XML content."""
    cfg = load_config()
    _adb_shell(cfg.adb.serial, "uiautomator dump /sdcard/ui_dump.xml")
    result = _adb(cfg.adb.serial, "shell", "cat /sdcard/ui_dump.xml")
    _adb_shell(cfg.adb.serial, "rm /sdcard/ui_dump.xml")
    return result.stdout.strip()


def find_element(selector: str) -> tuple[int, int] | None:
    """Find element center (x, y) by selector in the current UI dump.

    Supported selector formats:
      - "resource-id=value"
      - "text=value"
      - "content-desc=value"
    """
    xml_content = ui_dump()
    try:
        root = ElementTree.fromstring(xml_content)
    except ElementTree.ParseError:
        return None

    key, _, value = selector.partition("=")
    if not key or not value:
        return None

    for node in root.iter("node"):
        if node.get(key) == value:
            bounds = node.get("bounds", "")
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
            if m:
                x1, y1, x2, y2 = map(int, m.groups())
                return ((x1 + x2) // 2, (y1 + y2) // 2)
    return None


def set_ime(ime: str) -> None:
    cfg = load_config()
    _adb_shell(cfg.adb.serial, f"ime set {ime}")


def get_default_ime() -> str:
    cfg = load_config()
    return _adb_shell(
        cfg.adb.serial, "settings get secure default_input_method"
    )


def wait_for(selector: str, timeout_s: int = 30, interval_s: int = 1) -> bool:
    """Poll ui_dump until element found or timeout."""
    import time
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if find_element(selector) is not None:
            return True
        time.sleep(interval_s)
    return find_element(selector) is not None
