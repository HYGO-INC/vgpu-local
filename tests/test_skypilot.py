from unittest.mock import MagicMock
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest

from vgpu_local.contracts.models import BackendRequest
from vgpu_local.errors import OutcomeUnknown, UnsupportedCapability
from vgpu_local.journal import Journal
from vgpu_local.skypilot_backend import SkyPilotBackend, task_config


def workload_backend(tmp_path, request_data):
    request = BackendRequest.model_validate({**request_data,"provider":"vast"})
    sdk = MagicMock()
    sdk.launch.return_value, sdk.down.return_value = "create", "delete"
    sdk.status.return_value, sdk.job_status.return_value = "cluster", "job"
    current = {"state":"RUNNING"}
    backend = SkyPilotBackend(Journal(tmp_path/"jobs.db"),sdk)
    def result(ticket):
        if ticket == "create": return 17, object()
        if ticket == "cluster": return [{"name":backend._owned(request)["cluster_name"],"status":"UP"}]
        if ticket == "job": return {17:current["state"]}
        if ticket == "delete": return None
        raise AssertionError(ticket)
    sdk.get.side_effect = result
    backend.provision(request)
    return request,sdk,current,backend


@pytest.mark.parametrize("status,normalized", [("SUCCEEDED","succeeded"),("FAILED","failed"),("CANCELLED","canceled"),("FAILED_DRIVER","failed"),("FAILED_SETUP","failed")])
def test_identified_job_completion_never_means_supplier_release(tmp_path,request_data,status,normalized):
    request,sdk,current,backend = workload_backend(tmp_path,request_data)
    running = backend.observe(request)
    assert running.workload.model_dump() == {"job_id":"17","state":"running"}
    sdk.job_status.assert_called_with(backend._owned(request)["cluster_name"],job_ids=[17])
    current["state"] = status
    completed = backend.observe(request)
    assert completed.workload.state == normalized
    assert completed.supplier_state == "allocated" and completed.state == "running"
    assert completed.revision > running.revision
    current["state"] = "RUNNING"  # a late or lost status cannot resurrect finished work
    assert backend.observe(request).workload == completed.workload
    backend.release(request)
    released = backend.observe(request)
    assert released.state == released.supplier_state == "released"
    assert released.workload == completed.workload


def test_absent_or_foreign_job_result_cannot_finish_a_workload(tmp_path,request_data):
    request,sdk,current,backend = workload_backend(tmp_path,request_data)
    current["state"] = None
    assert backend.observe(request).workload.state == "unknown"
    original = sdk.get.side_effect
    sdk.get.side_effect = lambda ticket: {18:"SUCCEEDED"} if ticket == "job" else original(ticket)
    with pytest.raises(OutcomeUnknown): backend.observe(request)
    assert backend._owned(request)["observation"]["workload"]["state"] == "unknown"
    sdk.down.assert_not_called()


@pytest.mark.parametrize("result", [None,{},(True,None),(0,None),("17",None),(17,)])
def test_malformed_launch_result_stays_uncertain(tmp_path,request_data,result):
    request = BackendRequest.model_validate({**request_data,"provider":"vast"})
    sdk = MagicMock(); sdk.launch.return_value = "create"; sdk.get.return_value = result
    backend = SkyPilotBackend(Journal(tmp_path/"malformed.db"),sdk)
    with pytest.raises(OutcomeUnknown): backend.provision(request)
    with pytest.raises(OutcomeUnknown): backend.provision(request)
    assert backend._owned(request)["state"] == "uncertain"
    assert sdk.launch.call_count == 1


@pytest.mark.parametrize("provider", ["vast", "runpod"])
def test_provider_and_create_boundaries(tmp_path, request_data, provider):
    request = BackendRequest.model_validate({**request_data, "provider": provider, "capacity_mode": "spot",
                                           "command": ["python", "-c", "print('a b')"]})
    sdk = MagicMock()
    sdk.get.return_value = (None, None)
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
    sdk.get.return_value = (None, None)
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
    sdk.get.return_value = (None, None)
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
    sdk.get.return_value = (None, None)
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
    sdk.get.return_value = (None, None)
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


def ready_backend(tmp_path, request_data):
    request = BackendRequest.model_validate({**request_data, "provider": "vast"})
    sdk = MagicMock()
    sdk.get.return_value = (None, None)
    sdk.launch.return_value = "create"
    sdk.down.return_value = "delete"
    sdk.status.return_value = "status"
    backend = SkyPilotBackend(Journal(tmp_path / "ops.db"), sdk, account_id=request.account_id)
    receipt = backend.provision(request)
    return request, sdk, backend, receipt


