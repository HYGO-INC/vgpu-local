"""Offline qualification of the pinned SDK's models and adapter call boundary."""
import json
from unittest.mock import patch

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from vgpu_local.kubernetes_api import KubernetesAPI
from vgpu_local.errors import OutcomeUnknown


def configure(*, client_configuration, **kwargs):
    assert kwargs == {'config_file':None,'context':'qualification','persist_config':False}
    client_configuration.host = 'https://qualification.invalid'
    client_configuration.verify_ssl = True


with patch.object(config,'load_kube_config',configure):
    api = KubernetesAPI(context='qualification',namespace='gpu-jobs')
try:
    assert api.client.configuration.retries == 0
    with patch.object(api.core,'read_namespace',return_value=client.V1Namespace(metadata=client.V1ObjectMeta(uid='namespace-uid'))) as call:
        assert api.namespace_uid() == 'namespace-uid'
        call.assert_called_once_with('gpu-jobs',_request_timeout=(5,20))
    with patch.object(api.custom,'get_namespaced_custom_object',return_value={'metadata':{'name':'gpu','namespace':'gpu-jobs'}}) as call:
        assert api.queue_exists('gpu')
        call.assert_called_once_with('kueue.x-k8s.io','v1beta1','gpu-jobs','localqueues','gpu',_request_timeout=(5,20))
    document = {'apiVersion':'batch/v1','kind':'Job','metadata':{'name':'job'}}
    job = client.V1Job(api_version='batch/v1',kind='Job',metadata=client.V1ObjectMeta(name='job',uid='job-uid'))
    with patch.object(api.batch,'create_namespaced_job',return_value=job) as call:
        assert api.create_job(document)['metadata']['uid'] == 'job-uid'
        call.assert_called_once_with('gpu-jobs',document,_request_timeout=(5,20))
    with patch.object(api.batch,'delete_namespaced_job',return_value=client.V1Status(status='Success')) as call:
        api.delete_job('job','job-uid')
        args,kwargs = call.call_args
        assert args == ('job','gpu-jobs')
        assert kwargs['_request_timeout'] == (5,20)
        assert api.client.sanitize_for_serialization(kwargs['body']) == {'preconditions':{'uid':'job-uid'},'propagationPolicy':'Foreground'}
    with patch.object(api.batch,'read_namespaced_job',side_effect=ApiException(status=404)):
        assert api.get_job('job') is None
    with patch.object(api.batch,'read_namespaced_job',side_effect=ApiException(status=403)):
        try: api.get_job('job')
        except OutcomeUnknown: pass
        else: raise AssertionError('Forbidden was mistaken for missing')
    pages = [{'items':[{'metadata':{'ownerReferences':[{'uid':'foreign'}]}}],'metadata':{'continue':'next'}},
             {'items':[{'metadata':{'ownerReferences':[{'uid':'job-uid'}]}}],'metadata':{}}]
    with patch.object(api.core,'list_namespaced_pod',side_effect=pages) as call:
        assert len(api.owned_pods('job-uid')) == 1
        assert call.call_args.kwargs == {'_request_timeout':(5,20),'limit':500,'_continue':'next'}
    print(json.dumps({'kubernetes':'35.0.0','provider_calls':0,'bounded_requests':True,'uid_delete':True,'pod_pagination':True}))
finally:
    api.close()
