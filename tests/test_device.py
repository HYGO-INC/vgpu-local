import json
from urllib.parse import parse_qs

import httpx
import pytest

from vgpu_local.cloud import CloudConnection, CloudError
from vgpu_local.device import DeviceConnection


class Secrets:
    def __init__(self): self.values = {}
    def get(self, name): return self.values.get(name)
    def set(self, name, value): self.values[name] = value


class Clock:
    def __init__(self): self.now = 1000; self.waits = []
    def time(self): return self.now
    def sleep(self, delay): self.waits.append(delay); self.now += delay


class Server:
    def __init__(self):
        self.calls = []; self.polls = ["authorization_pending", "success"]
        self.enrolled = None; self.start_changes = {}; self.approval_changes = {}; self.lose_enroll = False
        self.starts = 0

    def request(self, request):
        self.calls.append(request)
        if request.url.path == "/oauth/device_authorization":
            self.starts += 1
            self.info = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            return httpx.Response(200, json=dict(device_code="private-device-code", user_code="BCDF-GHJK-LMNP",
                verification_uri="https://cloud.example/device", expires_in=600, **self.start_changes))
        if request.url.path == "/oauth/token":
            step = self.polls.pop(0)
            if step == "timeout": raise httpx.ReadTimeout("secret must not be printed")
            if step != "success": return httpx.Response(400, json={"error": step, "error_description": "secret data"})
            return httpx.Response(200, json=dict(access_token="private-enrollment-token", token_type="Bearer", scope="vgpu:enroll", expires_in=300, unknown_extension=True))
        if request.url.path == "/api/v1/device/approval":
            assert request.headers["authorization"] == "Bearer private-enrollment-token"
            return httpx.Response(200, json={"site_id": self.info["site_id"], "name": self.info["site_name"],
                "tenant_id": "ten_example0", "project_id": "prj_example0", **self.approval_changes})
        if request.url.path == "/api/v1/device/enroll":
            self.enrolled = json.loads(request.content)
            if self.lose_enroll:
                self.lose_enroll = False
                raise httpx.ReadTimeout("secret")
            return httpx.Response(201, json=self.connection())
        if request.url.path.endswith("/connection"):
            if self.enrolled:
                assert request.headers["authorization"] == "Bearer " + self.enrolled["credential"]
                return httpx.Response(200, json=self.connection())
            return httpx.Response(401, json={"error": "unauthorized"})
        raise AssertionError("unexpected endpoint")

    def connection(self):
        return dict(site_id=self.enrolled["site_id"], name=self.enrolled["name"], tenant_id="ten_example0", project_id="prj_example0",
                    protocol_version="vgpu.site.v1", state="active", credential_expires_at=1800000000,
                    consumption_enabled=False, contribution_enabled=False)


@pytest.fixture
def setup(tmp_path):
    server, secrets, clock = Server(), Secrets(), Clock()
    cloud = CloudConnection(tmp_path / "cloud.json", secrets, transport=httpx.MockTransport(server.request), lock_dir=tmp_path / "locks")
    client = DeviceConnection(cloud, clock=clock.time, sleep=clock.sleep)
    return server, secrets, clock, cloud, client


def connect(client, **kwargs):
    return client.connect(endpoint="https://cloud.example", name="Office", announce=lambda *_: None, **kwargs)


def test_code_flow_only_displays_public_link_and_code_and_persists_no_account_token(setup):
    server, secrets, clock, cloud, client = setup
    announced = []
    result = client.connect(endpoint="https://cloud.example", name="Office", announce=lambda *values: announced.append(values))
    assert announced == [("https://cloud.example/device", "BCDF-GHJK-LMNP")]
    assert result["state"] == "active"
    assert clock.waits == [5, 5]  # Standard default when interval is omitted.
    config = cloud.config.read_text()
    assert "credential" not in config and "token" not in config and "private-device-code" not in config
    assert [v for k, v in secrets.values.items() if k.startswith("device:")] == [""]
    assert server.enrolled["credential"] in secrets.values.values()
    assert not result["consumption_enabled"] and not result["contribution_enabled"]


def test_slow_down_adds_five_seconds_permanently_and_timeout_reduces_frequency(setup):
    server, _, clock, _, client = setup
    server.polls = ["slow_down", "authorization_pending", "timeout", "success"]
    connect(client)
    assert clock.waits == [5, 10, 10, 20]


