import json
from uuid import uuid4

import httpx
import pytest
from starlette.testclient import TestClient

from vgpu_local.cloud import CloudConnection, CloudError
from vgpu_local.comfyui import ComfyEngine, EngineError
from vgpu_local.journal import fingerprint
from vgpu_local.runtime import Runtime
from vgpu_local.runtime_config import load
from vgpu_local.runtime_server import application
from vgpu_local.runtime_store import RuntimeStore
from runtime_fixture import EngineFixture, PROMPT, service, setup, submit, wait_for, crash_runtime
from test_cloud import Secrets, connected

SCOPE = {"tenant_id": "ten_example0", "project_id": "prj_example0", "site_id": "sit_"+"a"*32}


def command(store, **changes):
    value = store.local_command(SCOPE["site_id"], "start", "fixture")
    value.update(SCOPE, **changes)
    value["request_sha256"] = fingerprint({k: v for k, v in value.items() if k != "request_sha256"})
    return value


@pytest.fixture
def store(tmp_path):
    value = RuntimeStore(tmp_path / "jobs.sqlite3", create=True)
    value.install_recipe("fixture", "Test workflow", PROMPT)
    return value


def test_duplicate_commands_and_claims_survive_restart(store):
    c = command(store)
    first = store.accept(c, SCOPE, origin="cloud")
    assert first["accepted"]
    claimed = store.claim_submission(c["execution_id"])
    recovered = RuntimeStore(store.journal.path)
    assert recovered.accept(c, SCOPE, origin="cloud", now=c["expires_at"]+10) == first
    assert recovered.claim_submission(c["execution_id"]) is None
    assert recovered.job(c["execution_id"])["correlation"] == claimed["correlation"]


@pytest.mark.parametrize("changes,error", [({"expires_at": 1}, "command_expired"),
    ({"recipe_sha256": "f"*64}, "recipe_not_approved")])
def test_rejected_commands_never_reach_engine(store, changes, error):
    assert store.accept(command(store, **changes), SCOPE, origin="cloud")["error_code"] == error
    assert store.jobs() == []


def test_wrong_scope_digest_and_stale_commands_cannot_mutate_jobs(store):
    c = command(store)
    with pytest.raises(ValueError, match="scope"): store.accept(c, {**SCOPE, "site_id": "sit_"+"b"*32}, origin="cloud")
    with pytest.raises(ValueError, match="digest"): store.accept({**c, "recipe_sha256": "f"*64}, SCOPE, origin="cloud")
    store.accept(c, SCOPE, origin="cloud")
    stale = {**c, "command_id": "cmd_"+uuid4().hex}
    stale["request_sha256"] = fingerprint({k: v for k, v in stale.items() if k != "request_sha256"})
    assert store.accept(stale, SCOPE, origin="cloud")["error_code"] == "stale_generation"
    assert len(store.jobs()) == 1


def test_cancellation_tombstone_prevents_late_start(store):
    start = command(store)
    cancel = command(store, execution_id=start["execution_id"], action="cancel", generation=2)
    store.accept(cancel, SCOPE, origin="cloud")
    assert store.accept(start, SCOPE, origin="cloud")["error_code"] == "stale_generation"
    assert store.jobs()[0]["state"] == "canceled"
    assert store.claim_submission(start["execution_id"]) is None


def test_outbox_acks_cannot_erase_newer_results_or_unsent_receipts(store):
    c = command(store)
    store.accept(c, SCOPE, origin="cloud")
    sent = store.exchange_batch()
    store.claim_submission(c["execution_id"])
    response = dict(command_receipts=[c["command_id"]], report_receipts=[{"execution_id": c["execution_id"], "revision": 1}])
    store.acknowledge(sent, response)
    pending = store.exchange_batch()
    assert pending["receipts"] == [] and pending["reports"][0]["revision"] == 2
    with pytest.raises(ValueError): store.acknowledge(sent, {**response, "command_receipts": ["cmd_"+"b"*32]})


