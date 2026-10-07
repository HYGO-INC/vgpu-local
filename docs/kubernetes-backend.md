# Kueue execution adapter

`KubernetesBackend` connects the public backend interface to native Kubernetes
Jobs. It reuses the existing suspended Kueue manifest builder, a durable receipt
store and the official Kubernetes Python client. Kubernetes and Kueue continue to
own GPU admission, placement, pod lifecycle and eviction. This is an execution
adapter, not another scheduler or a cluster installer.

Install the optional pinned client with `uv sync --locked --extra kubernetes`.
Use Kubernetes 1.34 or later: the adapter explicitly selects the stable
`podReplacementPolicy: Failed`, one completion, one parallel pod and zero retries.
GPU drivers, device plugins, RuntimeClass, namespace, Kueue and LocalQueue must
already exist. Configure the served Kueue API version (`v1beta1` or `v1beta2`)
explicitly. No qualification here installs or mutates a real cluster.

```python
from vgpu_local.journal import Journal
from vgpu_local.kubernetes_api import KubernetesAPI
from vgpu_local.kubernetes_backend import GpuClass, KubernetesBackend

api = KubernetesAPI(context="my-home-cluster", namespace="gpu-jobs")
backend = KubernetesBackend(
    Journal("controller.sqlite"), api,
    account_id="home-site", namespace="gpu-jobs",
    namespace_uid="PIN_THE_EXISTING_NAMESPACE_UID", queue="gpu", region="home",
    gpu_classes={"RTX4090": GpuClass("nvidia.com/gpu", "NVIDIA-GeForce-RTX-4090")},
)
# request is a validated BackendRequest with this account, region and GPU class.
# backend.provision(request), backend.observe(request), backend.release(request)
# api.close() when the worker stops.
```

The namespace UID pins the execution domain across restarts and rejects a deleted
and recreated namespace. The kubeconfig context is explicit, TLS verification is
required, request retries are disabled, and each SDK request has connect/read
timeouts. Credentials stay with the operator; the pod gets no service-account
token or operator kubeconfig. Allow only the selected namespace's Job create/read/
delete, Pod list, LocalQueue read, and read of that named Namespace. A namespace
is not sufficient isolation for arbitrary hostile workloads: this adapter accepts
owner workloads only.

The site maps advertised GPU class IDs to exact extended resources and product
selectors. An existing MIG resource can be configured explicitly. It never creates
MIG partitions, enables HAMi or combines VRAM. The adapter rejects spot and
multi-node requests. CPU/memory admission defaults are tolerated while the accepted
GPU request and workload command remain fixed.

Before create, the journal commits one deterministic name and the full accepted
manifest. A lost reply is adopted only from a matching Job, including its scope,
intent annotations, immutable workload fields and UID. A missing uncertain create
remains uncertain; it is never reissued. Retain the journal through all outstanding
allocations. Catalog changes do not rewrite an existing manifest or prevent its
cleanup. Changes to the execution binding need the old binding retained for
cleanup, rather than rebinding old operations to another namespace or queue.

Job `active` counts include pending pods, so running status requires an observed
running workload container. Only `Complete` and `Failed` are terminal results;
`FailureTarget` and `SuccessCriteriaMet` are not completion. Workload completion
remains separate from resource cleanup. Deletion uses foreground propagation and
the recorded UID precondition. The adapter confirms release only after the Job is
absent and a bounded Pod inventory contains no references to that UID. Timeouts,
permission errors, changed identity and scan overflow retain uncertainty.

The adapter creates one Job object per operation. Kubernetes can still execute a
workload more than once in unusual failure cases. Applications and artifact
publication must therefore tolerate retries and enforce their own write fencing;
this is not exactly-once execution or proof that a partitioned GPU host stopped.

Offline tests inject lost create/delete replies, changed namespaces and jobs,
concurrent retries, stale observations and delayed pod cleanup. Run
`uv run --locked --extra kubernetes python scripts/qualify-kubernetes.py` to verify
the installed client's wire models, deletion preconditions and bounded calls
without reading a kubeconfig or contacting a cluster. Real Kueue admission,
device-plugin allocation, node failure and GPU execution remain unqualified.

Sources: [Kubernetes Job semantics](https://kubernetes.io/docs/concepts/workloads/controllers/job/),
[foreground deletion](https://kubernetes.io/docs/concepts/architecture/garbage-collection/),
[official Python client v35](https://github.com/kubernetes-client/python/tree/v35.0.0).