def test_process_restart_keeps_polling_interval_and_same_pending_machine(setup):
    server, _, clock, cloud, client = setup
    server.polls = ["slow_down", "success"]
    real_sleep = clock.sleep
    def crash(delay):
        if len(clock.waits) == 1: raise KeyboardInterrupt()
        real_sleep(delay)
    client.sleep = crash
    with pytest.raises(KeyboardInterrupt): connect(client)
    client = DeviceConnection(cloud, clock=clock.time, sleep=real_sleep)
    connect(client)
    assert server.starts == 1 and clock.waits == [5, 10]


def test_lost_enrollment_reply_recovers_even_after_grant_expiry_without_new_device_flow(setup):
    server, _, clock, cloud, client = setup
    server.lose_enroll = True
    with pytest.raises(CloudError, match="device_network_retry_same_connection"): connect(client)
    before = cloud.config.read_bytes()
    clock.now += 1000
    result = connect(DeviceConnection(cloud, clock=clock.time, sleep=clock.sleep))
    assert result["state"] == "active" and before == cloud.config.read_bytes() and server.starts == 1
    assert len([r for r in server.calls if r.url.path == "/api/v1/device/enroll"]) == 1


@pytest.mark.parametrize("error", ["access_denied", "expired_token", "invalid_grant", "temporarily_unavailable", "unknown_with_secrets"])
def test_terminal_errors_stop_and_never_start_a_new_authorization(setup, error):
    server, _, _, cloud, client = setup
    server.polls = [error]
    with pytest.raises(CloudError) as caught: connect(client)
    assert "secret" not in str(caught.value)
    with pytest.raises(CloudError, match="ended_use_restart"): connect(client)
    assert server.starts == 1 and not cloud.config.exists()


def test_expiry_stops_before_next_poll_and_explicit_restart_is_required(setup):
    server, _, clock, _, client = setup
    server.start_changes = {"interval": 60}
    server.polls = ["slow_down"] * 20
    with pytest.raises(CloudError, match="expired_use_restart"): connect(client)
    assert clock.now == 1600 and server.starts == 1
    server.polls = ["success"]
    assert connect(client, restart=True)["state"] == "active" and server.starts == 2


def test_initial_response_loss_requires_explicit_restart_without_copying_secrets(setup):
    server, _, _, cloud, client = setup
    actual = server.request
    def timeout(request):
        actual(request)
        raise httpx.ReadTimeout("secret")
    cloud.transport = httpx.MockTransport(timeout)
    with pytest.raises(CloudError, match="network_retry"): connect(client)
    cloud.transport = httpx.MockTransport(actual)
    with pytest.raises(CloudError, match="outcome_unknown_use_restart"): connect(client)
    assert server.starts == 1
    connect(client, restart=True)
    assert server.starts == 2


@pytest.mark.parametrize("changes", [
    {"verification_uri": "https://evil.example/device"}, {"verification_uri": "https://cloud.example/\x1b[1m"},
    {"verification_uri": "https://user@cloud.example/device"}, {"expires_in": True}, {"interval": 0},
    {"user_code": "secret\ncommand"}, {"device_code": None},
])
def test_bad_start_responses_never_reach_terminal_or_polling(setup, changes):
    server, _, _, cloud, client = setup
    # Override response without conflicting kwargs in the fixture.
    def changed(request):
        response = server.request(request)
        return httpx.Response(200, json={**response.json(), **changes})
    cloud.transport = httpx.MockTransport(changed)
    with pytest.raises(CloudError, match="invalid_device_response"): connect(client)
    assert len(server.calls) == 1 and not cloud.config.exists()


def test_no_silent_takeover_of_existing_connection_or_changed_project(setup):
    server, _, _, cloud, client = setup
    connect(client)
    original = cloud.config.read_bytes()
    for restart in [False, True]:
        with pytest.raises(CloudError, match="config_exists_use_status"): connect(client, restart=restart)
    assert server.starts == 1 and cloud.config.read_bytes() == original


def test_mismatched_approval_never_creates_configuration_or_enrolls(setup):
    server, _, _, cloud, client = setup
    server.approval_changes = {"site_id": "sit_" + "f" * 32}
    with pytest.raises(CloudError, match="approval_scope_mismatch"): connect(client)
    assert server.enrolled is None and not cloud.config.exists()


def test_redirect_does_not_forward_any_credential(setup):
    server, _, _, cloud, client = setup
    def redirect(request):
        server.calls.append(request)
        return httpx.Response(307, headers={"Location": "https://evil.example"})
    cloud.transport = httpx.MockTransport(redirect)
    with pytest.raises(CloudError, match="redirect_refused"): connect(client)
    assert len(server.calls) == 1
