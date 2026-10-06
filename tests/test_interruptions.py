from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from vgpu_local.contracts.models import InterruptionRequest, InterruptionScope, InterruptionSourceNotice
from vgpu_local.errors import KeyConflict
from vgpu_local.interruptions import InterruptionConflict, InterruptionController
from vgpu_local.journal import Journal


@pytest.fixture
def runtime():
    return InterruptionScope(tenant_id="tenant-a", project_id="project-a", lease_id="lease-a", job_id="job-a",
        attempt_id="attempt-a", generation=1, controller_epoch=2, agent_session_id="igs_" + "a" * 32)


def source(**overrides):
    return InterruptionSourceNotice.model_validate(dict(source_id="site-owner", source_event_id="reclaim-1", source_revision=1,
        authority="local_owner", state="active", kind="preempt", reason="capacity_reclaim", observed_at_ms=1000,
        source_time_kind="vgpu_policy", source_action_at_ms=None, source_not_before_ms=None,
        release_by_ms=5000, signal_at_ms=4500, safety_margin_ms=0, clock_uncertainty_ms=0,
        mapping_policy="local.v1", notice_class="controlled", allowed_actions=["ack", "ready", "request_extension"],
        extension_limit_ms=9000) | overrides)


def request(notice, participant="rank-0", action="ack", **overrides):
    return InterruptionRequest.model_validate({key:getattr(notice,key) for key in InterruptionScope.model_fields} |
        dict(schema_version=1, request_id="irq_" + uuid4().hex, interruption_id=notice.interruption_id,
             interruption_version=notice.version, participant_id=participant, action=action,
             checkpoint_manifest=None, requested_release_by_ms=None) | overrides)


def controller(tmp_path, runtime, participants=None):
    return InterruptionController(Journal(tmp_path / "interruptions.db"), runtime, participants or ["rank-0"])


def test_ack_ready_release_and_billing_are_distinct(tmp_path, runtime):
    book = controller(tmp_path,runtime,["rank-0","rank-1"])
    notice = book.publish(source())
    ack = request(notice)
    receipt = book.respond(ack,participant_id="rank-0")
    assert receipt.status == "accepted"
    assert book.respond(ack,participant_id="rank-0") == receipt
    assert book.snapshot().interruptions[0].phase == "scheduled"
    for participant in ["rank-0", "rank-1"]:
        with pytest.raises(InterruptionConflict): book.authorize_release(notice.interruption_id,notice.version,2000)
        ready = request(notice,participant,"ready",checkpoint_manifest="manifest-untrusted")
        assert book.respond(ready,participant_id=participant).checkpoint_status == "unverified"
    releasing = book.authorize_release(notice.interruption_id,notice.version,2000)
    assert releasing.phase == "releasing"  # no process has been stopped by this controller
    assert book.authorize_release(notice.interruption_id,notice.version,2100) == releasing  # lost committed reply
    done = book.confirm_released(releasing.interruption_id,releasing.version,backend_evidence_id="verified-backend-observation")
    assert done.phase == "completed"
    assert book.confirm_released(releasing.interruption_id,releasing.version,backend_evidence_id="verified-backend-observation") == done
    assert book.respond(ack,participant_id="rank-0") == receipt  # exact historical outcome


def test_deadline_does_not_require_ack_and_unknown_time_never_invents_one(tmp_path, runtime):
    book = controller(tmp_path,runtime)
    notice = book.publish(source(release_by_ms=None,signal_at_ms=None,extension_limit_ms=None,allowed_actions=["ack","ready"]))
    with pytest.raises(InterruptionConflict): book.authorize_release(notice.interruption_id,1,900000)
    updated = book.publish(source(source_revision=2))
    with pytest.raises(InterruptionConflict): book.authorize_release(updated.interruption_id,updated.version,4499)
    assert book.authorize_release(updated.interruption_id,updated.version,4500).phase == "releasing"


def test_multiple_sources_withdrawal_and_late_cancellation(tmp_path, runtime):
    book = controller(tmp_path,runtime)
    first = book.publish(source())
    second = book.publish(source(source_id="supplier",source_event_id="spot",authority="provider",source_time_kind="action_at",
        source_action_at_ms=4000,release_by_ms=3900,signal_at_ms=3500,allowed_actions=["ack","ready"],extension_limit_ms=None))
    canceled = book.publish(source(source_revision=2,state="withdrawn"))
    assert canceled.phase == "canceled"
    assert len(book.snapshot().interruptions) == 2
    assert book.respond(request(first,action="ready"),participant_id="rank-0").code == "stale_notice"
    active = book.authorize_release(second.interruption_id,second.version,3500)
    withdrawal = second.source.model_copy(update={"state":"withdrawn","source_revision":2})
    late = book.publish(withdrawal)
    assert late.phase == "releasing" and late.version > active.version
    with pytest.raises(InterruptionConflict): book.publish(source(source_revision=3))


def test_source_deduplication_restart_and_event_replay(tmp_path, runtime):
    book = controller(tmp_path,runtime)
    first = book.publish(source())
    assert book.publish(source()) == first
    updated = book.publish(source(source_revision=3,release_by_ms=6000))
    assert book.publish(source(source_revision=2)) == updated
    with pytest.raises(KeyConflict): book.publish(source(source_revision=3,release_by_ms=7000))
    resumed = controller(tmp_path,runtime)
    assert resumed.snapshot() == book.snapshot()
    events = resumed.events()
    assert len(events) == 2 and len({event.id for _,event in events}) == 2
    assert resumed.events(events[0][0]) == events[1:]
    assert events[0][1].data == first
    assert events[1][1].data == updated


