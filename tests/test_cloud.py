import json

import httpx
import pytest

from vgpu_local.cloud import CloudConnection, CloudError, endpoint_url


class Secrets:
    def __init__(self): self.values = {}
    def get(self, name): return self.values.get(name)
    def set(self, name, secret): self.values[name] = secret


def connected(body, **changes):
    return dict(site_id=body['site_id'], tenant_id='ten_example0', project_id='prj_example0', name=body['name'],
                protocol_version='vgpu.site.v1', state='active', credential_expires_at=1800000000,
                consumption_enabled=False, contribution_enabled=False, **changes)


def test_lost_enrollment_reply_preserves_key_and_site_without_plaintext_in_config(tmp_path):
    seen = []
    secrets = Secrets()
    def server(request):
        assert request.headers['authorization'] == 'Bearer user-token'
        body = json.loads(request.content)
        seen.append(body)
        assert body['credential'] in secrets.values.values()  # saved before sending
        if len(seen) == 1: raise httpx.ReadTimeout('secret data must not be echoed')
        return httpx.Response(201, json=connected(body))
    path = tmp_path / 'cloud.json'
    client = CloudConnection(path, secrets, transport=httpx.MockTransport(server))
    kwargs = dict(endpoint='https://cloud.example', tenant_id='ten_example0', project_id='prj_example0', name='Office', user_access_token='user-token')
    with pytest.raises(CloudError, match='cloud_outcome_unknown_retry_same_connection'): client.connect(**kwargs)
    result = client.connect(**kwargs)
    assert seen[0] == seen[1]
    assert result['consumption_enabled'] is False and result['contribution_enabled'] is False
    assert seen[0]['credential'] not in path.read_text()
    assert 'user-token' not in path.read_text()
    assert len(secrets.values) == 1


def test_redirect_never_forwards_token(tmp_path):
    requests = []
    def server(request):
        requests.append(request)
        return httpx.Response(307, headers={'Location': 'https://another.example/stolen'})
    client = CloudConnection(tmp_path / 'cloud.json', Secrets(), transport=httpx.MockTransport(server))
    with pytest.raises(CloudError, match='cloud_request_failed'):
        client.connect(endpoint='https://cloud.example', tenant_id='ten_example0', project_id='prj_example0', name='Office', user_access_token='user-token')
    assert len(requests) == 1


def test_response_scope_and_config_origin_are_bound(tmp_path):
    requests = []
    def server(request):
        requests.append(request)
        body = json.loads(request.content)
        result = connected(body)
        result['project_id'] = 'prj_different0'
        return httpx.Response(200, json=result)
    path = tmp_path / 'cloud.json'
    client = CloudConnection(path, Secrets(), transport=httpx.MockTransport(server))
    with pytest.raises(CloudError, match='scope_mismatch'):
        client.connect(endpoint='https://cloud.example', tenant_id='ten_example0', project_id='prj_example0', name='Office', user_access_token='user-token')
    data = json.loads(path.read_text()); data['endpoint'] = 'https://different.example'; path.write_text(json.dumps(data))
    with pytest.raises(CloudError, match='site_credential_unavailable'): client.status()
    assert len(requests) == 1


def test_site_key_only_used_on_own_connection_endpoints(tmp_path):
    seen = []
    record = {}
    def server(request):
        seen.append(request)
        if request.url.path.endswith('/sites'):
            record.update(json.loads(request.content))
        else:
            assert request.headers['authorization'] == 'Bearer ' + record['credential']
            assert f'/sites/{record["site_id"]}/connection' in request.url.path
        result = connected(record)
        if request.url.path.endswith('/revoke'): result['state'] = 'revoked'
        return httpx.Response(200, json=result)
    client = CloudConnection(tmp_path / 'cloud.json', Secrets(), transport=httpx.MockTransport(server))
    client.connect(endpoint='https://cloud.example', tenant_id='ten_example0', project_id='prj_example0', name='Office', user_access_token='user-token')
    client.status()
    assert client.disconnect()['state'] == 'revoked'
    assert client.disconnect()['state'] == 'revoked'
    assert len(seen) == 4


@pytest.mark.parametrize('url', ['http://cloud.example', 'https://user:pass@cloud.example', 'https://cloud.example/path', 'https://cloud.example?url=x', 'https://cloud.example#fragment'])
def test_reject_unsafe_endpoint(url):
    with pytest.raises(CloudError): endpoint_url(url)
