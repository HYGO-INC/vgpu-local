import json

import httpx
import pytest

from vgpu_local.cloud import CloudConnection, CloudError
from test_cloud import Secrets, connected


def setup_connection(tmp_path, *, lose_commit=False, lose_before=False, mismatched_reply=False):
    store = Secrets()
    record = {}
    rotations = []
    calls = []
    def server(request):
        nonlocal lose_commit, lose_before
        calls.append(request)
        if request.url.path.endswith('/sites'):
            record.update(json.loads(request.content))
            return httpx.Response(201, json=connected(record))
        if request.url.path.endswith('/renew'):
            body = json.loads(request.content)
            state = json.loads(next(iter(store.values.values())))
            assert state['pending'] == body  # durable OS entry exists BEFORE request
            rotations.append((request.headers['authorization'], body))
            if lose_before:
                lose_before = False
                raise httpx.ConnectTimeout('private transport detail')
            record['credential'] = body['credential']
            if lose_commit:
                lose_commit = False
                raise httpx.ReadTimeout('private transport detail')
            return httpx.Response(200, json={**connected(record), 'rotation_id':
                'rot_' + 'f' * 32 if mismatched_reply else body['rotation_id']})
        if request.headers['authorization'] != 'Bearer ' + record['credential']:
            return httpx.Response(401, json={'error': 'unauthorized'})
        result = connected(record)
        if request.url.path.endswith('/revoke'): result['state'] = 'revoked'
        return httpx.Response(200, json=result)
    transport = httpx.MockTransport(server)
    def client(config=None):
        return CloudConnection(config or tmp_path / 'cloud.json', store, transport=transport, lock_dir=tmp_path / 'locks')
    client().connect(endpoint='https://cloud.example', tenant_id='ten_example0', project_id='prj_example0',
                     name='Office', user_access_token='user-token')
    return client, store, record, rotations, calls


def test_lost_rotation_reply_replays_same_identity_and_discards_old_secret_only_after_ack(tmp_path):
    client, store, record, rotations, _ = setup_connection(tmp_path, lose_commit=True)
    old = record['credential']
    metadata = (tmp_path / 'cloud.json').read_bytes()
    with pytest.raises(CloudError, match='outcome_unknown'): client().renew()
    state = json.loads(next(iter(store.values.values())))
    assert state['active'] == old and state['pending']['credential'] == record['credential']
    result = client().renew()  # new process/object, recovered solely from OS store
    assert rotations[0] == rotations[1]
    assert rotations[0][0] == 'Bearer ' + old
    assert result['rotation_id'] == state['pending']['rotation_id']
    assert next(iter(store.values.values())) == record['credential'] != old
    assert (tmp_path / 'cloud.json').read_bytes() == metadata
    assert old not in metadata.decode() and record['credential'] not in metadata.decode()


def test_status_promotes_new_credential_after_a_lost_committed_reply(tmp_path):
    client, store, record, rotations, _ = setup_connection(tmp_path, lose_commit=True)
    with pytest.raises(CloudError): client().renew()
    assert client().status()['state'] == 'active'
    assert len(rotations) == 1  # read-only status never issues a new renewal
    assert next(iter(store.values.values())) == record['credential']


def test_status_and_disconnect_work_when_rotation_was_never_received(tmp_path):
    client, store, record, rotations, _ = setup_connection(tmp_path, lose_before=True)
    old = record['credential']
    with pytest.raises(CloudError): client().renew()
    assert client().status()['state'] == 'active'
    assert json.loads(next(iter(store.values.values())))['active'] == old
    assert client().disconnect()['state'] == 'revoked'
    assert len(rotations) == 1


def test_mismatched_rotation_ack_cannot_discard_recovery_keys(tmp_path):
    client, store, record, _, _ = setup_connection(tmp_path, mismatched_reply=True)
    old = record['credential']
    with pytest.raises(CloudError, match='rotation_response_mismatch'): client().renew()
    assert json.loads(next(iter(store.values.values())))['active'] == old
    assert client().status()['state'] == 'active'  # independent proof through the new credential


def test_rotating_config_origin_cannot_exfiltrate_pending_credentials(tmp_path):
    client, _, _, _, calls = setup_connection(tmp_path, lose_commit=True)
    with pytest.raises(CloudError): client().renew()
    before = len(calls)
    path = tmp_path / 'cloud.json'
    settings = json.loads(path.read_text()); settings['endpoint'] = 'https://attacker.example'
    path.write_text(json.dumps(settings))
    with pytest.raises(CloudError, match='site_credential_unavailable'): client().renew()
    assert len(calls) == before


def test_copied_connection_configs_share_one_renewal_lock(tmp_path):
    client, _, _, _, _ = setup_connection(tmp_path)
    original = client()
    copied = tmp_path / 'copy.json'
    copied.write_bytes(original.config.read_bytes())
    with original._lock(original._settings()):
        with pytest.raises(CloudError, match='already_running'): client(copied).renew()
    assert client(copied).renew()['state'] == 'active'


def test_os_store_failure_after_server_ack_retains_recoverable_pending_state(tmp_path):
    client, store, record, _, _ = setup_connection(tmp_path)
    original_set = store.set
    def fail_promotion(name, value):
        if value.startswith('vgs_'): raise CloudError('os_credential_store_unavailable')
        original_set(name, value)
    store.set = fail_promotion
    with pytest.raises(CloudError, match='os_credential_store'): client().renew()
    assert json.loads(next(iter(store.values.values())))['pending']['credential'] == record['credential']
    store.set = original_set
    assert client().status()['state'] == 'active'
    assert next(iter(store.values.values())) == record['credential']
