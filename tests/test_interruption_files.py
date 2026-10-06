import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest

from vgpu_local.contracts.models import InterruptionRequest, InterruptionScope, InterruptionSourceNotice
from vgpu_local.errors import KeyConflict
from vgpu_local.interruption_files import InterruptionFiles, MESSAGE_LIMIT
from vgpu_local.interruptions import InterruptionController
from vgpu_local.journal import Journal

pytestmark = pytest.mark.skipif(sys.platform != "linux",reason="Linux descriptor and O_NOFOLLOW transport; run on Linux/WSL")


@pytest.fixture
def exchange(tmp_path):
    scope = InterruptionScope(tenant_id="tenant-a",project_id="project-a",lease_id="lease-a",job_id="job-a",attempt_id="attempt-a",
        generation=1,controller_epoch=1,agent_session_id="igs_"+"a"*32)
    book = InterruptionController(Journal(tmp_path/"control.db"),scope,["coordinator"])
    notice = book.publish(InterruptionSourceNotice(source_id="site",source_event_id="event",source_revision=1,authority="local_owner",
        state="active",kind="preempt",reason="capacity_reclaim",observed_at_ms=1000,source_time_kind="vgpu_policy",
        source_action_at_ms=None,source_not_before_ms=None,release_by_ms=5000,signal_at_ms=4500,safety_margin_ms=0,
        clock_uncertainty_ms=0,mapping_policy="local.v1",notice_class="controlled",allowed_actions=["ack","ready"],extension_limit_ms=None))
    request = InterruptionRequest(**scope.model_dump(),schema_version=1,request_id="irq_"+uuid4().hex,
        interruption_id=notice.interruption_id,interruption_version=notice.version,participant_id="coordinator",action="ack",
        checkpoint_manifest=None,requested_release_by_ms=None)
    root = tmp_path/"runtime"
    with InterruptionFiles(root,scope,"coordinator",create=True) as files:
        files.publish(book.snapshot())
        yield book,files,request,root


def test_file_request_needs_correlated_durable_receipt(exchange):
    book,files,request,root = exchange
    assert files.snapshot() == book.snapshot()
    files.submit(request)
    files.submit(request)
    assert files.receipt(request) is None
    assert files.forward(book) == {"processed":1,"invalid":0}
    receipt = files.receipt(request)
    assert receipt.status == "accepted" and not (root/"requests"/(request.request_id+".json")).exists()
    assert book.snapshot().interruptions[0].phase == "scheduled"
    files.submit(request)  # retried after the receipt was lost to the caller
    files.forward(book)
    assert files.receipt(request) == receipt
    with pytest.raises(ValueError): files.receipt(request.model_copy(update={"action":"ready"}))


def test_snapshot_atomic_replace_and_cursor_reuse_detection(exchange):
    book,files,request,root = exchange
    initial = files.snapshot()
    book.respond(request,participant_id="coordinator")
    files.publish(book.snapshot())
    assert files.snapshot().cursor > initial.cursor
    files.publish(initial)
    with pytest.raises(ValueError): files.snapshot()
    assert not list(root.glob("*.tmp"))


def test_controller_failure_keeps_request_and_never_forges_a_receipt(exchange,monkeypatch):
    book,files,request,root = exchange
    files.submit(request)
    def failed(*args,**kwargs): raise RuntimeError("controller unavailable")
    monkeypatch.setattr(book,"respond",failed)
    with pytest.raises(RuntimeError): files.forward(book)
    assert files.receipt(request) is None
    assert (root/"requests"/(request.request_id+".json")).exists()


@pytest.mark.parametrize("malicious",["symlink","fifo","directory","oversized","other_scope","name_mismatch"])
def test_untrusted_request_files_never_gain_authority(exchange,tmp_path,malicious):
    book,files,request,root = exchange
    path = root/"requests"/(request.request_id+".json")
    outside = tmp_path/"outside.json"
    original = request.model_dump_json()
    outside.write_text(original)
    if malicious == "symlink": path.symlink_to(outside)
    elif malicious == "fifo": os.mkfifo(path)
    elif malicious == "directory": path.mkdir()
    elif malicious == "oversized": path.write_bytes(b" "*(MESSAGE_LIMIT+1))
    elif malicious == "other_scope": path.write_text(request.model_copy(update={"agent_session_id":"igs_"+"b"*32}).model_dump_json())
    else: path.write_text(request.model_copy(update={"request_id":"irq_"+"c"*32}).model_dump_json())
    assert files.forward(book) == {"processed":0,"invalid":1}
    assert book.snapshot().cursor == 1 and files.receipt(request) is None
    assert outside.read_text() == original


def test_parent_directories_are_pinned_and_symlink_directories_rejected(exchange,tmp_path):
    book,files,request,root = exchange
    original = root/"requests"
    original.rename(root/"original-requests")
    outside = tmp_path/"outside"
    outside.mkdir()
    original.symlink_to(outside,target_is_directory=True)
    files.submit(request)  # descriptor still refers to the original directory
    assert list(outside.iterdir()) == []
    assert (root/"original-requests"/(request.request_id+".json")).exists()
    with pytest.raises(OSError): InterruptionFiles(root,book.scope,"coordinator")


def test_existing_request_cannot_be_overwritten_with_changed_intent(exchange):
    book,files,request,root = exchange
    files.submit(request)
    with pytest.raises(KeyConflict): files.submit(request.model_copy(update={"action":"ready"}))
    files.forward(book)
    assert files.receipt(request).action == "ack"


def test_foreign_snapshot_rejected_before_any_workload_action(exchange):
    book,files,request,root = exchange
    snapshot = book.snapshot().model_dump()
    snapshot["interruptions"][0]["tenant_id"] = "another-tenant"
    (root/"state.json").write_text(json.dumps(snapshot))
    with pytest.raises(PermissionError): files.snapshot()


def test_lost_receipt_write_recovers_original_committed_response(exchange,monkeypatch):
    book,files,request,root = exchange
    files.submit(request)
    write = files._write
    failed = False
    def lose_receipt(directory,*args,**kwargs):
        nonlocal failed
        if directory == files.receipts and not failed:
            failed = True
            raise OSError("receipt volume unavailable after database commit")
        return write(directory,*args,**kwargs)
    monkeypatch.setattr(files,"_write",lose_receipt)
    with pytest.raises(OSError): files.forward(book)
    committed = book.snapshot().cursor
    assert files.receipt(request) is None
    files.forward(book)
    assert files.receipt(request).cursor == committed
    assert book.snapshot().cursor == committed


@pytest.mark.parametrize("content",['{"action":"ack","action":"ready"}','['*2000+']'*2000,'{"version":NaN}'])
def test_ambiguous_or_excessively_nested_json_is_rejected(exchange,content):
    book,files,request,root = exchange
    (root/"requests"/(request.request_id+".json")).write_text(content)
    assert files.forward(book) == {"processed":0,"invalid":1}
    assert book.snapshot().cursor == 1
