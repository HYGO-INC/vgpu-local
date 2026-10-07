import argparse
import plistlib
import subprocess
import sys
import uuid

import pytest

from vgpu_local import autostart
from vgpu_local.autostart import LaunchAgent, SystemdUser, WindowsRun, for_platform
from vgpu_local.errors import UnsupportedCapability


class Calls(list):
    """Records supervisor commands instead of running them."""

    def __call__(self, args, **kwargs):
        self.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")


class FakeRegistry(dict):
    def get(self, value):
        return super().get(value)

    def set(self, value, line):
        self[value] = line

    def delete(self, value):
        self.pop(value, None)


@pytest.fixture(autouse=True)
def real_run_key_unchanged():
    """Fails any test that changes this machine's real startup entry."""
    if sys.platform != "win32":
        yield
        return
    before = autostart._WinReg().get(autostart.NAME)
    yield
    assert autostart._WinReg().get(autostart.NAME) == before, "a test changed the real startup entry"


def test_supervisors_run_serve_and_windows_runs_start(tmp_path):
    state = tmp_path / "runtime state"
    assert autostart.command(state, supervised=True)[-4:] == ["runtime", "serve", "--state", str(state)]
    assert autostart.command(state, supervised=False)[-4:] == ["runtime", "start", "--state", str(state)]


def test_systemd_unit_escapes_the_state_path_and_enables_now(tmp_path):
    calls = Calls()
    backend = SystemdUser(home=tmp_path, run=calls)
    backend.enable(tmp_path / "state 100% $HOME")
    unit = backend.unit.read_text(encoding="utf-8")
    exec_start = next(line for line in unit.splitlines() if line.startswith("ExecStart="))
    assert "state 100%% $$HOME" in exec_start
    assert "Restart=on-failure" in unit and "WantedBy=default.target" in unit
    assert calls == [["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", "--now", autostart.UNIT]]
    assert backend.status()["enabled"] is True

    calls.clear()
    assert backend.disable() == {"enabled": False, "mechanism": "systemd-user"}
    assert not backend.unit.exists()
    assert calls[0] == ["systemctl", "--user", "disable", "--now", autostart.UNIT]
    assert backend.disable()["enabled"] is False


def test_missing_systemd_is_reported_not_crashed(tmp_path):
    def missing(*args, **kwargs):
        raise FileNotFoundError("systemctl")

    with pytest.raises(UnsupportedCapability, match="systemd_user_unavailable"):
        SystemdUser(home=tmp_path, run=missing).enable(tmp_path / "state")


def test_launch_agent_keeps_the_runtime_alive_and_replaces_a_loaded_copy(tmp_path):
    calls = Calls()
    backend = LaunchAgent(home=tmp_path, run=calls, uid=501)
    state = tmp_path / "state"
    backend.enable(state)
    plist = plistlib.loads(backend.plist.read_bytes())
    assert plist["Label"] == autostart.LABEL and plist["RunAtLoad"] is True
    assert plist["KeepAlive"] == {"SuccessfulExit": False}
    assert plist["ProgramArguments"][-4:] == ["runtime", "serve", "--state", str(state)]
    assert [call[:3] for call in calls] == [["launchctl", "bootout", "gui/501"], ["launchctl", "bootstrap", "gui/501"]]

    backend.disable()
    assert not backend.plist.exists()


def test_windows_run_entry_round_trip_with_a_fake_registry(tmp_path):
    registry = FakeRegistry()
    backend = WindowsRun(registry=registry)
    assert backend.registry is registry  # an empty fake must not fall back to the real registry
    state = tmp_path / "my state"
    result = backend.enable(state)
    assert registry[autostart.NAME] == result["command"]
    assert result["command"] == subprocess.list2cmdline(autostart.command(state, supervised=False))
    assert backend.status()["enabled"] is True

    backend.disable()
    backend.disable()
    assert backend.status() == {"enabled": False, "mechanism": "windows-run-key"}


@pytest.mark.skipif(sys.platform != "win32", reason="the real Run key exists only on Windows")
def test_windows_run_entry_in_the_real_registry(tmp_path):
    # A unique value name, so the test never touches the user's real entry.
    backend = WindowsRun(value=f"vGPU autostart test {uuid.uuid4()}")
    try:
        backend.enable(tmp_path / "state")
        status = backend.status()
        assert status["enabled"] is True and "runtime start --state" in status["command"]
    finally:
        backend.disable()
    assert backend.status()["enabled"] is False


def test_unknown_platforms_are_refused():
    with pytest.raises(UnsupportedCapability, match="autostart_unsupported_platform"):
        for_platform("aix")


def test_cli_status_and_disable_work_without_an_initialized_runtime(tmp_path, monkeypatch):
    pytest.importorskip("httpx")
    from vgpu_local import runtime_cli

    registry = FakeRegistry()
    monkeypatch.setattr(autostart, "for_platform", lambda: WindowsRun(registry=registry))
    parser = argparse.ArgumentParser()
    runtime_cli.register(parser.add_subparsers(dest="action"))
    missing = str(tmp_path / "never-initialized")

    assert runtime_cli.run(parser.parse_args(["runtime", "autostart", "status", "--state", missing]))["enabled"] is False
    assert runtime_cli.run(parser.parse_args(["runtime", "autostart", "disable", "--state", missing]))["enabled"] is False
    with pytest.raises((ValueError, OSError)):
        runtime_cli.run(parser.parse_args(["runtime", "autostart", "enable", "--state", missing]))
    assert registry == {}
