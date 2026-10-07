"""Pinned official Kubernetes client; bounded calls and UID-conditional deletion."""
from importlib.metadata import version
import time
from urllib.parse import urlsplit

from .errors import OutcomeUnknown, UnsupportedCapability


class KubernetesAPI:
    def __init__(self, *, context: str, namespace: str, kubeconfig: str | None = None, queue_api_version='v1beta1'):
        if not context or not namespace or queue_api_version not in {'v1beta1','v1beta2'}:
            raise ValueError('Explicit Kubernetes context, namespace and supported Kueue API version required')
        if version('kubernetes') != '35.0.0':
            raise UnsupportedCapability('Install the pinned kubernetes extra')
        from kubernetes import client, config
        configuration = client.Configuration()
        config.load_kube_config(config_file=kubeconfig, context=context, client_configuration=configuration, persist_config=False)
        endpoint = urlsplit(configuration.host)
        if endpoint.scheme != 'https' or not configuration.verify_ssl:
            raise UnsupportedCapability('Kubernetes requires certificate-verified HTTPS')
        configuration.retries = 0  # In particular, never retry POST behind the operation journal.
        self.client = client.ApiClient(configuration)
        self.core,self.batch,self.custom = client.CoreV1Api(self.client),client.BatchV1Api(self.client),client.CustomObjectsApi(self.client)
        self.namespace,self.queue_api_version = namespace,queue_api_version

    def close(self):
        self.client.close()

    def _call(self, function, *args, missing=False, **kwargs):
        from kubernetes.client.exceptions import ApiException
        try:
            return self.client.sanitize_for_serialization(function(*args, _request_timeout=(5,20), **kwargs))
        except ApiException as error:
            if missing and error.status == 404: return None
            raise OutcomeUnknown('Kubernetes API did not confirm this operation') from error
        except Exception as error:
            raise OutcomeUnknown('Kubernetes API response unavailable') from error

    def namespace_uid(self):
        return self._call(self.core.read_namespace,self.namespace)['metadata']['uid']

    def queue_exists(self, name):
        queue = self._call(self.custom.get_namespaced_custom_object,'kueue.x-k8s.io',self.queue_api_version,
                           self.namespace,'localqueues',name,missing=True)
        if queue is None: return False
        if queue.get('metadata',{}).get('name') != name or queue.get('metadata',{}).get('namespace') != self.namespace:
            raise OutcomeUnknown('Kueue queue identity mismatch')
        return True

    def create_job(self, document):
        return self._call(self.batch.create_namespaced_job,self.namespace,document)

    def get_job(self, name):
        return self._call(self.batch.read_namespaced_job,name,self.namespace,missing=True)

    def delete_job(self, name, uid):
        from kubernetes.client import V1DeleteOptions,V1Preconditions
        self._call(self.batch.delete_namespaced_job,name,self.namespace,
                   body=V1DeleteOptions(propagation_policy='Foreground',preconditions=V1Preconditions(uid=uid)),missing=True)

    def owned_pods(self, uid):
        # Owner references remain authoritative even if a pod's selector labels
        # were changed. Bound the entire scan and retain uncertainty on overflow.
        result,continuation = [],None
        deadline = time.monotonic()+25
        for _ in range(100):
            if time.monotonic() >= deadline: raise OutcomeUnknown('Kubernetes pod inventory time bound exceeded')
            page = self._call(self.core.list_namespaced_pod,self.namespace,limit=500,_continue=continuation)
            for pod in page['items']:
                if any(owner.get('uid') == uid for owner in pod.get('metadata',{}).get('ownerReferences',[])):
                    result.append(pod)
            continuation = page.get('metadata',{}).get('continue')
            if not continuation: return result
        raise OutcomeUnknown('Kubernetes pod inventory exceeds the bounded scan')
