from argparse import Namespace
import json
from pathlib import Path
import sqlite3

import pytest

from vgpu_local import kubernetes_cli as cli
from vgpu_local.journal import Journal
from vgpu_local.kubernetes_config import validate_config
from test_kubernetes_backend import API

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def setup(tmp_path, monkeypatch):
    config = json.loads((ROOT/'examples/kubernetes-site.json').read_text())
    config['namespace_uid'] = 'namespace-uid'
    request = json.loads((ROOT/'examples/kubernetes-request.json').read_text())
    paths = {'config':tmp_path/'site.json', 'request':tmp_path/'request.json', 'journal':tmp_path/'operations.db'}
    paths['config'].write_text(json.dumps(config))
    paths['request'].write_text(json.dumps(request))
    api = API()
    api.closes,api.connections = 0,0
    def close(): api.closes += 1
    api.close = close
    def factory(**kwargs):
        api.connections += 1
        assert kwargs == dict(context='my-home-cluster',namespace='gpu-jobs',kubeconfig=None,queue_api_version='v1beta1')
        return api
    monkeypatch.setattr(cli,'KubernetesAPI',factory)
    def call(action):
        return cli.run(Namespace(kubernetes_action=action,account_id='home-site',**paths))
    return call,api,paths,request


def test_cli_explicit_initialization_validation_and_lost_reply_recovery(setup):
    call,api,paths,request = setup
    assert call('validate')['status'] == 'valid' and api.connections == 0
    with pytest.raises(ValueError,match='Journal missing'): call('provision')
    assert call('init') == {'status':'initialized'}
    with pytest.raises(FileExistsError): call('init')
    api.lost_create = True
    with pytest.raises(RuntimeError,match='OutcomeUnknown'): call('provision')
    assert call('observe')['resource_id'] == 'k8s:job-uid'
    assert call('provision')['state'] == 'running' and api.creates == 1
    api.lost_delete = True
    with pytest.raises(RuntimeError,match='OutcomeUnknown'): call('release')
    assert call('observe')['supplier_state'] == 'released'
    assert call('release')['supplier_state'] == 'released' and api.deletes == 1
    assert api.closes == api.connections


def test_cli_rejects_foreign_or_missing_receipts_and_corrupt_journals_before_cluster_access(setup):
    call,api,paths,request = setup
    call('init')
    with pytest.raises(ValueError,match='No operation receipt'): call('release')
    paths['request'].write_text(json.dumps({**request,'account_id':'foreign'}))
    with pytest.raises(ValueError,match='account binding'): call('provision')
    paths['request'].write_text(json.dumps(request))
    paths['journal'].write_text('broken SQLite')
    with pytest.raises(ValueError,match='unavailable or invalid'): call('provision')
    assert api.connections == 0


def test_existing_only_journal_never_recreates_removed_recovery_evidence(tmp_path):
    path = tmp_path/'journal.db'
    Journal(path)
    journal = Journal(path,create=False)
    path.unlink()
    with pytest.raises(sqlite3.OperationalError): journal.begin('key',{'x':1},{})
    assert not path.exists()


@pytest.mark.parametrize('raw',['{"x":1,"x":2}','[]','{"x":NaN}','{"x":'+('['*2000)+'1'+(']'*2000)+'}', ' '*65537],
                         ids=['duplicate','nonobject','nonfinite','deep','large'])
def test_bounded_unambiguous_command_documents(tmp_path,raw):
    path = tmp_path/'request.json'
    path.write_text(raw)
    with pytest.raises(ValueError): cli.read_object(path)


def test_site_configuration_rejects_unknown_and_unbounded_bindings():
    config = json.loads((ROOT/'examples/kubernetes-site.json').read_text())
    invalid = [{**config,'context':''},{**config,'namespace':'../other'}, {**config,'gpu_classes':{}},
               {**config,'gpu_classes':{'x':{'resource':'cpu','product':'x'}}},
               {**config,'queue_api_version':'v1'},{**config,'token':'secret'},
               {**config,'kubeconfig':None},{**config,'region':'x'*1025}]
    for item in invalid:
        with pytest.raises(ValueError): validate_config(item)
    copy = validate_config(config)
    copy['gpu_classes']['RTX4090']['product'] = 'changed'
    assert copy != validate_config(config)
