# FastVideo on a local GPU

This recipe runs the upstream engine in an isolated, digest-pinned Docker image.
It changes no host Python/CUDA installation. It requires NVIDIA GPU access in
Linux Docker; the qualification below used Docker Desktop's WSL2 backend.

`lock.json` pins the image, upstream source and model snapshot. It selects Ray,
BF16 text-encoder weights, text-encoder CPU offload, three denoising steps and
video sparse attention (0.8 sparsity). These settings affect memory, performance
and quality; they are not a comparison against the original full-step model.

From the repository root, choose a data directory with at least 30 GiB free for
the model files, plus room for outputs. Docker's image storage is additional.
The host launcher needs Python 3.10+; the container supplies its own environment.

```sh
python recipes/fastvideo/run.py pull --data-directory /path/to/benchmark
python recipes/fastvideo/run.py preflight --data-directory /path/to/benchmark
python recipes/fastvideo/run.py download --data-directory /path/to/benchmark
python recipes/fastvideo/run.py benchmark --data-directory /path/to/benchmark --profile 480p --runs 2
```

Only the download step uses a network. Inference uses the exact cached snapshot
offline. No host credentials are mounted. Each run limits CPU to six cores and
host memory to 20 GiB with no additional swap, names its own disposable container,
records invocation status, and stops that container on timeout/interruption.
Default wall-time bounds are 30 minutes for GPU runs and two hours for download;
`--timeout-seconds` can set another explicit bound. A failed/stalled run is not
qualified merely because denoising finished: every expected MP4 must decode with
the requested frame count and dimensions.

## RTX 4090 qualification, 6 October 2026

One RTX 4090, 24,564 MiB, driver 610.62; PyTorch 2.12.0+cu126, FastVideo 0.2.1,
fastvideo-kernel 0.3.5, Ray 2.59.0. The pinned upstream VSA implementation ran on
SM 8.9; no custom kernel or driver was installed. Other host processes occupied
about 2,007 MiB before the successful 480p run.

| Measurement | Result |
| --- | --- |
| Output | Two 832x480 MP4s, 81 frames each at 16 FPS (about 5.1 seconds) |
| Model load from local cache | 247.66 seconds |
| First generation, including first-use costs and saving | 27.16 seconds |
| Second generation in the same loaded process | 17.12 seconds |
| Sampled whole-board GPU peak, including other processes | 18,846 MiB |
| Container memory peak, including page cache | 21,083,688,960 bytes (19.64 GiB) |
| Container limit | 20 GiB; no cgroup OOM or OOM-kill event |

Both clips were decoded. First, middle and last frames were inspected and show
the requested red boat, mountain lake and sunrise; this is a basic output check,
not a quantitative temporal-quality evaluation. The two runs use the same prompt
and seed. Results do not establish sustained throughput, concurrent serving,
long-video memory behavior, multi-GPU scaling or RTX 5090 performance.

Raw measurement records: [480p](evidence/rtx4090-480p.json),
[earlier small smoke](evidence/rtx4090-smoke-no-offload.json),
[environment preflight](evidence/preflight.json). The smoke used 256x448/17 frames,
no encoder offload and a 14 GiB host limit; its 7.98s/1.01s times are a different
configuration and must not be advertised as 480p performance.

## Failed configurations retained in the qualification record

- GPU-resident text encoder: the 480p run completed denoising, then produced no
  video for several minutes near 24,031 MiB whole-board use. It was stopped; the
  cause of the stall was not established.
- BF16 encoder CPU offload with a 14 GiB container: Ray terminated its worker at
  its host-memory threshold during model loading. Increasing this test's limit
  to 20 GiB allowed the two measured runs; little peak headroom remains.
- The engine's multiprocessing executor failed while returning a CUDA IPC tensor
  in this environment. Ray passed a small transfer check and the full recipe.
  This is not a claim that CUDA IPC is universally unsupported on WSL.

The four-minute cold load is materially larger than a warm generation. Use these
separate measurements when evaluating keeping a worker warm, model caches or
releasing capacity; a fast denoising benchmark alone does not predict cold-start
latency. GPU/host-memory admission must budget for the full recipe, not just its
model's nominal parameter size.

Upstream: [pinned FastVideo source](https://github.com/hao-ai-lab/FastVideo/tree/8b51380466a963692a8c0afa254417bfcc2ba8bc)
and [pinned model snapshot](https://huggingface.co/FastVideo/FastWan2.1-T2V-1.3B-Diffusers/tree/25e7ed7f41fd8ce2fdd108688c65e8caf0ce3aef).
