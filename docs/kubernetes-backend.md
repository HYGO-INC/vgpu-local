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

## Local command interface

Copy [the site configuration](../examples/kubernetes-site.json) and
[the job request](../examples/kubernetes-request.json), then set the actual
context, namespace UID, queue, GPU labels, qualified image and command. Site
configuration is operator-owned and separate from each workload request. The
local tenant/project/account identifiers need no vgpu.com account. The shared
request's price ceiling is unused by this local adapter; the example's positive
placeholder does not enable billing or cloud access.

```sh
uv run --extra kubernetes vgpu-local kubernetes validate --config site.json
uv run --extra kubernetes vgpu-local kubernetes init --journal operations.db
uv run --extra kubernetes vgpu-local kubernetes provision --config site.json --journal operations.db --account-id home-site --request job.json
uv run --extra kubernetes vgpu-local kubernetes observe --config site.json --journal operations.db --account-id home-site --request job.json
uv run --extra kubernetes vgpu-local kubernetes release --config site.json --journal operations.db --account-id home-site --request job.json
```

Initialization exclusively creates a new journal and makes no cluster calls.
Subsequent commands require an existing valid journal and never recreate it if
the file disappears. Back up and protect that file as operation recovery
evidence. Restore a missing journal for an existing site; initializing a new file
does not recover old operations. Validation is offline and checks only the
configuration shape, not whether the site exists or has available GPUs.

Re-use the unchanged request file and journal when observing an uncertain
operation. A second `provision` with the same identity reconciles the original;
it does not submit another Job. Reusing the identity with different intent is
rejected. Use a new operation ID only for a deliberately new workload. The CLI
performs one bounded API sequence per invocation. It does not supervise jobs in
the background or automatically clean up finished Jobs; call `release` and
observe until cleanup is confirmed. Hosted lifecycle automation uses this same
backend independently.

The older `submit-job` command remains a direct, name-based `kubectl create`
convenience without these durable receipts. Prefer the `kubernetes` commands for
recoverable operation. Neither command family provisions or joins GPU machines.

## Python interface

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
