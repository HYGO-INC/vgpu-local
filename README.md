# vgpu-local

Open-source tools for GPU pools at home, in an office, or in a private cloud,
with an optional connection to vgpu.com for additional capacity.

**Status: experimental engineering foundation.** Local inventory, native queued
job submission, provider adapters, an offline fault simulator, scoped cloud
enrollment/renewal, and a native interruption controller/file transport are
implemented. Automatic overflow execution, the local console and capacity
contribution still require integration and qualification.

**Release timing:** public release is planned for when the vgpu.com site is ready.
Development stays local while the remote's visibility does not match that policy;
no new code, packages, images or releases should be published before then.

Local tools require no vgpu.com login or private packages. Importing the library,
rendering jobs and running the tests make no provider calls. Live cluster access
requires an explicit kubeconfig context; provider SDK calls require credentials.

## Try it without a GPU or cloud account

Install Python 3.12 and [uv](https://docs.astral.sh/uv/), then:

```sh
git clone https://github.com/HYGO-INC/vgpu-local.git
cd vgpu-local
uv sync --locked
uv run vgpu-local inventory --nodes-json examples/nodes.json
uv run vgpu-local capabilities runpod
uv run vgpu-local render-job --name gpu-check --image nvidia/cuda:12.8.1-base-ubuntu22.04 -- nvidia-smi
```

The sample inventory includes 4090, 5090 and MIG resources. It is fixture data,
not a hardware test. Rendering emits a suspended Kubernetes Job; it does not
start a container. Choose and pin a workload image qualified for your actual GPU.

For a real site, follow [local setup](docs/local-setup.md). With a configured
Kubernetes/K3s cluster, NVIDIA device allocation and Kueue:

```sh
uv run vgpu-local inventory --context my-local-cluster
uv run vgpu-local submit-job --context my-local-cluster --name gpu-check --image nvidia/cuda:12.8.1-base-ubuntu22.04 -- nvidia-smi
```

`submit-job` checks that the named LocalQueue exists and uses `kubectl create`.
Kueue admits the suspended Job. A timeout or an already-existing job must be
reconciled by its name before issuing a new submission; no automatic resubmit is
performed. This tool uses your selected kubeconfig permissions.

## Pooling and partitioning

- Pool GPUs across hosts for jobs and replicas using Kubernetes and Kueue.
- Run larger models through application-supported partitioning. Pooling cards
  does not create a GPU with transparently combined VRAM.
- Request an existing MIG resource with `--gpu-resource nvidia.com/mig-1g.10gb`.
  MIG profiles must already exist on supported hardware.
- Qualify software sharing for trusted workloads separately. Neither time slicing
  nor a software memory quota promises hardware tenant isolation.

Inventory reports **allocatable resources, not currently free GPUs**. Kubernetes
owns placement and admission. Multiple consumer cards and supported enterprise
partitions can coexist in a site without pretending they have identical capabilities.

`--gpus N` requests N devices on **one worker**, even if the cluster has many
workers. Distributed JobSets, HAMi sharing setup, DRA claims, VM pass-through and
multi-GPU video recipes remain planned. See the [support matrix and engine choices](docs/gpu-modes.md).

## Providers and overflow

The [pinned FastVideo recipe](recipes/fastvideo/README.md) has passed a small
single-4090 video qualification, with cold-load time, warm generation time and
memory measured separately. It is independent of the cloud adapters and does not
claim long-video or multi-GPU qualification.

The Python library includes Vast/Runpod adapters through SkyPilot and a Theta
GPU Node API v1 client. These are tested with injected SDK/HTTP transports;
live supplier qualification is still pending. See [provider boundaries](docs/providers.md).

`examples/local-only.json` disables cloud use. The overflow policy library checks
budgets, regions, allowed providers, data-export readiness and local execution
fencing. It is an eligibility check, **not an automatic submitter or an atomic
spending reservation**. The separate [cloud connection](docs/cloud-connection.md)
enrolls and renews a scoped installation without enabling spending or contribution.
See [architecture and remaining work](docs/architecture.md).

The [interruption protocol](docs/interruptions.md) provides versioned warnings,
acknowledgement/readiness receipts, cancellation, explicit extension grants and a
Linux file channel, with `vgpu-local interruption` commands for the operator relay
and workload responses. Reclamation and billing remain external authority boundaries.

## Development

```sh
# Node version: .node-version; pnpm version: package.json
pnpm install --frozen-lockfile
uv sync --locked
pnpm check
```

Edit `protocol/backend.tsp`, `federation.tsp` or `interruptions.tsp`, then `pnpm generate`. TypeSpec generates OpenAPI 3.1,
JSON Schema, TypeScript types and Python models. A common fixture set is checked
against JSON Schema, Ajv and Python/Pydantic. Generated files must remain in sync.
The protocol is experimental and defines no deployed HTTP routes.

Tests cover durable operation receipts, concurrent creates, lost replies,
preemption with/without warning, stale observations, failed teardown, duplicate
delivery and overflow restrictions. They require neither GPUs nor paid services.

Apache-2.0. This repository contains the public local product; it does not require
the hosted service's source, commercial settings or account infrastructure.
