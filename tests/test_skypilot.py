from unittest.mock import MagicMock
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from vgpu_local.contracts.models import BackendRequest
from vgpu_local.errors import OutcomeUnknown, UnsupportedCapability
from vgpu_local.journal import Journal
from vgpu_local.skypilot_backend import SkyPilotBackend, task_config


@pytest.mark.parametrize("provider", ["vast", "runpod"])
def test_provider_and_create_boundaries(tmp_path, request_data, provider):
    request = BackendRequest.model_validate({**request_data, "provider": provider, "capacity_mode": "spot",
                                           "command": ["python", "-c", "print('a b')"]})
    sdk = MagicMock()
    sdk.launch.return_value = "request-create"
    sdk.down.return_value = "request-delete"
    backend = SkyPilotBackend(Journal(tmp_path / "ops.db"), sdk)
    config = task_config(request)
    assert config["resources"]["cloud"] == provider
    assert config["resources"]["max_hourly_cost"] == .5
    assert config["resources"]["use_spot"] is True
    assert "file_mounts" not in config and "envs" not in config and "workdir" not in config
    first = backend.provision(request)
    assert backend.provision(request) == first
    assert sdk.launch.call_count == 1
    assert sdk.launch.call_args.kwargs["retry_until_up"] is False
    released = backend.release(request)
    assert released["state"] == "released"
    assert sdk.down.call_args.kwargs["purge"] is False
    backend.release(request)
    assert sdk.down.call_count == 1


def test_uncertain_launch_never_blindly_retries(tmp_path, request_data):
    request = BackendRequest.model_validate({**request_data, "provider": "runpod"})
    sdk = MagicMock()
    sdk.launch.return_value = "accepted-id"
    sdk.get.side_effect = TimeoutError()
    path = tmp_path / "ops.db"
    with pytest.raises(OutcomeUnknown):
        SkyPilotBackend(Journal(path), sdk).provision(request)
    restarted = SkyPilotBackend(Journal(path), sdk)
    with pytest.raises(OutcomeUnknown):
        restarted.provision(request)
    assert sdk.launch.call_count == 1
    sdk.get.side_effect = None
    assert restarted.reconcile(request)["state"] == "ready"
    assert sdk.get.call_args.args == ("accepted-id",)


def test_lost_sdk_submission_reply_requires_inventory(tmp_path, request_data):
    request = BackendRequest.model_validate({**request_data, "provider": "vast"})
    sdk = MagicMock()
    sdk.launch.side_effect = TimeoutError()
    backend = SkyPilotBackend(Journal(tmp_path / "ops.db"), sdk)
    with pytest.raises(OutcomeUnknown):
        backend.provision(request)
    with pytest.raises(OutcomeUnknown):
        backend.reconcile(request)
    assert sdk.launch.call_count == 1


def test_unknown_cleanup_is_not_reported_released(tmp_path, request_data):
    request = BackendRequest.model_validate({**request_data, "provider": "vast"})
    sdk = MagicMock()
    sdk.launch.return_value = "create"
    sdk.down.return_value = "delete"
    backend = SkyPilotBackend(Journal(tmp_path / "ops.db"), sdk)
    backend.provision(request)
    sdk.get.side_effect = TimeoutError()
    with pytest.raises(OutcomeUnknown):
        backend.release(request)
    with pytest.raises(OutcomeUnknown):
        backend.reconcile_release(request)
    sdk.get.side_effect = None
    assert backend.reconcile_release(request)["state"] == "released"
    assert sdk.down.call_count == 1


@pytest.mark.parametrize("override", [{"workload_trust": "untrusted"}, {"num_nodes": 2}, {"provider": "theta"}])
def test_unqualified_execution_rejected(request_data, override):
    request = BackendRequest.model_validate({**request_data, "provider": "vast", **override})
    with pytest.raises(UnsupportedCapability):
        task_config(request)


def test_concurrent_release_has_one_owner(tmp_path, request_data):
    request = BackendRequest.model_validate({**request_data, "provider": "vast"})
    sdk = MagicMock()
    sdk.launch.return_value = "create"
    sdk.down.return_value = "delete"
    backend = SkyPilotBackend(Journal(tmp_path / "ops.db"), sdk)
    backend.provision(request)
    read = backend._owned
    barrier = Barrier(2)
    def synchronized_read(value):
        receipt = read(value)
        barrier.wait(timeout=5)
        return receipt
    backend._owned = synchronized_read
    def release():
        try:
            return backend.release(request)["state"]
        except OutcomeUnknown:
            return "pending"
    with ThreadPoolExecutor(max_workers=2) as pool:
        states = list(pool.map(lambda _: release(), range(2)))
    assert "released" in states
    assert sdk.down.call_count == 1
