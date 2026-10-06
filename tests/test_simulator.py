import concurrent.futures

import pytest

from vgpu_local.contracts.models import BackendRequest, BackendObservation
from vgpu_local.errors import KeyConflict, OutcomeUnknown
from vgpu_local.journal import Journal
from vgpu_local.simulator import Faults, Simulator, merge_observation


def test_lost_reply_recovers_original_after_restart(tmp_path, backend_request):
    path = tmp_path / "state.db"
    first = Simulator(Journal(path), Faults(lose_create_reply=True))
    with pytest.raises(OutcomeUnknown):
        first.provision(backend_request)
    second = Simulator(Journal(path))
    observed = second.observe(backend_request)
    assert second.provision(backend_request) == observed
    assert observed.revision == 1


def test_concurrent_creates_share_one_resource(tmp_path, backend_request):
    path = tmp_path / "state.db"
    Simulator(Journal(path))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: Simulator(Journal(path)).provision(backend_request), range(12)))
    assert len({result.resource_id for result in results}) == 1
    assert {result.revision for result in results} == {1}


def test_key_conflict_does_not_change_allocation(tmp_path, backend_request):
    fake = Simulator(Journal(tmp_path / "state.db"))
    original = fake.provision(backend_request)
    changed = BackendRequest.model_validate({**backend_request.model_dump(), "gpu_count": 2})
    with pytest.raises(KeyConflict):
        fake.provision(changed)
    assert fake.observe(backend_request) == original


@pytest.mark.parametrize("field", ["tenant_id", "project_id", "account_id", "operation_id", "generation"])
def test_scope_separation(tmp_path, backend_request, field):
    fake = Simulator(Journal(tmp_path / "state.db"))
    first = fake.provision(backend_request)
    value = 2 if field == "generation" else "another-owner"
    other = BackendRequest.model_validate({**backend_request.model_dump(), field: value})
    assert fake.provision(other).resource_id != first.resource_id
    with pytest.raises(ValueError):
        merge_observation(first, fake.observe(other))


@pytest.mark.parametrize("warning", [0, 60])
def test_preemption_ordering_and_duplicate_delivery(tmp_path, backend_request, warning):
    fake = Simulator(Journal(tmp_path / "state.db"))
    initial = fake.provision(backend_request)
    fake.preempt(backend_request, warning)
    if warning:
        fake.advance(backend_request, warning - 1)
        assert fake.observe(backend_request) == initial
        fake.advance(backend_request, 1)
    lost = fake.observe(backend_request)
    assert lost.state == "lost"
    assert merge_observation(lost, fake.observe(backend_request, stale=True)) == lost
    assert merge_observation(lost, lost) == lost
    events = fake.events(backend_request, duplicate=True)
    assert len(events) == 2 * len({event["id"] for event in events})


def test_failed_teardown_preserves_supplier_liability(tmp_path, backend_request):
    path = tmp_path / "state.db"
    fake = Simulator(Journal(path), Faults(fail_teardown=True))
    fake.provision(backend_request)
    with pytest.raises(OutcomeUnknown):
        fake.release(backend_request)
    assert fake.observe(backend_request).supplier_state == "allocated"
    recovered = Simulator(Journal(path))
    released = recovered.release(backend_request)
    assert released.state == released.supplier_state == "released"
    assert recovered.release(backend_request) == released
    resurrected = BackendObservation.model_validate({**released.model_dump(), "state": "running", "revision": 999})
    with pytest.raises(ValueError):
        merge_observation(released, resurrected)
