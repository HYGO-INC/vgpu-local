from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from vgpu_local.contracts.models import BackendRequest
from vgpu_local.errors import KeyConflict, OutcomeUnknown, UnsupportedCapability
from vgpu_local.journal import Journal
from vgpu_local.kubernetes_backend import GpuClass, KubernetesBackend


class API:
    namespace = 'namespace-uid'
    job = None
    pods = []
    creates = 0
    deletes = 0
    queue = True
    lost_create = False
    lose_before_create = False
    lost_delete = False
    retain_pods = False

    def namespace_uid(self): return self.namespace
    def queue_exists(self, name): return self.queue
    def create_job(self, document):
        self.creates += 1
        if self.lose_before_create: raise TimeoutError()
        self.created = deepcopy(document)
        self.job = deepcopy(document)
        self.job['spec']['suspend'] = False  # Emulate subsequent Kueue admission.
        self.job['metadata']['uid'] = 'job-uid'
        self.job['status'] = {'active':1}
        self.pods = [{'metadata':{'ownerReferences':[{'uid':'job-uid'}]},
            'status':{'phase':'Running','containerStatuses':[{'name':'workload','state':{'running':{}}}]}}]
        if self.lost_create: raise TimeoutError()
        return deepcopy(self.job)
    def get_job(self, name): return deepcopy(self.job)
    def delete_job(self, name, uid):
        self.deletes += 1
        if self.job is not None:
            assert self.job['metadata']['uid'] == uid
            self.job = None
        if not self.retain_pods: self.pods = []
        if self.lost_delete: raise TimeoutError()
    def owned_pods(self, uid): return deepcopy(self.pods)


@pytest.fixture
def setup(tmp_path):
    api = API()
    journal = Journal(tmp_path/'site.db')
    backend = KubernetesBackend(journal,api,account_id='site-a',namespace='gpu-jobs',namespace_uid='namespace-uid',
        queue='gpu',region='office',gpu_classes={'RTX4090':GpuClass('nvidia.com/gpu','NVIDIA-GeForce-RTX-4090')})
    request = BackendRequest(tenant_id='tenant-a',project_id='project-a',account_id='site-a',operation_id='operation-a',
        generation=1,provider='kubernetes',image='example:1',gpu_model='RTX4090',gpu_count=2,num_nodes=1,
        region='office',capacity_mode='on_demand',workload_trust='owner',max_hourly_price_microusd=1,command=['nvidia-smi'])
    return backend,api,request


def test_kueue_owns_suspension_and_gpu_placement_with_one_create_across_retries(setup):
    backend,api,request = setup
    assert backend.provision(request).state == 'running'
    with ThreadPoolExecutor(max_workers=8) as pool:
        replies = list(pool.map(lambda _:backend.provision(request),range(16)))
    assert api.creates == 1 and {reply.resource_id for reply in replies} == {'k8s:job-uid'}
    assert api.created['spec']['suspend'] is True
    assert api.job['spec']['parallelism'] == 1
    assert api.created['spec']['podReplacementPolicy'] == 'Failed'
    assert api.job['spec']['template']['spec']['containers'][0]['resources']['limits'] == {'nvidia.com/gpu':2}
    with pytest.raises(KeyConflict): backend.provision(request.model_copy(update={'gpu_count':1}))


def test_lost_create_is_adopted_and_missing_uncertain_create_is_never_reissued(setup):
    backend,api,request = setup
    api.lost_create = True
    with pytest.raises(OutcomeUnknown): backend.provision(request)
    assert backend.observe(request).resource_id == 'k8s:job-uid'
    assert backend.provision(request).state == 'running' and api.creates == 1
    another = request.model_copy(update={'operation_id':'second-operation'})
    api.lose_before_create = True
    with pytest.raises(OutcomeUnknown): backend.provision(another)
    api.job = None
    with pytest.raises(OutcomeUnknown): backend.provision(another)
    with pytest.raises(OutcomeUnknown): backend.release(another)
    assert api.creates == 2 and api.deletes == 0


@pytest.mark.parametrize('change',[{'account_id':'another'},{'region':'another'},{'num_nodes':2},
    {'workload_trust':'untrusted'},{'capacity_mode':'spot'},{'gpu_model':'unknown'}])
