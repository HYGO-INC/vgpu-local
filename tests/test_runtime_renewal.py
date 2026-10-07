"""Unattended key maintenance must preserve identity, local work and recovery."""
import asyncio
import json
import threading

import pytest

from vgpu_local.cloud import CloudError
from vgpu_local.comfyui import ComfyEngine
from vgpu_local.runtime import Runtime
from vgpu_local.runtime_store import RuntimeStore
from runtime_fixture import EngineFixture, setup
from test_cloud_renewal import setup_connection
from test_runtime import command


class Clock:
    wall = 1800000000
    steady = 1


def make_runtime(tmp_path, client, clock, *, store=None, engine=None):
    identity = {k: client().settings()[k] for k in ('endpoint', 'tenant_id', 'project_id', 'site_id')}
    return Runtime(store or RuntimeStore(tmp_path / 'jobs.sqlite3', create=True), engine,
                   cloud=client(), cloud_identity=identity,
                   wall_clock=lambda: clock.wall, monotonic=lambda: clock.steady)


def test_automatic_rotation_runs_at_startup_and_checks_hourly_without_rotating_every_poll(tmp_path):
    client, secrets, record, rotations, calls = setup_connection(tmp_path)
    clock = Clock()
    record['expires_at'] = clock.wall + 90000  # just outside the renewal window
    runtime = make_runtime(tmp_path, client, clock)
    metadata = client().config.read_bytes()
    original = record['credential']
    runtime.exchange()
    clock.wall += 7200
    runtime.exchange()  # wall-clock change alone does not cause another check
    assert not rotations
    clock.steady += 3600
    runtime.exchange()
    assert len(rotations) == 1 and record['credential'] != original
    runtime.exchange(); runtime.exchange()
    assert sum(r.method == 'GET' for r in calls) == 2
    assert len(rotations) == 1
    assert next(iter(secrets.values.values())) == record['credential']
    assert client().config.read_bytes() == metadata
    # Restart promptly verifies server state; it does not renew an already fresh key.
    make_runtime(tmp_path, client, clock).exchange()
    assert len(rotations) == 1


@pytest.mark.parametrize('loss', ['lose_commit', 'lose_before'])
def test_restart_recovers_exact_pending_rotation_before_sending_reports(tmp_path, loss):
    client, secrets, record, rotations, calls = setup_connection(tmp_path, **{loss: True})
    clock = Clock()
    record['expires_at'] = clock.wall + 100
    runtime = make_runtime(tmp_path, client, clock)
    with pytest.raises(CloudError, match='outcome_unknown'): runtime.exchange()
    pending = json.loads(next(iter(secrets.values.values())))['pending']
    assert not any(r.url.path.endswith('/exchange') for r in calls)
    recovered = make_runtime(tmp_path, client, clock)
    recovered.exchange()
    assert all(rotation[1] == pending for rotation in rotations)
    assert len(rotations) == (1 if loss == 'lose_commit' else 2)
    assert next(iter(secrets.values.values())) == pending['credential']
    assert recovered.cloud_state == 'connected'


def test_uncommitted_manual_renewal_is_resumed_even_outside_automatic_renewal_window(tmp_path):
    client, _, record, rotations, _ = setup_connection(tmp_path, lose_before=True)
    record['expires_at'] = Clock.wall + 20 * 86400
    with pytest.raises(CloudError): client().renew()
    make_runtime(tmp_path, client, Clock()).exchange()
    assert len(rotations) == 2 and rotations[0] == rotations[1]


@pytest.mark.parametrize('state', ['revoked', 'expired'])
def test_inactive_connection_never_renews_or_automatically_enrolls_again(tmp_path, state):
    client, secrets, record, rotations, calls = setup_connection(tmp_path)
    record['state'] = state
    before = dict(secrets.values)
    with pytest.raises(CloudError, match='connection_inactive'):
        make_runtime(tmp_path, client, Clock()).exchange()
    assert not rotations and secrets.values == before
    assert len(calls) == 2  # enrollment plus status, no exchange/renewal/enrollment retry


def test_config_replacement_between_maintenance_and_exchange_cannot_redirect_outbox(tmp_path):
    client, _, record, _, calls = setup_connection(tmp_path)
    clock = Clock()
    record['expires_at'] = clock.wall + 10 * 86400
    runtime = make_runtime(tmp_path, client, clock)
    original = runtime.cloud.maintain
    def replace(**kwargs):
        result = original(**kwargs)
        settings = runtime.cloud.settings()
        settings['site_id'] = 'sit_' + 'b' * 32
        runtime.cloud.config.write_text(json.dumps(settings))
        return result
    runtime.cloud.maintain = replace
    with pytest.raises(CloudError, match='identity_changed'): runtime.exchange()
    assert not any(r.url.path.endswith('/exchange') for r in calls)
    # A fresh process pinned to the old identity also refuses before any HTTP request.
    count = len(calls)
    with pytest.raises(CloudError, match='identity_changed'):
        client().maintain(now=clock.wall, expected_identity=runtime.cloud_identity)
    assert len(calls) == count


def test_network_blocked_maintenance_does_not_block_local_job_completion(tmp_path):
    client, _, _, _, _ = setup_connection(tmp_path)
    with EngineFixture() as engine:
        store = setup(tmp_path / 'runtime', engine)
        c = command(store)
        scope = {k: c[k] for k in ('tenant_id', 'project_id', 'site_id')}
        store.accept(c, scope, origin='local')
        runtime = make_runtime(tmp_path, client, Clock(), store=store, engine=ComfyEngine(engine.endpoint))
        entered, release = threading.Event(), threading.Event()
        def blocked(**_):
            entered.set()
            if not release.wait(10): raise AssertionError('Test did not release blocked maintenance')
            raise CloudError('cloud_outcome_unknown_retry_same_connection')
        runtime.cloud.maintain = blocked
        runtime.interval = 0.01
        async def exercise():
            task = asyncio.create_task(runtime.run())
            try:
                async def completed():
                    while not entered.is_set() or not engine.posts: await asyncio.sleep(0.01)
                    engine.finish(store.jobs()[0]['engine_job_id'])
                    while store.jobs()[0]['state'] != 'succeeded': await asyncio.sleep(0.01)
                await asyncio.wait_for(completed(), 5)
                assert not release.is_set() and engine.posts == 1
            finally:
                runtime.stopping.set()
                release.set()
                await asyncio.wait_for(task, 5)
        asyncio.run(exercise())