def test_fresh_status_normalization_never_uses_launch_success_as_live_health(tmp_path, request_data):
    request, sdk, backend, receipt = ready_backend(tmp_path, request_data)
    sdk.get.return_value = [{"name": receipt["cluster_name"], "status": "UP"}]
    first = backend.observe(request)
    assert first.state == "running" and first.supplier_state == "allocated"
    assert backend.observe(request) == first
    sdk.status.assert_called_with(cluster_names=[receipt["cluster_name"]], refresh="FORCE", all_users=False,
                                  _include_credentials=False)
    sdk.get.return_value[0]["status"] = "STOPPED"
    paused = backend.observe(request)
    assert paused.state == "paused" and paused.supplier_state == "allocated" and paused.revision > first.revision
    sdk.get.return_value = []
    unknown = backend.observe(request)
    assert unknown.state == unknown.supplier_state == "unknown"
    assert unknown.revision > paused.revision
    backend.provision(request)
    assert sdk.launch.call_count == 1  # missing inventory is never permission to rent again


@pytest.mark.parametrize("records", [[{"name": "another-customer", "status": "UP"}], {}, [1], [{"name": "missing", "status": "UP"}] * 2])
def test_unverified_status_cannot_claim_capacity_or_release(tmp_path, request_data, records):
    request, sdk, backend, _ = ready_backend(tmp_path, request_data)
    sdk.get.return_value = records
    with pytest.raises(OutcomeUnknown): backend.observe(request)
    sdk.down.assert_not_called()
    assert backend._owned(request)["observation"]["state"] == "unknown"


def test_late_status_reply_cannot_overwrite_a_newer_observation(tmp_path, request_data):
    request, sdk, backend, receipt = ready_backend(tmp_path, request_data)
    entered, resume = Event(), Event()
    sdk.status.side_effect = ["slow", "new"]
    def get(request_id):
        if request_id == "slow":
            entered.set()
            assert resume.wait(5)
            return [{"name": receipt["cluster_name"], "status": "UP"}]
        return [{"name": receipt["cluster_name"], "status": "STOPPED"}]
    sdk.get.side_effect = get
    with ThreadPoolExecutor(max_workers=1) as pool:
        slow = pool.submit(backend.observe, request)
        assert entered.wait(5)
        try: newer = backend.observe(request)
        finally: resume.set()
        assert slow.result() == newer
    assert newer.state == "paused"


def test_confirmed_teardown_dominates_an_inflight_status_reply(tmp_path, request_data):
    request, sdk, backend, receipt = ready_backend(tmp_path, request_data)
    entered, resume = Event(), Event()
    def get(request_id):
        if request_id == "status":
            entered.set()
            assert resume.wait(5)
            return [{"name": receipt["cluster_name"], "status": "UP"}]
    sdk.get.side_effect = get
    with ThreadPoolExecutor(max_workers=1) as pool:
        slow = pool.submit(backend.observe, request)
        assert entered.wait(5)
        try: backend.release(request)
        finally: resume.set()
        final = slow.result()
    assert final.state == final.supplier_state == "released"
    assert backend.observe(request) == final
    assert sdk.status.call_count == 1


def test_account_worker_binding_rejects_other_accounts_before_any_provider_call(tmp_path, request_data):
    request = BackendRequest.model_validate({**request_data, "provider": "runpod"})
    sdk = MagicMock()
    sdk.get.return_value = (None, None)
    backend = SkyPilotBackend(Journal(tmp_path / "ops.db"), sdk, account_id="another-account")
    with pytest.raises(UnsupportedCapability): backend.provision(request)
    with pytest.raises(UnsupportedCapability): backend.observe(request)
    sdk.launch.assert_not_called(); sdk.status.assert_not_called()


def test_newer_failed_poll_prevents_old_healthy_reply_from_restoring_health(tmp_path, request_data):
    request, sdk, backend, receipt = ready_backend(tmp_path, request_data)
    entered, resume = Event(), Event()
    sdk.status.side_effect = ["slow", "failed"]
    def get(request_id):
        if request_id == "failed": raise TimeoutError()
        entered.set()
        assert resume.wait(5)
        return [{"name": receipt["cluster_name"], "status": "UP"}]
    sdk.get.side_effect = get
    with ThreadPoolExecutor(max_workers=1) as pool:
        slow = pool.submit(backend.observe, request)
        assert entered.wait(5)
        try:
            with pytest.raises(OutcomeUnknown): backend.observe(request)
        finally: resume.set()
        assert slow.result().state == "unknown"
    assert backend._owned(request)["observation"]["supplier_state"] == "unknown"
