"""Identified Kueue Jobs; Kubernetes owns admission, placement and pod execution."""
from dataclasses import dataclass
from typing import Protocol

from .contracts.models import BackendObservation, BackendRequest
from .errors import OutcomeUnknown, UnsupportedCapability
from .journal import ReceiptStore, fingerprint, scope
from .kubernetes import render_job


class KubernetesPort(Protocol):
    def namespace_uid(self) -> str: ...
    def queue_exists(self, name: str) -> bool: ...
    def create_job(self, document: dict) -> dict: ...
    def get_job(self, name: str) -> dict | None: ...
    def delete_job(self, name: str, uid: str) -> None: ...
    def owned_pods(self, uid: str) -> list[dict]: ...


@dataclass(frozen=True)
class GpuClass:
    resource: str
    product: str


class KubernetesBackend:
    """One explicit namespace/account binding; owner workloads and one-node jobs.

    A lost create reply is adopted by deterministic name and immutable intent.
    Absence while create is uncertain never authorizes another create or release.
    Delete always has the previously recorded UID precondition.
    """
    def __init__(self, journal: ReceiptStore, api: KubernetesPort, *, account_id: str, namespace: str,
                 namespace_uid: str, queue: str, region: str, gpu_classes: dict[str,GpuClass], runtime_class='nvidia'):
        if not account_id or not namespace_uid or not region or not gpu_classes:
            raise ValueError('Provide an explicit account, namespace UID, region and GPU classes')
        self.journal,self.api = journal,api
        self.account_id,self.namespace,self.namespace_uid = account_id,namespace,namespace_uid
        self.queue,self.region,self.gpu_classes,self.runtime_class = queue,region,dict(gpu_classes),runtime_class
        self.binding = fingerprint({'account':account_id,'namespace':namespace,'namespace_uid':namespace_uid,
            'queue':queue,'region':region,'runtime_class':runtime_class})

    def _account(self, request):
        request = BackendRequest.model_validate(request.model_dump())
        if request.provider != 'kubernetes' or request.account_id != self.account_id or request.region != self.region:
            raise UnsupportedCapability('Request is outside this configured Kubernetes site')
        if request.num_nodes != 1 or request.workload_trust != 'owner' or request.capacity_mode != 'on_demand':
            raise UnsupportedCapability('This Kubernetes adapter supports owner, single-node, on-demand jobs')

    def _document(self, request):
        self._account(request)
        gpu = self.gpu_classes.get(request.gpu_model)
        if gpu is None: raise UnsupportedCapability('GPU class is not configured at this site')
        job = render_job(name='vg-'+scope(request)[:40],namespace=self.namespace,queue=self.queue,image=request.image,
            command=request.command,gpu_count=request.gpu_count,gpu_resource=gpu.resource,
            runtime_class=self.runtime_class,gpu_product=gpu.product)
        job['spec'].update(parallelism=1,completions=1,podReplacementPolicy='Failed')
        job['metadata']['annotations'].update({'vgpu.com/request-sha256':fingerprint(request.model_dump()),
            'vgpu.com/binding-sha256':self.binding,'vgpu.com/spec-sha256':fingerprint(job['spec'])})
        return job

    def _site(self):
        try:
            if self.api.namespace_uid() != self.namespace_uid:
                raise ValueError('Namespace identity changed')
        except Exception as error:
            raise OutcomeUnknown('Configured Kubernetes namespace is unavailable or changed') from error

    def _owned(self, request):
        self._account(request)
        key = scope(request)
        self.journal.read(key)
        _,receipt = self.journal.begin(key,request.model_dump(),{})
        if receipt.get('binding') != self.binding:
            raise OutcomeUnknown('Operation belongs to another Kubernetes binding')
        return receipt

    def provision(self, request: BackendRequest) -> BackendObservation:
        try: self._owned(request)
        except KeyError: pass
        else: return self.observe(request)
        document = self._document(request)
        self._site()
        try:
            if not self.api.queue_exists(self.queue):
                raise UnsupportedCapability('Configured Kueue LocalQueue is absent')
        except UnsupportedCapability: raise
        except Exception as error: raise OutcomeUnknown('Kueue LocalQueue could not be verified') from error
        claimed,receipt = self.journal.begin(scope(request),request.model_dump(),
            {'binding':self.binding,'state':'uncertain','name':document['metadata']['name'],'manifest':document,'poll':0})
        if not claimed:
            return self.observe(request)
        try:
            job = self.api.create_job(document)
            self._adopt(request,job)
        except Exception as error:
            raise OutcomeUnknown('Kubernetes create may have succeeded; reconcile this exact job') from error
        return self.observe(request)

    def _adopt(self, request, job):
        desired = self.journal.read(scope(request))['manifest']
        metadata = job.get('metadata',{})
        annotations = metadata.get('annotations',{})
        spec = job.get('spec',{})
        expected = desired['spec']['template']['spec']
        actual = spec.get('template',{}).get('spec',{})
        if (job.get('kind') != 'Job' or job.get('apiVersion') != 'batch/v1'
                or metadata.get('name') != desired['metadata']['name'] or metadata.get('namespace') != self.namespace
                or not isinstance(metadata.get('uid'),str) or not metadata['uid']
                or any(annotations.get(key) != desired['metadata']['annotations'][key]
                       for key in ['vgpu.com/request-sha256','vgpu.com/binding-sha256','vgpu.com/spec-sha256'])
                or metadata.get('labels',{}).get('kueue.x-k8s.io/queue-name') != self.queue
                or spec.get('parallelism') != 1 or spec.get('completions') != 1 or spec.get('backoffLimit') != 0
                or spec.get('podReplacementPolicy') != 'Failed'
                or any(actual.get(key) != expected[key] for key in ['restartPolicy','runtimeClassName','automountServiceAccountToken'])
                or len(actual.get('containers',[])) != 1):
            raise OutcomeUnknown('Kubernetes Job does not match accepted scope or intent')
        container,expected_container = actual['containers'][0],expected['containers'][0]
        if any(container.get(key) != expected_container[key] for key in ['name','image','command']) or container.get('args'):
            raise OutcomeUnknown('Kubernetes workload was changed')
        # Admission may add CPU/memory defaults; the requested GPU resource is
        # fixed, and no additional GPU allocation may be silently accepted.
        actual_resources = container.get('resources',{})
        for mode in ['requests','limits']:
            resources = actual_resources.get(mode,{})
            wanted = expected_container['resources'][mode]
            if any(str(resources.get(key)) != str(value) for key,value in wanted.items()):
                raise OutcomeUnknown('Kubernetes GPU request was changed')
            if any('/' in key and key not in wanted for key in resources):
                raise OutcomeUnknown('Kubernetes workload acquired an unexpected extended resource')
        for key,value in expected.get('nodeSelector',{}).items():
            if actual.get('nodeSelector',{}).get(key) != value:
                raise OutcomeUnknown('Kubernetes GPU selector was changed')
        def update(row):
            if row.get('uid') and row['uid'] != metadata['uid']:
                raise OutcomeUnknown('Job name was reused with another UID')
            row['uid'] = metadata['uid']
            if row['state'] == 'uncertain': row['state'] = 'ready'
            return row
        return self.journal.change(scope(request),update)

    def observe(self, request: BackendRequest) -> BackendObservation:
        receipt = self._owned(request)
        if receipt['state'] == 'released': return BackendObservation.model_validate(receipt['observation'])
        self._site()
        ticket = self.journal.change(scope(request),lambda row:{**row,'poll':row['poll']+1})['poll']
        try:
            job = self.api.get_job(receipt['name'])
            if job is None:
                if not receipt.get('uid'):
                    raise OutcomeUnknown('Create remains uncertain; absence does not authorize another create')
                if receipt['state'] == 'releasing' and not self.api.owned_pods(receipt['uid']):
                    return self._observation(request,ticket,'released','released')
                return self._observation(request,ticket,'lost','unknown')
            receipt = self._adopt(request,job)
            conditions = job.get('status',{}).get('conditions',[])
            terminal = {condition.get('type') for condition in conditions if condition.get('status') == 'True'} & {'Complete','Failed'}
            if len(terminal) > 1: raise OutcomeUnknown('Conflicting terminal job conditions')
            # Job.status.active includes Pending pods. It cannot establish that
            # the requested GPU workload actually started.
            pods = self.api.owned_pods(receipt['uid']) if not terminal else []
            running = any(pod.get('status',{}).get('phase') == 'Running' and
                          any(item.get('name') == 'workload' and 'running' in item.get('state',{})
                              for item in pod.get('status',{}).get('containerStatuses',[])) for pod in pods)
            state = 'succeeded' if 'Complete' in terminal else 'failed' if 'Failed' in terminal else 'running' if running else 'queued'
            return self._observation(request,ticket,'running' if running or terminal else 'provisioning','allocated',
                                     {'job_id':receipt['uid'],'state':state})
        except OutcomeUnknown: raise
        except Exception as error: raise OutcomeUnknown('Kubernetes observation could not be verified') from error

    def release(self, request: BackendRequest) -> BackendObservation:
        receipt = self._owned(request)
        if receipt['state'] == 'released': return BackendObservation.model_validate(receipt['observation'])
        # Reconcile a lost create response before selecting a deletion UID.
        self.observe(request)
        receipt = self._owned(request)
        if receipt['state'] == 'released': return BackendObservation.model_validate(receipt['observation'])
        if not receipt.get('uid'): raise OutcomeUnknown('Cannot release an unidentified Kubernetes create')
        self.journal.change(scope(request),lambda row:{**row,'state':'releasing'} if row['state'] != 'released' else row)
        try:
            self._site()
            self.api.delete_job(receipt['name'],receipt['uid'])
        except Exception as error: raise OutcomeUnknown('Kubernetes deletion is unconfirmed') from error
        return self.observe(request)

    def _observation(self, request, ticket, state, supplier, workload=None):
        def update(row):
            previous = row.get('observation')
            if previous and (row['state'] == 'released' or ticket <= row.get('applied_poll',0)): return row
            old_work = previous.get('workload') if previous else None
            if old_work and old_work['state'] in {'succeeded','failed','canceled'}:
                if workload and workload != old_work: raise OutcomeUnknown('Terminal Kubernetes workload outcome changed')
                workload_state = old_work
            else: workload_state = workload
            observation = {key:getattr(request,key) for key in ['tenant_id','project_id','account_id','operation_id','provider','generation']}
            observation.update(resource_id='k8s:'+row['uid'],revision=(previous['revision']+1 if previous else 1),
                               state=state,supplier_state=supplier)
            if workload_state: observation['workload'] = workload_state
            row.update(observation=BackendObservation.model_validate(observation).model_dump(mode='json'),applied_poll=ticket)
            if supplier == 'released': row['state'] = 'released'
            return row
        return BackendObservation.model_validate(self.journal.change(scope(request),update)['observation'])
