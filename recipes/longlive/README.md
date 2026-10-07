# LongLive 1.3B on a local GPU

This recipe uses the pinned upstream **LongLive 1.0 / Wan 2.1 1.3B** engine and
base/LoRA checkpoints. It is distinct from LongLive 2.0's GB200/NVFP4 measurements
and LongLive-Plug's larger models. No published benchmark is transferred to a
4090 without measurement.

The Linux Docker environment starts from a digest-pinned CUDA/FlashAttention
image and adds two hash-verified wheels. The exact source, model revisions and
generation settings are in `lock.json`; the source checkout stays unmodified.
Python 3.10+, Git, `uv`, Docker and an NVIDIA GPU available to Linux containers
are needed. Choose a data directory with at least 30 GiB for weights and outputs;
Docker image storage is additional.

```sh
python recipes/longlive/run.py setup --data-directory /path/to/longlive
python recipes/longlive/run.py download --data-directory /path/to/longlive --timeout-seconds 7200
python recipes/longlive/run.py preflight --data-directory /path/to/longlive
python recipes/longlive/run.py benchmark --data-directory /path/to/longlive --latent-frames 21 --runs 2
```

Each GPU run uses its own disposable container, GPU 0, six CPU cores and a 28 GiB
host-memory limit with no extra swap. Source/model mounts are read-only and the
container has no network. No host credentials are mounted. Model download uses
a separately locked Hub client without inherited Hub credentials. Wall-time
limits terminate the owned container or download process tree.

The harness injects the same BF16 text-encoder checkpoint on CPU before installing
upstream dynamic offload, avoiding the original constructor's temporary float32
GPU allocation. It uses safe, memory-mapped tensor checkpoint loading, enables
upstream infinite/relative attention and preserves the four denoising steps.
The generator, LoRA and VAE run on the GPU. PyAV saves frames because this pinned
environment no longer provides the older torchvision video-writing API. No model
layers or generation math are replaced.

Preflight checks FlashAttention against a small PyTorch reference and imports the
upstream pipeline; it does not load model weights or establish generation support.
Benchmark success requires every MP4 to decode at the requested dimensions,
frame count and FPS. Timings distinguish model loading, generation, and saving;
sampled GPU/process memory and cgroup peak/OOM counters are retained.

On 6 October 2026 two short clips passed on an RTX 4090: 21 latent frames decoded
to 81 frames at 832x480 and 16 FPS (5.0625 seconds). Initial loading took 80.78s;
generation took 19.28s then 17.87s, or 20.77s and 19.29s including saving. Peak
whole-board GPU memory was 18,715 MiB including unrelated host use; process RSS
peaked at 22.91 GiB and container memory at 27.02 GiB. No container OOM occurred.
The middle frame was visually inspected. This is not a real-time performance,
multi-GPU, 5090 or bounded-total-memory claim.

A longer run **failed qualification**. Requested 243 latent frames should decode
to 969 frames, but the MP4 contains 963. The pinned upstream
`utils/wan_wrapper.py::decode_to_pixel_chunk` divides this into 120/120/3 latent
frame chunks and resets the VAE cache before each; each yields `4*N-3` frames,
explaining the six-frame loss. Temporal continuity at those boundaries also
needs evaluation. Do not relax the validation or call this a qualified long-video
recipe. It reached 21,297 MiB whole-board GPU memory and 27.15 GiB container memory
without OOM. Generation time was not retained by the original failure path;
the harness now records output measurements before validating future runs.

`evidence/` preserves both measured results. The 60-second configuration remains
unsupported until decode continuity and requested frame counts are fixed and
qualified. Upstream returns the decoded video as a tensor, so bounded attention
alone does not imply bounded total output memory. Model weights, downloaded source,
Docker images and videos are not bundled with the initial local runtime.

Upstream: [pinned LongLive source](https://github.com/NVlabs/LongLive/tree/fb16a879f46e604df4a0ca48ce2bf45adfa90352/LongLive1.0).