def test_unqualified_requests_never_create_capacity(setup,change):
    backend,api,request = setup
    with pytest.raises(UnsupportedCapability): backend.provision(request.model_copy(update=change))
    assert api.creates == 0


def test_missing_queue_and_changed_namespace_fail_before_any_create(setup):
    backend,api,request = setup
    api.queue = False
    with pytest.raises(UnsupportedCapability): backend.provision(request)
    api.queue = True
    api.namespace = 'recreated-namespace'
    with pytest.raises(OutcomeUnknown): backend.provision(request)
    assert api.creates == 0


@pytest.mark.parametrize('tamper',['uid','fingerprint','command','gpu','namespace'])
def test_foreign_or_changed_jobs_are_never_adopted_or_deleted(setup,tamper):
    backend,api,request = setup
    backend.provision(request)
    if tamper == 'uid': api.job['metadata']['uid'] = 'foreign-job'
    elif tamper == 'fingerprint': api.job['metadata']['annotations']['vgpu.com/request-sha256'] = 'bad'
    elif tamper == 'command': api.job['spec']['template']['spec']['containers'][0]['command'] = ['other']
    elif tamper == 'gpu': api.job['spec']['template']['spec']['containers'][0]['resources']['limits']['nvidia.com/gpu'] = 1
    else: api.job['metadata']['namespace'] = 'other'
    with pytest.raises(OutcomeUnknown): backend.observe(request)
    with pytest.raises(OutcomeUnknown): backend.release(request)
    assert api.deletes == 0


@pytest.mark.parametrize('condition,state',[('Complete','succeeded'),('Failed','failed')])
def test_workload_completion_is_separate_from_confirmed_teardown(setup,condition,state):
    backend,api,request = setup
    backend.provision(request)
    api.job['status'] = {'conditions':[{'type':condition,'status':'True'}]}
    finished = backend.observe(request)
    assert finished.workload.state == state and finished.supplier_state == 'allocated'
    api.pods = [{'metadata':{'uid':'terminating-pod'}}]
    api.retain_pods = True
    releasing = backend.release(request)
    assert releasing.supplier_state != 'released' and releasing.workload.state == state
    api.pods = []
    released = backend.observe(request)
    assert released.state == 'released' and released.workload.state == state
    assert backend.provision(request) == released and api.creates == 1


def test_delete_reply_loss_recovers_without_deleting_another_job(setup):
    backend,api,request = setup
    backend.provision(request)
    api.lost_delete = True
    with pytest.raises(OutcomeUnknown): backend.release(request)
    result = backend.release(request)
    assert result.supplier_state == 'released' and api.deletes == 1


def test_saved_manifest_allows_cleanup_after_gpu_catalog_or_queue_discovery_changes(setup):
    backend,api,request = setup
    backend.provision(request)
    api.queue = False
    backend.gpu_classes = {'H100':GpuClass('nvidia.com/gpu','NVIDIA-H100')}
    assert backend.provision(request).workload.state == 'running'
    assert backend.release(request).supplier_state == 'released'
    assert api.creates == 1


def test_pending_pods_and_failure_targets_do_not_forge_running_or_completed_work(setup):
    backend,api,request = setup
    backend.provision(request)
    api.pods = [{'status':{'phase':'Pending'}}]
    api.job['status'] = {'active':1,'conditions':[{'type':'FailureTarget','status':'True'}]}
    result = backend.observe(request)
    assert result.state == 'provisioning' and result.workload.state == 'queued'
    api.job['spec']['template']['spec']['containers'][0]['resources']['limits']['memory'] = '1Gi'
    assert backend.observe(request).workload.state == 'queued'


def test_late_observation_cannot_restore_released_capacity(setup,monkeypatch):
    backend,api,request = setup
    backend.provision(request)
    get = api.get_job
    fired = False
    def delayed(name):
        nonlocal fired
        result = get(name)
        if not fired:
            fired = True
            backend.release(request)
        return result
    monkeypatch.setattr(api,'get_job',delayed)
    assert backend.observe(request).supplier_state == 'released'
    assert backend.observe(request).supplier_state == 'released'
