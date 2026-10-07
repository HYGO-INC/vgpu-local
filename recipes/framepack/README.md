# FramePack on a local GPU

The launcher uses an isolated, locked Python environment and an immutable
upstream checkout. It runs FramePack's original image-to-video worker headlessly;
it does not start a public Gradio server or change the host CUDA/Python install.
Source/model revisions, prompt and generation settings are in `lock.json`.

Choose a data directory with room for about 43 GB of model weights, the Python
environment and output. `uv`, Git and Python 3.10+ are required. The environment
itself uses Python 3.10 and PyTorch 2.6.0+cu126.

```sh
python recipes/framepack/run.py setup --data-directory /path/to/framepack
python recipes/framepack/run.py download --data-directory /path/to/framepack --timeout-seconds 7200
python recipes/framepack/run.py preflight --data-directory /path/to/framepack
python recipes/framepack/run.py benchmark --data-directory /path/to/framepack --input-image /path/to/input.png --seconds 5 --runs 1
```

Downloads use a separately locked Hub client without inherited Hub credentials.
Model loading is local/offline. A wall-time limit terminates the owned process
tree; logs, sampled memory and output measurements stay in a timestamped folder.
Native Windows inference has **no hard host-memory limit**. Following the result
below, new benchmark runs require at least 48 GiB of available host RAM before
model loading. This is conservative admission headroom, not a proven upper bound
or a guarantee against exhaustion. Preflight does not load model weights.

## RTX 4090 measurement, 6 October 2026

One 24,564 MiB RTX 4090, driver 610.62, native Windows, 63.8 GiB total system RAM.
The input was the first frame from the separately measured FastVideo boat clip;
its hash is retained in [the raw result](evidence/rtx4090-5s.json).
Settings: 13B FramePack I2V, 25 steps, latent window 9, CFG 1, distilled guidance
10, TeaCache disabled, upstream memory-preservation setting 6 GB and CRF 16.
These differ substantially from the three-step FastVideo recipe.

| Measurement | Result |
| --- | --- |
| Complete MP4 | 832x480, 145 frames, 30 FPS, 4.83 seconds |
| Requested duration | 5 seconds; upstream rounds to four 36-frame sections plus the image |
| Generation and intermediate/final saves | 666.64 seconds (11.1 minutes) |
| Initial model-object construction | 4.72 seconds; deferred reads/transfers also occur during generation |
| Peak PyTorch allocated GPU memory | 19,154,924,544 bytes (17.84 GiB) |
| Sampled whole-board GPU peak | 23,014 MiB, including other processes |
| Sampled process resident peak | 37,978,853,376 bytes (35.37 GiB) |
| Lowest system available RAM | 146,911,232 bytes (140 MiB) |

All 145 frames decode; first, middle and last frames show the input boat/lake
scene with movement in the boat and water. This is a basic visual check, not a
quality benchmark. The process started with about 27 GiB available RAM and spent
145 of 643 roughly one-second samples below 1 GiB available. It completed, but
this was substantial host-memory pressure. The 48 GiB admission guard was added
after this run; the measured run predates it.

Do not use this configuration as the default for unattended jobs on this busy
64 GiB workstation. The run does not establish the upstream 6 GB GPU claim,
60-second performance, fixed total memory, 5090 support or multi-GPU scaling.
Upstream keeps generated-frame history in CPU memory, so bounded GPU context
does not establish bounded total memory. Longer runs need separate memory and
quality qualification. No automatic service registration is performed.

Upstream: [pinned source](https://github.com/lllyasviel/FramePack/tree/97fe5dbe06ac1f337ece08935b1076a35eefeeb9).
