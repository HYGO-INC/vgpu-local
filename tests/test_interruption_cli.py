import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from filelock import FileLock
import pytest

from vgpu_local.interruption_cli import configuration, document, relay
from vgpu_local.contracts.models import InterruptionRequest, InterruptionScope, InterruptionSourceNotice


def setup(tmp_path):
    scope = InterruptionScope(tenant_id='tenant-a', project_id='project-a', lease_id='lease-a', job_id='job-a',
        attempt_id='attempt-a', generation=1, controller_epoch=1, agent_session_id='igs_'+'a'*32)
    config = tmp_path/'operator.json'
    config.write_text(json.dumps({'version':1,'scope':scope.model_dump(),'journal':'operator.db',
        'participants':[{'id':'rank-0','mailbox':'rank-0'},{'id':'rank-1','mailbox':'rank-1'}]}))
    scope_path = tmp_path/'scope.json'
    scope_path.write_text(scope.model_dump_json())
    notice = InterruptionSourceNotice(source_id='owner', source_event_id='test-event', source_revision=1, authority='local_owner',
        state='active', kind='preempt', reason='capacity_reclaim', observed_at_ms=1000, source_time_kind='vgpu_policy',
        source_action_at_ms=None, source_not_before_ms=None, release_by_ms=5000, signal_at_ms=4500, safety_margin_ms=0,
        clock_uncertainty_ms=0, mapping_policy='local.v1', notice_class='controlled', allowed_actions=['ack','ready'], extension_limit_ms=None)
    notice_path = tmp_path/'notice.json'
    notice_path.write_text(notice.model_dump_json())
    return scope, config, scope_path, notice_path


def command(*args):
    result = subprocess.run(['vgpu-local','interruption',*map(str,args)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_operator_configuration_rejects_overlapping_mailboxes_and_exposed_journal(tmp_path):
    scope, config, _, _ = setup(tmp_path)
    read_scope, journal, paths = configuration(config)
    assert read_scope == scope and journal == tmp_path/'operator.db'
    assert set(paths) == {'rank-0','rank-1'}
    original = json.loads(config.read_text())
    for path in ['rank-0','rank-0/child','.']:
        changed = json.loads(json.dumps(original))
        changed['participants'][1]['mailbox'] = path
        config.write_text(json.dumps(changed))
        with pytest.raises(ValueError): configuration(config)
    original['journal'] = 'rank-0/operator.db'
    config.write_text(json.dumps(original))
    with pytest.raises(ValueError): configuration(config)


def test_cli_rejects_duplicate_json_keys_and_oversized_input(tmp_path):
    source = tmp_path/'input.json'
    for content in ['{"action":"ack","action":"ready"}', '{"version":NaN}', ' '*65537, '['*2000+']'*2000]:
        source.write_text(content)
        with pytest.raises(ValueError): document(source)


@pytest.mark.skipif(sys.platform != 'linux', reason='Real Linux descriptor transport')
def test_cli_relays_acknowledgements_across_process_restarts_without_reclaiming(tmp_path):
    scope, config, scope_path, notice_path = setup(tmp_path)
    notice = command('publish','--config',config,'--notice',notice_path)
    initial = command('relay','--config',config,'--initialize','--once')
    assert initial['cursor'] == 1
    snapshot = command('snapshot','--mailbox',tmp_path/'rank-0','--scope',scope_path,'--participant','rank-0')
    assert snapshot['interruptions'] == [notice]
    request = InterruptionRequest(**scope.model_dump(), schema_version=1, request_id='irq_'+uuid4().hex,
        interruption_id=notice['interruption_id'], interruption_version=notice['version'], participant_id='rank-0',
        action='ready', checkpoint_manifest='checkpoint-example', requested_release_by_ms=None)
    request_path = tmp_path/'response.json'
    request_path.write_text(request.model_dump_json())
    assert command('submit','--mailbox',tmp_path/'rank-0','--request',request_path)['status'] == 'receipt_pending'
    forwarded = command('relay','--config',config,'--once')
    assert forwarded['participants']['rank-0'] == {'processed':1,'invalid':0}
    receipt = command('receipt','--mailbox',tmp_path/'rank-0','--request',request_path)
    assert receipt['status'] == 'accepted' and receipt['checkpoint_status'] == 'unverified'
    command('submit','--mailbox',tmp_path/'rank-0','--request',request_path)
    replayed = command('relay','--config',config,'--once')
    assert replayed['cursor'] == forwarded['cursor']
    assert command('receipt','--mailbox',tmp_path/'rank-0','--request',request_path) == receipt
    assert command('snapshot','--mailbox',tmp_path/'rank-1','--scope',scope_path,'--participant','rank-1')['interruptions'][0]['phase'] == 'scheduled'


@pytest.mark.skipif(sys.platform != 'linux', reason='Real Linux descriptor transport')
def test_cli_binds_participants_and_refuses_a_second_file_publisher(tmp_path):
    scope, config, _, notice_path = setup(tmp_path)
    notice = command('publish','--config',config,'--notice',notice_path)
    command('relay','--config',config,'--initialize','--once')
    request = InterruptionRequest(**scope.model_dump(), schema_version=1, request_id='irq_'+uuid4().hex,
        interruption_id=notice['interruption_id'], interruption_version=notice['version'], participant_id='rank-1',
        action='ready', checkpoint_manifest=None, requested_release_by_ms=None)
    path = tmp_path/'forged.json'
    path.write_text(request.model_dump_json())
    command('submit','--mailbox',tmp_path/'rank-0','--request',path)
    assert command('relay','--config',config,'--once')['participants']['rank-0'] == {'processed':0,'invalid':1}
    assert command('receipt','--mailbox',tmp_path/'rank-0','--request',path)['status'] == 'receipt_pending'
    with FileLock(str(tmp_path/'operator.db')+'.relay.lock'):
        with pytest.raises(RuntimeError, match='Another relay'): relay(config, once=True)


@pytest.mark.skipif(sys.platform != 'linux', reason='Real Linux descriptor transport')
def test_relay_does_not_replace_a_published_snapshot_after_journal_loss(tmp_path):
    _, config, _, notice = setup(tmp_path)
    command('publish','--config',config,'--notice',notice)
    command('relay','--config',config,'--initialize','--once')
    saved = (tmp_path/'rank-0'/'state.json').read_bytes()
    changed = json.loads(config.read_text())
    changed['journal'] = 'missing.db'
    config.write_text(json.dumps(changed))
    with pytest.raises(RuntimeError, match='behind'): relay(config, once=True)
    assert (tmp_path/'rank-0'/'state.json').read_bytes() == saved
