# GPU modes and implementation status

Reviewed 6 October 2026. Project documentation describes possible integrations;
it is not evidence of a hardware test or a feature implemented in this repository.

| Function | Current status |
|---|---|
| Minimal installation without Kubernetes or an account | Implemented; no third-party base dependencies |
| Inspect local GPUs and an existing local engine | Implemented; read-only, no downloads |
| Website-managed standalone GPU jobs | Planned; scoped enrollment exists, dispatch does not |
| Inventory a configured Kubernetes/K3s GPU pool | Implemented; reports allocatable resources, not free GPUs |
| Submit a queued single-Pod job | Implemented; requires an installed NVIDIA allocation stack and Kueue |
| Request N GPUs on one worker | Implemented with `--gpus N`; the application must use the devices |
| Request an existing MIG instance | Implemented with `--gpu-resource`; partition creation is external |
| Bootstrap a home site automatically | Planned; current setup is manual |
| Run one coordinated job across multiple workers | Planned; no JobSet/rendezvous renderer yet |
| Install HAMi and account for GPU shares | Planned; no fractional memory/compute request renderer yet |
| Allocate with DRA ResourceClaims | Planned; no claim renderer yet |
| Pass through GPUs or configure NVIDIA Multi-vGPU in a VM | Planned; no hypervisor integration yet |
| Distributed video/model recipe catalog | Optional short-video recipes measured on one 4090; distributed execution unqualified |
| Automatic cloud overflow | Separate hosted feature; supplier adapters and spending policy are absent here |

## Multiple devices do not become one larger device

NVIDIA Multi-vGPU attaches multiple vGPU devices to one VM. Model sharding or
offload is still required when a single-device workload does not fit in one
device's memory. Multiple GPUs in a container have the same application-level
requirement. Memory replicated by each worker and communication workspace reduce
the memory available for useful model/activation shards.
[NVIDIA Multi-vGPU](https://docs.nvidia.com/ai-enterprise/release-7/latest/infra-software/vgpu/features/multi-vgpu-p2p.html).

`--gpus 2` requests two devices on one node. Two computers with one card each
cannot satisfy this Pod. Distributed workloads will need a separate controller
and recipe, with explicit worker counts and a tested network topology.

MIG divides a supported GPU into smaller hardware partitions. It does not increase
the memory available to a large single-GPU job. Discover exact device/profile
support; consumer 4090/5090 pooling does not enable MIG.
[MIG hardware matrix](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/latest/supported-gpus.html).

## Sharing and scheduling profiles

Use [Project-HAMi/HAMi](https://github.com/Project-HAMi/HAMi), the maintained
successor to `4paradigm/k8s-vgpu-scheduler`, for the planned trusted sharing profile.
HAMi's CUDA controls are not a hardware isolation boundary. Its current
[FAQ](https://project-hami.io/docs/faq) and
[K3s example](https://project-hami.io/tutorials/labs/hami-isolation-k3s) describe
the distinction. Qualify 4090 and 5090 driver/framework combinations separately.

Retain Kueue admission and one device allocator per pool. Use HAMi's documented
[quota transformation](https://project-hami.io/docs/next/userguide/kueue/how-to-use-kueue)
to account for total memory/compute when requests are expressed per device.
Virtual-share counts are not physical GPU counts. Inventory must distinguish them.

[HAMi-DRA](https://github.com/Project-HAMi/HAMi-DRA) is a future allocation option.
Its reviewed upstream documentation says its Pod conversion does not yet cover
parent-created Kueue Workloads such as `batch/v1` Jobs. Qualify the parent resource
and ResourceClaimTemplate path before changing our Job renderer. DRA API support
alone does not establish that an entire controller chain works.

[KAI Scheduler](https://github.com/kai-scheduler/KAI-Scheduler) and Volcano are
alternative scheduler profiles to evaluate for appropriate workloads. Ray is a
distributed application runtime within an admitted allocation. Existing Slurm
sites can have a future adapter. None automatically partitions an unchanged model;
multiple independent admission owners must not double-allocate the same pool.

[TensorFusion](https://github.com/NexusGPU/tensor-fusion#-license) publishes its
controller and fractional vGPU components as open source, but states that the
advanced GPU-over-IP implementation is not fully open sourced. It is an optional
comparison, not a mandatory component of local operation.

## Large video and hybrid execution

Qualify [Diffusers](https://huggingface.co/docs/diffusers/main/training/distributed_inference)
context parallelism and component placement, and
[xDiT](https://github.com/xdit-project/xDiT) against the actual video model.
[SGLang Diffusion](https://github.com/sgl-project/sglang/blob/main/docs/docs/sglang-diffusion/parallelism.mdx)
and [vLLM-Omni](https://docs.vllm.ai/projects/vllm-omni/en/latest/user_guide/diffusion/parallelism/sequence_parallel/)
are additional engine candidates. Support for a model does not imply support for
every parallelism, offload or checkpointing mode.

Measure resolution/frame count, output quality, time, per-rank memory, startup
and communication for each recipe. Extra GPUs do not remove a model's temporal
context constraints. Independent jobs can use different sites; a tightly coupled
multi-GPU job should stay within one measured, compatible placement domain.
Cloud overflow places a whole job or routes excess inference, with explicit
artifact export, budgets and ownership handoff. It does not merge home and cloud
VRAM. Supplier charges continue until the billed resource is released.