def test_missing_engine_evidence_never_recreates_and_wrong_marker_never_adopts(store):
    c = command(store)
    store.accept(c, SCOPE, origin="cloud")
    job = store.claim_submission(c["execution_id"])
    seen = []
    def wire(request):
        seen.append(request.method)
        if request.url.path.startswith("/history/"): return httpx.Response(200, json={})
        return httpx.Response(200, json={"queue_running": [], "queue_pending": []})
    runtime = Runtime(store, ComfyEngine("http://127.0.0.1:8188", transport=httpx.MockTransport(wire)))
    for _ in range(3): runtime.step()
    assert store.job(c["execution_id"])["state"] == "uncertain" and set(seen) == {"GET"}
    runtime.engine.transport = httpx.MockTransport(lambda r: httpx.Response(200, json={job["engine_job_id"]: {"prompt": [0, job["engine_job_id"], {}, {}]}}))
    runtime.step()
    assert store.job(c["execution_id"])["error_code"] == "engine_identity_conflict"


def test_old_active_job_is_not_hidden_by_more_than_500_completed_jobs(store):
    from concurrent.futures import ThreadPoolExecutor
    c = command(store)
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _: store.accept(c, SCOPE, origin="cloud"), range(16)))
        claims = list(executor.map(lambda _: store.claim_submission(c["execution_id"]), range(16)))
    assert sum(item is not None for item in claims) == 1
    with store.journal.connection() as db:
        sample = store.report(claims[next(i for i, v in enumerate(claims) if v)])
        for _ in range(501):
            data = {**sample, "execution_id": "lex_"+uuid4().hex, "state": "succeeded"}
            db.execute("INSERT INTO runtime_jobs VALUES(?,?)", (data["execution_id"], json.dumps(data)))
    assert [job["execution_id"] for job in store.jobs(active=True)] == [c["execution_id"]]


def test_specific_cancellation_does_not_stop_another_engine_job(tmp_path):
    with EngineFixture() as engine:
        store = setup(tmp_path / "runtime", engine)
        one, two = command(store), command(store)
        for c in (one, two): store.accept(c, SCOPE, origin="cloud")
        runtime = Runtime(store, ComfyEngine(engine.endpoint))
        runtime.step()
        cancel = command(store, action="cancel", generation=2, execution_id=one["execution_id"])
        store.accept(cancel, SCOPE, origin="cloud")
        runtime.step(); runtime.step()
        assert store.job(one["execution_id"])["state"] == "canceled"
        assert store.job(two["execution_id"])["state"] == "running"
        assert len(engine.jobs) == 1 and engine.posts == 2


def test_canceling_a_queued_engine_job_finishes_although_the_engine_records_nothing(tmp_path):
    with EngineFixture() as engine:
        store = setup(tmp_path / "runtime", engine)
        running, waiting = command(store), command(store)
        for c in (running, waiting): store.accept(c, SCOPE, origin="cloud")
        runtime = Runtime(store, ComfyEngine(engine.endpoint))
        runtime.step()
        engine.waiting.add(store.job(waiting["execution_id"])["engine_job_id"])
        runtime.step()
        assert store.job(waiting["execution_id"])["state"] == "queued"
        cancel = command(store, action="cancel", generation=2, execution_id=waiting["execution_id"])
        store.accept(cancel, SCOPE, origin="cloud")
        runtime.step()  # The engine confirms removing the pending prompt.
        assert store.job(waiting["execution_id"])["state"] == "cancel_requested"
        runtime.step()  # Neither queued, running nor in history: it never ran.
        job = store.job(waiting["execution_id"])
        assert (job["state"], job["error_code"]) == ("canceled", "engine_dequeued")
        assert store.job(running["execution_id"])["state"] == "running"
        assert engine.history == {} and engine.posts == 2


def test_a_job_missing_from_the_engine_is_not_assumed_canceled(tmp_path):
    with EngineFixture() as engine:
        store = setup(tmp_path / "runtime", engine)
        c = command(store); store.accept(c, SCOPE, origin="cloud")
        runtime = Runtime(store, ComfyEngine(engine.endpoint))
        runtime.step()
        cancel = command(store, action="cancel", generation=2, execution_id=c["execution_id"])
        store.accept(cancel, SCOPE, origin="cloud")
        engine.jobs.clear()  # Lost without any record, e.g. an engine restart.
        runtime.step(); runtime.step()
        job = store.job(c["execution_id"])
        assert job["state"] == "cancel_requested" and not job.get("dequeued")


