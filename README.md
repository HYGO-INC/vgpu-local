# vgpu-local

A small open-source runtime for using **your own GPUs** at home, in an office,
or in a private cloud. Optional vgpu.com management does not change where the
work runs. A vgpu.com account and Kubernetes are both optional.

**Status: experimental.** The starter inspects this computer and existing local
engines. Optional modules add an authenticated local console, background ComfyUI
execution, outbound account commands, interruption exchange and Kubernetes/Kueue.
The runtime passes controlled-engine/process/browser tests; real ComfyUI GPU
qualification, browser pairing and production dashboard integration remain.

**Release timing:** public release is planned for when vgpu.com is ready. Current
development stays local; no new packages, images or releases are published yet.

## Start with the minimum download

From this checkout, with [uv](https://docs.astral.sh/uv/):

```sh
uv tool install --python 3.12 .
vgpu-local doctor
```

The default package has **no third-party runtime dependencies**. It does not
install Kubernetes, Docker, PyTorch, CUDA, models, provider SDKs, a database server
or a desktop browser. `uv` obtains Python 3.12 if needed, without replacing your
system Python. Python is an additional download and is not included in the
package-size measurement. `doctor` invokes an installed `nvidia-smi` when available;
`doctor --no-probe` skips that invocation. It makes no network requests.

The version request is explicit because `uv tool` does not use this checkout's
Python pin as its interpreter-selection default. If the executable directory is
not on PATH, run `uv tool update-shell` and open a new terminal. See
[uv tool Python selection](https://docs.astral.sh/uv/concepts/tools/#python-versions).
The package has not been published to PyPI; an unqualified registry install is
not the current installation route.

If an engine is already running on this computer, inspect it without installing
another copy or pulling a model:

```sh
vgpu-local engine status --kind comfyui --endpoint http://127.0.0.1:8188
vgpu-local engine status --kind ollama --endpoint http://127.0.0.1:11434
vgpu-local engine status --kind vllm --endpoint http://127.0.0.1:8000
```

These read-only probes recognize the API response, not successful GPU inference.
Choose an engine/model only when needed; drivers and model weights may still be
substantial downloads. Signed native installers and browser-guided optional
downloads are planned, not already distributed.

## Two ways to use the same local runtime

| Mode | Management | Work runs on | Kubernetes |
|---|---|---|---|
| Standalone | Local CLI and loopback console | Your GPUs | Optional |
| Connected | Outbound command API; production dashboard integration pending | Your GPUs | Optional |

Connecting never enables paid rentals, output uploads or renting your GPUs to others.
Standalone mode does not require the hosted platform's account, billing,
database or orchestration services. See [architecture](docs/architecture.md).

Install extras only for features you choose:

```sh
# From the checkout; retain already chosen extras when changing this selection.
uv tool install --python 3.12 --reinstall '.[cloud]'
# Optional local console; use '.[runtime,cloud]' to also manage it through an account.
uv tool install --python 3.12 --reinstall '.[runtime]'
# Existing cluster support; optionally combined as '.[cloud,kubernetes]'.
uv tool install --python 3.12 --reinstall '.[kubernetes]'
```

- `cloud`: scoped outbound enrollment and credential renewal; see
  [cloud connection](docs/cloud-connection.md). Interactive browser login is pending.
- `runtime`: detached local program, authenticated console and identified ComfyUI
  execution. Closing every browser does not cancel a job. See [runtime setup](docs/local-runtime.md).
- `control`: durable interruption notices and acknowledgements; see
  [interruption exchange](docs/interruptions.md).
- `kubernetes`: existing Kubernetes/Kueue integration. It installs the Python
  client, **not a cluster**, drivers or GPU allocator. See [optional cluster setup](docs/local-setup.md).

## Optional GPU pools

Cluster integration inventories allocatable resources and queues jobs needing
one or more GPUs on one worker. Existing MIG resource names are supported.
It does not merge VRAM across cards. Kubernetes/Kueue owns cluster scheduling;
there is no competing GPU scheduler here.

The [recoverable cluster backend](docs/kubernetes-backend.md) retains create
receipts, adopts identified Jobs after lost replies and waits for pod teardown.
The [reclaim command](docs/interruptions.md#local-kubernetes-reclaim) connects
workload readiness/deadlines to cleanup. These paths have offline and client-model
tests; actual GPU-cluster installation remains unqualified.

HAMi setup, multi-node jobs, DRA and VM integration remain optional future work.
See [GPU modes](docs/gpu-modes.md). A single computer does not need any of these.

## Optional workload recipes

Recipes are separate development artifacts, not starter dependencies:

- [FastVideo](recipes/fastvideo/README.md): two short clips measured on a 4090.
- [FramePack](recipes/framepack/README.md): a short clip passed with substantial
  host-memory pressure; read its measured requirements before running.
- [LongLive](recipes/longlive/README.md): two short clips passed; the longer run
  failed frame-count qualification and is not a supported long-video recipe.

No supplier adapters, spending policy or hosted financial services are included.
Optional cloud capacity is a separate service-side concern.

## Development

```sh
pnpm install --frozen-lockfile
uv sync --locked
pnpm check
pnpm release:build
pnpm release:check
```

Development tooling is larger than the end-user installation. Edit public
contracts in `protocol/*.tsp`, run `pnpm generate`, and retain the cross-language
fixtures. The common backend envelope retains existing provider identifiers for
wire compatibility; those identifiers do not install or implement supplier code.
Hosted spending policy is not part of this package.

Apache-2.0. Local use needs no private repository or package registry.

## Release artifacts

`release:build` builds both the wheel and source distribution in a fresh staging
directory, verifies their contents against this runtime, then replaces the local
artifacts. Source packages exclude development history, recipes, tests and cloud
supplier implementation. `release:check` rejects stale or unexpected archives,
changed source bytes and mandatory runtime dependencies. CI runs both checks.
Building does not publish. Any future upload must use the explicit verified
filenames; do not upload an unchecked `dist/*` glob.
