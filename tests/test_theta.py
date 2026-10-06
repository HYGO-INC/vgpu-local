import json

import httpx
import pytest

from vgpu_local.errors import KeyConflict, OutcomeUnknown
from vgpu_local.journal import Journal
from vgpu_local.theta import ThetaClient


PARAMS = dict(resource_id="community-node1", template_id="template-a", image="example/gpu:1",
              region="region-a", ssh_public_key="ssh-ed25519 AAAATESTPUBLICKEYONLY sample",
              max_hourly_price_microusd=250000)


def test_project_scope_price_limit_and_response_replay(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.headers["x-api-key"] == "test-key"
        if request.method == "POST":
            payload = json.loads(request.content)
            assert payload["max_price_per_hour_usd"] == .25
            assert payload["region"] == "region-a"
            assert len(payload["name"]) == 20
        return httpx.Response(201, json={"status": "success", "body": {"deployment_id": "dpl-a"}})
    api = ThetaClient("project-a", "test-key", Journal(tmp_path / "ops.db"), transport=httpx.MockTransport(handler))
    assert api.create("create-a", **PARAMS) == {"deployment_id": "dpl-a"}
    api.create("create-a", **PARAMS)
    assert len(calls) == 1
    assert calls[0].url.path == "/v1/projects/project-a/gpu-deployments"
    with pytest.raises(KeyConflict):
        api.create("create-a", **{**PARAMS, "image": "different/image:2"})
    api.close()


@pytest.mark.parametrize("failure", ["timeout", "server_error", "invalid_json"])
def test_ambiguous_create_never_reposts(tmp_path, failure):
    calls = []
    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("lost response", request=request)
        if failure == "invalid_json":
            return httpx.Response(201, text="broken response")
        return httpx.Response(503)
    path = tmp_path / "ops.db"
    api = ThetaClient("project-a", "test", Journal(path), transport=httpx.MockTransport(handler))
    with pytest.raises(OutcomeUnknown):
        api.create("create-a", **PARAMS)
    api.close()
    restarted = ThetaClient("project-a", "test", Journal(path), transport=httpx.MockTransport(handler))
    with pytest.raises(OutcomeUnknown):
        restarted.create("create-a", **PARAMS)
    assert len(calls) == 1
    restarted.close()


def test_read_lifecycle_paths_and_no_redirect_credentials(tmp_path):
    calls = []
    def handler(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json={"status": "success", "body": {}})
    api = ThetaClient("project-a", "test", Journal(tmp_path / "ops.db"), transport=httpx.MockTransport(handler))
    api.resources(); api.templates(); api.deployments(); api.inspect("dpl-a")
    api.stop("dpl-a"); api.start("dpl-a"); api.events("dpl-a"); api.logs("dpl-a"); api.delete("dpl-a")
    assert len(calls) == 9
    assert all(path.startswith("/v1/projects/project-a/") for _, path in calls)
    assert api.client.follow_redirects is False
    with pytest.raises(ValueError):
        api.inspect("../another-project")
    api.close()