def test_unsupported_targeted_cancellation_never_uses_global_interrupt(store):
    c = command(store); store.accept(c, SCOPE, origin="cloud")
    job = store.claim_submission(c["execution_id"])
    requests = []
    def wire(request):
        requests.append(request.url.path)
        return httpx.Response(404, json={"error": "not_found"})
    with pytest.raises(EngineError, match="targeted_cancel_unavailable"):
        ComfyEngine("http://127.0.0.1:8188", transport=httpx.MockTransport(wire)).cancel(job)
    assert requests == [f'/api/jobs/{job["engine_job_id"]}/cancel']


def test_local_api_requires_bearer_and_same_origin_even_with_valid_token(store):
    runtime = Runtime(store, None)
    app = application(runtime, SCOPE["site_id"], origin="http://127.0.0.1:8000", token="secret", shutdown=lambda: None)
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    assert client.get("/api/status").status_code == 401
    headers = {"Authorization": "Bearer secret"}
    assert client.get("/api/status", headers=headers).status_code == 200
    for more in ({"Origin": "https://evil.example"}, {"Origin": "null"}, {"Host": "evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
        assert client.get("/api/status", headers={**headers, **more}).status_code == 403
    assert client.get("/", headers={"Origin": "https://evil.example"}).status_code == 403
    page = client.get("/")
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert "access-control-allow-origin" not in page.headers
    assert client.get("/../config.json").status_code == 404


def test_real_process_restart_adopts_lost_submit_reply_and_retains_result(tmp_path):
    with EngineFixture() as engine:
        engine.lose_reply = True
        path = tmp_path / "runtime"
        store = setup(path, engine)
        with service(path) as (info, process):
            c = submit(info)
            wait_for(lambda: engine.posts == 1)
            crashed_pid = info["pid"]
            crash_runtime(info, process)
        with service(path):
            from vgpu_local.runtime_cli import running
            assert running(path)["pid"] != crashed_pid
            wait_for(lambda: store.job(c["execution_id"])["state"] == "running")
            job = store.job(c["execution_id"])
            engine.finish(job["engine_job_id"])
            wait_for(lambda: store.job(c["execution_id"])["state"] == "succeeded")
            assert store.job(c["execution_id"])["outputs"] == {"1": {"text": ["fixture result"]}}
            assert engine.posts == 1


def test_detached_cli_outlives_launching_process_and_stop_preserves_engine_job(tmp_path):
    import subprocess
    import sys
    from vgpu_local.runtime_cli import running, request
    with EngineFixture() as engine:
        path = tmp_path / "runtime"
        store = setup(path, engine)
        args = [sys.executable, "-m", "vgpu_local", "runtime"]
        try:
            result = subprocess.run(args+["start", "--state", str(path)], check=True, capture_output=True, text=True, timeout=20)
            assert json.loads(result.stdout)["running"]
            c = submit(running(path))
            wait_for(lambda: engine.posts == 1)
            second = subprocess.run(args+["serve", "--state", str(path)], capture_output=True, text=True, timeout=10)
            assert second.returncode == 2 and "already_running" in second.stderr
            assert request(path)["jobs"][0]["execution_id"] == c["execution_id"]
        finally:
            request(path, "POST", "/api/stop")
            wait_for(lambda: not (path / "running.json").exists())
        assert len(engine.jobs) == 1  # Stopping the control program is not cancellation.
        engine.finish(store.job(c["execution_id"])["engine_job_id"])
        with service(path):
            wait_for(lambda: store.job(c["execution_id"])["state"] == "succeeded")


def test_outbound_outage_replay_and_scope_change_do_not_duplicate_work(tmp_path):
    secrets, record, exchanges = Secrets(), {}, []
    outage = False
    c = None
    def wire(request):
        nonlocal outage
        if request.url.path.endswith("/sites"):
            record.update(json.loads(request.content)); return httpx.Response(201, json=connected(record))
        assert request.headers["authorization"] == "Bearer "+record["credential"]
        if request.method == "GET": return httpx.Response(200, json=connected(record))
        batch = json.loads(request.content); exchanges.append(batch)
        if outage: raise httpx.ReadTimeout("lost reply")
        return httpx.Response(200, json={**SCOPE, "site_id": record["site_id"], "commands": [c],
              "command_receipts": [r["command_id"] for r in batch["receipts"]],
              "report_receipts": [{k: r[k] for k in ("execution_id", "revision")} for r in batch["reports"]]})
    cloud = CloudConnection(tmp_path / "cloud.json", secrets, transport=httpx.MockTransport(wire), lock_dir=tmp_path / "locks")
    cloud.connect(endpoint="https://cloud.example", tenant_id=SCOPE["tenant_id"], project_id=SCOPE["project_id"], name="Office", user_access_token="user")
    settings = cloud.settings()
    with EngineFixture() as engine:
        store = setup(tmp_path / "runtime", engine)
        c = command(store, site_id=record["site_id"])
        runtime = Runtime(store, ComfyEngine(engine.endpoint), cloud=cloud,
                          cloud_identity={k: settings[k] for k in ("endpoint", "tenant_id", "project_id", "site_id")})
        runtime.exchange(); runtime.step(); outage = True
        with pytest.raises(CloudError): runtime.exchange()
        engine.finish(store.jobs()[0]["engine_job_id"])
        runtime.step()
        assert store.jobs()[0]["state"] == "succeeded"
        outage = False
        runtime.exchange(); runtime.exchange()
        assert engine.posts == 1 and store.exchange_batch() == {"receipts": [], "reports": []}
        assert exchanges[-2]["reports"][0]["state"] == "succeeded"
        settings["site_id"] = "sit_"+"b"*32
        cloud.config.write_text(json.dumps(settings))
        with pytest.raises(CloudError, match="identity_changed"): runtime.exchange()


def test_connected_runtime_shares_its_recipe_catalog_only_when_it_changes(tmp_path, store):
    secrets, record, exchanges, held = Secrets(), {}, [], {}
    def wire(request):
        if request.url.path.endswith("/sites"):
            record.update(json.loads(request.content)); return httpx.Response(201, json=connected(record))
        if request.method == "GET": return httpx.Response(200, json=connected(record))
        batch = json.loads(request.content); exchanges.append(batch)
        if "recipes" in batch: held["digest"] = fingerprint(batch["recipes"])
        result = {**SCOPE, "site_id": record["site_id"], "commands": [], "command_receipts": [], "report_receipts": []}
        return httpx.Response(200, json={**result, **({"recipes_sha256": held["digest"]} if held.get("digest") else {})})
    cloud = CloudConnection(tmp_path / "cloud.json", secrets, transport=httpx.MockTransport(wire), lock_dir=tmp_path / "locks")
    cloud.connect(endpoint="https://cloud.example", tenant_id=SCOPE["tenant_id"], project_id=SCOPE["project_id"],
                  name="Office", user_access_token="user")
    settings = cloud.settings()
    runtime = Runtime(store, None, cloud=cloud,
                      cloud_identity={k: settings[k] for k in ("endpoint", "tenant_id", "project_id", "site_id")})
    runtime.exchange(); runtime.exchange()
    assert exchanges[0]["recipes"] == [{"recipe_id": "fixture", "title": "Test workflow", "recipe_sha256": fingerprint(PROMPT)}]
    assert "recipes" not in exchanges[1]
    # Only identity, title and digest leave the machine, never the workflow.
    assert all(json.dumps(node) not in json.dumps(exchanges[0]) for node in PROMPT.values())

    store.install_recipe("another", "Second workflow", PROMPT)
    runtime.exchange()
    assert [recipe["recipe_id"] for recipe in exchanges[2]["recipes"]] == ["another", "fixture"]

    # A service that lost its copy receives the catalog again on the next call.
    held.clear()
    runtime.exchange(); runtime.exchange(); runtime.exchange()
    assert "recipes" not in exchanges[3] and "recipes" in exchanges[4] and "recipes" not in exchanges[5]

    # A restarted runtime does not know the service's copy and sends it once.
    restarted = Runtime(store, None, cloud=cloud, cloud_identity=runtime.cloud_identity)
    restarted.exchange(); restarted.exchange()
    assert "recipes" in exchanges[6] and "recipes" not in exchanges[7]


def test_startable_catalog_is_the_first_hundred_recipes_by_id(store):
    for number in range(105):
        store.install_recipe(f"r{number:03d}", f"Recipe {number}", PROMPT)
    catalog = store.startable_recipes()
    assert len(catalog) == 100
    assert [recipe["recipe_id"] for recipe in catalog] == sorted(recipe["recipe_id"] for recipe in catalog)
    assert catalog[0]["recipe_id"] == "fixture" and catalog[-1]["recipe_id"] == "r098"
    assert all(set(recipe) == {"recipe_id", "title", "recipe_sha256"} for recipe in catalog)
