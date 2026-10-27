"""Optional start at login for the local runtime (ADR 0026).

Off by default; only `vgpu-local runtime autostart enable` installs it. Each
platform uses its own per-user mechanism, so no administrator rights are needed:
the current user's Run registry key on Windows, a systemd user service on Linux
and a launchd agent on macOS. The runtime's state lock still allows only one
instance per state folder.
"""
import os
import plistlib
import subprocess
import sys
from pathlib import Path

from .errors import UnsupportedCapability

NAME = "vGPU local runtime"
UNIT = "vgpu-local-runtime.service"
LABEL = "com.vgpu.local-runtime"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def command(state: Path, *, supervised: bool) -> list[str]:
    """A supervisor keeps `serve` in the foreground; Windows launches `start`, which detaches."""
    python = Path(sys.executable)
    if os.name == "nt":
        windowless = python.with_name("pythonw.exe")
        if windowless.exists():
            python = windowless
    return [str(python), "-m", "vgpu_local", "runtime", "serve" if supervised else "start", "--state", str(state)]


class WindowsRun:
    """The current user's Run key. `registry` is injectable for tests."""

    def __init__(self, registry=None, value: str = NAME):
        # `is None`, not truthiness: an empty injected registry must never fall back to the real one.
        self.registry, self.value = (_WinReg() if registry is None else registry), value

    def enable(self, state: Path) -> dict:
        line = subprocess.list2cmdline(command(state, supervised=False))
        self.registry.set(self.value, line)
        return {"enabled": True, "mechanism": "windows-run-key", "command": line}

    def disable(self) -> dict:
        self.registry.delete(self.value)
        return {"enabled": False, "mechanism": "windows-run-key"}

    def status(self) -> dict:
        line = self.registry.get(self.value)
        return {"enabled": line is not None, "mechanism": "windows-run-key", **({"command": line} if line else {})}


class _WinReg:
    """The current user's `path`: the Run key unless a test names another."""

    def __init__(self, path: str = RUN_KEY):
        self.path = path

    def _key(self, access):
        import winreg
        return winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.path, 0, access)

    def get(self, value):
        import winreg
        try:
            with self._key(winreg.KEY_QUERY_VALUE) as key:
                return winreg.QueryValueEx(key, value)[0]
        except FileNotFoundError:
            return None

    def set(self, value, line):
        import winreg
        # A profile may have no Run key yet, as on a fresh Windows runner: create it.
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, value, 0, winreg.REG_SZ, line)

    def delete(self, value):
        import winreg
        try:
            with self._key(winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, value)
        except FileNotFoundError:
            pass


def _systemd_quote(argument: str) -> str:
    # systemd expands % specifiers and $ variables in ExecStart; double-quote each word.
    escaped = argument.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
    return f'"{escaped}"'


class SystemdUser:
    def __init__(self, home: Path | None = None, run=subprocess.run):
        self.unit = (home or Path.home()) / ".config/systemd/user" / UNIT
        self.run = run

    def _systemctl(self, *args, check=True):
        try:
            return self.run(["systemctl", "--user", *args], check=check, capture_output=True, text=True)
        except FileNotFoundError:
            raise UnsupportedCapability("systemd_user_unavailable") from None

    def enable(self, state: Path) -> dict:
        exec_start = " ".join(_systemd_quote(part) for part in command(state, supervised=True))
        self.unit.parent.mkdir(parents=True, exist_ok=True)
        self.unit.write_text("\n".join([
            "[Unit]", f"Description={NAME}", "",
            "[Service]", f"ExecStart={exec_start}", "Restart=on-failure", "RestartSec=5", "",
            "[Install]", "WantedBy=default.target", "",
        ]), encoding="utf-8")
        self._systemctl("daemon-reload")
        self._systemctl("enable", "--now", UNIT)
        return {"enabled": True, "mechanism": "systemd-user", "unit": str(self.unit)}

    def disable(self) -> dict:
        if self.unit.exists():
            self._systemctl("disable", "--now", UNIT, check=False)
            self.unit.unlink()
            self._systemctl("daemon-reload")
        return {"enabled": False, "mechanism": "systemd-user"}

    def status(self) -> dict:
        return {"enabled": self.unit.exists(), "mechanism": "systemd-user", "unit": str(self.unit)}


class LaunchAgent:
    def __init__(self, home: Path | None = None, run=subprocess.run, uid: int | None = None):
        self.plist = (home or Path.home()) / "Library/LaunchAgents" / f"{LABEL}.plist"
        self.run, self.domain = run, f"gui/{os.getuid() if uid is None else uid}"

    def enable(self, state: Path) -> dict:
        self.plist.parent.mkdir(parents=True, exist_ok=True)
        log = str(state / "runtime.log")
        self.plist.write_bytes(plistlib.dumps({
            "Label": LABEL, "ProgramArguments": command(state, supervised=True), "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False}, "ProcessType": "Background",
            "StandardOutPath": log, "StandardErrorPath": log,
        }))
        # Replace an already loaded copy; bootout fails harmlessly when none is loaded.
        self.run(["launchctl", "bootout", self.domain, str(self.plist)], check=False, capture_output=True)
        self.run(["launchctl", "bootstrap", self.domain, str(self.plist)], check=True, capture_output=True)
        return {"enabled": True, "mechanism": "launchd-agent", "plist": str(self.plist)}

    def disable(self) -> dict:
        if self.plist.exists():
            self.run(["launchctl", "bootout", self.domain, str(self.plist)], check=False, capture_output=True)
            self.plist.unlink()
        return {"enabled": False, "mechanism": "launchd-agent"}

    def status(self) -> dict:
        return {"enabled": self.plist.exists(), "mechanism": "launchd-agent", "plist": str(self.plist)}


def for_platform(platform: str = sys.platform):
    if platform == "win32":
        return WindowsRun()
    if platform == "darwin":
        return LaunchAgent()
    if platform.startswith("linux"):
        return SystemdUser()
    raise UnsupportedCapability("autostart_unsupported_platform")
