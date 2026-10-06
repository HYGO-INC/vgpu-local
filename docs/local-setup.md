# Local GPU site setup

Use Linux GPU worker nodes and an existing Kubernetes cluster or a K3s site.
Windows/macOS can run the management CLI; that does not establish GPU-worker
support on those operating systems. No installer in this repository changes
drivers, partitions devices or enrolls the current computer automatically.

## Site components

1. Install the driver matching the actual GPU and operating system. Verify each
   card with `nvidia-smi` and a compatible CUDA container. Treat 4090 and 5090
   driver/runtime/image qualification as separate profiles.
2. Install Kubernetes/K3s and the NVIDIA Container Toolkit. For an existing
   operator-managed driver, avoid a second driver manager. K3s must detect the
   NVIDIA runtime; the default renderer requests `runtimeClassName: nvidia`.
3. Install one qualified GPU allocator for each pool. The NVIDIA device plugin
   supplies whole-device resources and existing MIG instances. Use GPU Operator
   on supported configurations when it owns the driver/device stack.
4. Install a pinned Kueue release compatible with your Kubernetes version.
   Create a ResourceFlavor, ClusterQueue with explicit quotas, and a `local-gpu`
   LocalQueue in namespace `vgpu-local`. Use the upstream
   [single-cluster configuration](https://kueue.sigs.k8s.io/docs/tasks/manage/administer_cluster_quotas/)
   and [Job integration](https://kueue.sigs.k8s.io/docs/tasks/run/jobs/).
   Do not let an independent autoscheduler admit the same jobs.
5. Run `vgpu-local inventory --context NAME`. It shows registered GPU resource
   names and node readiness. Queue quotas and inventory are not current free capacity.
6. Submit a compatible test workload with `submit-job`. Inspect the Kubernetes
   Job, Kueue Workload admission, pod logs and GPU activity before enabling user jobs.

Driver/runtime setup references: [K3s NVIDIA runtime](https://docs.k3s.io/advanced),
[NVIDIA device plugin](https://github.com/NVIDIA/k8s-device-plugin),
[Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).

## Heterogeneous GPUs and multiple sites

Use ResourceFlavors, node labels and queue quotas for 4090, 5090 and enterprise
devices. `--gpu-product` adds a device-plugin product-label selector. Do not add
memory capacities together and claim that a single unmodified CUDA program can
allocate the total. For multi-GPU inference, qualify a vLLM/Ray partitioning recipe;
for training, qualify a distributed training recipe and its network topology.
The current CLI emits single-Pod Jobs; multi-node JobSets and serving controllers
are planned integrations.

Independent offices keep independent clusters. An overlay network does not make
a slow WAN suitable for tensor-parallel traffic. Group jobs at the admission layer,
and keep a tightly coupled model-parallel gang in a qualified placement domain.
[vLLM parallelism](https://docs.vllm.ai/en/latest/serving/parallelism_scaling/).

## Enterprise partitions and trusted software sharing

MIG is available only on supported hardware/profiles. Provision its profiles with
the qualified NVIDIA tooling before using a `nvidia.com/mig-*` resource. Changing
profiles may require draining workloads and is never done implicitly by this CLI.
The product label “enterprise” alone does not prove MIG support.
[MIG hardware](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/supported-gpus.html).

For consumer devices, use whole-device scheduling by default. HAMi or device-plugin
time slicing may improve utilization of trusted workloads after qualification.
Time slicing does not guarantee separate memory or fault domains. Do not install
competing device allocators over the same GPUs, or advertise software shares as MIG.
[HAMi](https://project-hami.io/),
[NVIDIA time slicing](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/gpu-sharing.html).