@pytest.mark.parametrize("changed", [{"tenant_id":"another"},{"attempt_id":"another"},{"controller_epoch":3},{"agent_session_id":"igs_"+"b"*32}])
def test_stale_or_foreign_workloads_cannot_respond(tmp_path, runtime, changed):
    book = controller(tmp_path,runtime)
    notice = book.publish(source())
    with pytest.raises(PermissionError): book.respond(request(notice,**changed),participant_id="rank-0")
    assert book.snapshot().cursor == 1


def test_authenticated_participant_and_payload_binding(tmp_path, runtime):
    book = controller(tmp_path,runtime,["rank-0","rank-1"])
    notice = book.publish(source())
    ack = request(notice)
    with pytest.raises(PermissionError): book.respond(ack,participant_id="rank-1")
    book.respond(ack,participant_id="rank-0")
    with pytest.raises(KeyConflict): book.respond(ack.model_copy(update={"action":"ready"}),participant_id="rank-0")
    invalid = request(notice,action="ack",checkpoint_manifest="wrong-action")
    assert book.respond(invalid,participant_id="rank-0").code == "invalid_action_payload"


def test_extension_is_explicit_and_another_source_can_prevent_it(tmp_path, runtime):
    book = controller(tmp_path,runtime)
    notice = book.publish(source())
    extend = request(notice,action="request_extension",requested_release_by_ms=8000)
    assert book.respond(extend,participant_id="rank-0").status == "accepted"
    assert book.snapshot().interruptions[0].release_by_ms == 5000
    other = source(source_event_id="other",release_by_ms=6000)
    book.publish(other)
    with pytest.raises(InterruptionConflict): book.grant_extension(extend.request_id,notice.version)
    book.publish(other.model_copy(update={"state":"withdrawn","source_revision":2}))
    granted = book.grant_extension(extend.request_id,notice.version)
    assert granted.release_by_ms == 8000 and granted.signal_at_ms == 7500
    assert granted.source.release_by_ms == 5000  # raw source timing remains distinguishable
    assert book.grant_extension(extend.request_id,notice.version) == granted
    assert book.respond(request(notice,action="ready"),participant_id="rank-0").code == "stale_notice"


def test_provider_cannot_claim_extension_and_advisory_cannot_become_reclaim(tmp_path, runtime):
    book = controller(tmp_path,runtime)
    with pytest.raises(ValueError): book.publish(source(authority="provider"))
    with pytest.raises(ValueError): book.publish(source(kind="advisory"))
    with pytest.raises(ValueError): book.publish(source(source_time_kind="not_before",source_action_at_ms=1000))
    advisory = book.publish(source(kind="advisory",allowed_actions=["ack"],extension_limit_ms=None,release_by_ms=None,signal_at_ms=None))
    assert book.respond(request(advisory,action="ready"),participant_id="rank-0").code == "action_not_allowed"
    with pytest.raises(InterruptionConflict): book.authorize_release(advisory.interruption_id,1,99999)


def test_cancel_and_release_are_serialized_and_never_report_both(tmp_path, runtime):
    book = controller(tmp_path,runtime)
    notice = book.publish(source())
    barrier = Barrier(2)
    def cancel():
        barrier.wait(5)
        return book.publish(source(source_revision=2,state="withdrawn")).phase
    def release():
        barrier.wait(5)
        try: return book.authorize_release(notice.interruption_id,1,5000).phase
        except InterruptionConflict: return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        canceled = pool.submit(cancel)
        released = pool.submit(release)
        outcomes = canceled.result(),released.result()
    assert outcomes in {("canceled","conflict"),("releasing","releasing")}


def test_all_participants_must_belong_to_same_notice_version(tmp_path, runtime):
    book = controller(tmp_path,runtime,["rank-0","rank-1"])
    first = book.publish(source())
    book.respond(request(first,"rank-0","ready"),participant_id="rank-0")
    revised = book.publish(source(source_revision=2,release_by_ms=6000))
    book.respond(request(revised,"rank-1","ready"),participant_id="rank-1")
    with pytest.raises(InterruptionConflict): book.authorize_release(revised.interruption_id,revised.version,2000)
    book.respond(request(revised,"rank-0","ready"),participant_id="rank-0")
    assert book.authorize_release(revised.interruption_id,revised.version,2000).phase == "releasing"


def test_one_confirmed_allocation_release_closes_all_its_notices(tmp_path, runtime):
    book = controller(tmp_path,runtime)
    notice = book.publish(source())
    book.publish(source(source_event_id="second-warning"))
    releasing = book.authorize_release(notice.interruption_id,1,4500)
    book.confirm_released(releasing.interruption_id,releasing.version,backend_evidence_id="release-proof")
    assert all(item.phase == "completed" for item in book.snapshot().interruptions)
    late = book.publish(source(source_event_id="delayed-warning"))
    assert late.phase == "completed"
    assert book.respond(request(late,action="ready"),participant_id="rank-0").code == "notice_not_scheduled"


def test_unknown_or_earlier_stop_constraint_blocks_extension(tmp_path, runtime):
    book = controller(tmp_path,runtime)
    notice = book.publish(source())
    extend = request(notice,action="request_extension",requested_release_by_ms=8000)
    book.respond(extend,participant_id="rank-0")
    other = source(source_event_id="uncertain",release_by_ms=None,signal_at_ms=None,extension_limit_ms=None,allowed_actions=["ack"])
    book.publish(other)
    with pytest.raises(InterruptionConflict): book.grant_extension(extend.request_id,notice.version)
    book.publish(other.model_copy(update={"source_revision":2,"release_by_ms":9000,"signal_at_ms":4000}))
    with pytest.raises(InterruptionConflict): book.grant_extension(extend.request_id,notice.version)
