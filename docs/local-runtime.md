# Local background runtime

Install the small starter first; it has no required third-party dependencies.
Add the console only when you want to run an existing local ComfyUI installation:

```sh
uv tool install --python 3.12 ".[runtime]"
vgpu-local runtime init --engine http://127.0.0.1:8188
vgpu-local runtime add-recipe --id my-video --title "My video" --workflow workflow-api.json
vgpu-local runtime start
vgpu-local runtime open
```

Run the install command from this checkout. It does not install an engine,
models, Docker or Kubernetes. Until the
package is published, use `uv tool install --from <local-wheel-path> vgpu-local`
for the starter, or `uv tool install "<local-wheel-path>[runtime]"` for the console.
ComfyUI must already be running. Export a workflow in its **API format**, inspect
it and approve it through `add-recipe`. Custom nodes run with the engine's local
permissions; importing a workflow is an owner decision, never a hosted command.

`runtime start` launches a detached program. `runtime serve` runs in the foreground
for an existing OS supervisor. `runtime open` authorizes a browser using a random
local token in a URL fragment; the page removes it immediately. It is not sent in
HTTP URLs or logs. The listener is explicitly `127.0.0.1`, with strict Host/Origin
checks, bearer authentication, no CORS, a restrictive CSP and fixed static routes.
Local state is protected by user-directory permissions (explicit ACL on Windows).
Do not share that directory or launch URL. Local privileged processes remain trusted.

The same job continues when every browser closes. `runtime stop` stops the control
program, not ComfyUI or its jobs. Starting again reconciles their saved identities.
The computer and engine must remain running. Model checkpoint restoration and
engine restart recovery are separate features.

## Optional start at login

Off by default. `vgpu-local runtime autostart enable` starts the runtime each time
you sign in; `disable` removes it and `status` shows whether it is set. It uses your
own account's startup mechanism, so no administrator rights are needed: a Run
registry entry on Windows (launched without a console window), a systemd user
service on Linux and a launchd agent on macOS. The runtime's lock still allows one
instance per state folder, so a manual `runtime start` alongside it is harmless.
It starts only this control program; ComfyUI or other engines need their own setup.

## Results and recovery

The SQLite journal is written **before** an engine create. The connector includes
an execution ID, random correlation value and approved recipe hash in ComfyUI's
queue metadata. A lost reply or control-program crash never triggers a second
submission: queue/history inspection adopts the identified job. A missing or
pruned record stays uncertain. Keep this journal; replacing it loses recovery
evidence. The program refuses missing configuration or a missing database.

The console shows the most recent 500 jobs; older jobs remain in SQLite and are
readable by ID. All active jobs are reconciled regardless of age. Results shown
are engine metadata, not downloaded media. Model/output files stay with ComfyUI.
One runtime owns its state directory using an OS file lock.

Cancellation uses the modern, job-specific `/api/jobs/{id}/cancel` route. Older
engines without this route cannot be canceled here; there is no global interrupt
fallback. Lost cancellation replies are reconciled. If a canceled queued job has
no retained history, its final outcome can remain uncertain; the UI must not
present a missing record as successful cancellation.

The source-reviewed ComfyUI API is commit
`b26625f23a888367b92153b28d93e159e83e677b` in
[ComfyUI server.py](https://github.com/Comfy-Org/ComfyUI/blob/b26625f23a888367b92153b28d93e159e83e677b/server.py).
Caller-chosen prompt IDs are **not** upstream idempotency keys. Other releases
require qualification. Automated tests use a controlled HTTP fixture matching
these queue/history/create/cancel routes. A real GPU execution is also qualified
below; it does not qualify every workflow or cancellation path.

## Optional account management

Install `[runtime,cloud]`, enroll using the existing `cloud connect` command,
then explicitly supply its config when initializing a new runtime:

```sh
vgpu-local runtime init --engine http://127.0.0.1:8188 --cloud-config /path/to/cloud.json
```

The runtime polls outward to the scoped `/connection/exchange` endpoint. No
website-to-localhost connection, incoming firewall rule or Kubernetes cluster is
required. Standalone mode makes no account requests. Connected mode retains the
local console and continues local work during account/network failures.

The running program checks its credential on startup and hourly, and renews it
when one day or less remains. Lost renewal replies and restarts recover using the
same durable key/rotation identity. Network failures back off to at most one retry
per minute without stalling local work. An expired or revoked connection needs
explicit enrollment again; it is never recreated automatically. A sleeping or
stopped computer cannot renew a key, so an extended offline period can require
reconnection. The server controls expiry; credentials stay in the OS store.

Commands can start only an already approved recipe ID and content hash, or cancel
an identified job. The connected runtime tells the account which recipes it may
start: the first 100 approved recipes by ID, as ID, title and content hash only.
It sends that list only when it differs from the copy the server reports holding.
Commands bind tenant, project, site, execution, generation, expiry
and retry identity. They cannot upload workflows, run arbitrary shell commands,
rent GPUs or transfer output files. Durable receipts and minimal state reports
replay after disconnection. The server must authorize every user command and
validate the site's expiring/revocable key on every exchange. Reports are site
observations, not trusted financial metering. Enrollment identity changes require
an explicit new runtime, never silent reassignment of an old report outbox.

Revocation blocks future delivery; an already accepted command is not remotely
erased. The local owner retains cancellation. This release has no device-login
browser flow or production account dashboard integration.

## Qualification

Run `pnpm check` for cross-language contracts, loopback boundaries, durable replay,
lost engine replies, actual process restarts and detached CLI lifetime. The
[shared security corpus](../tests/fixtures/local-services/README.md) is pinned
under test fixtures and exercised over the real HTTP listener. It checks exact
Host/Origin handling, duplicate headers, bearer authentication and forwarded
header rejection. The upstream commit and hashes are in `upstream.json`; update
the canonical corpus in shared and use its export script rather than editing
these copies. The fixture data adds no runtime dependency or download.

The browser
group is development-only. Use your own installed Chrome, never a signed-in user
session:

```sh
uv run --locked --group browser python scripts/qualify-runtime-browser.py --chrome /path/to/chrome --output /path/to/evidence
```

This closes the entire browser during a fixture job, verifies the same result on
reopen, and denies loopback permissions for a separate hosted-page fixture.
Its report distinguishes that transport check from production website qualification.

### Real ComfyUI render, 7 October 2026

An isolated loopback ComfyUI 0.26.0 at source commit
`b0ec19804ff68bfafb2729fe1c83e5f451a6061e`, using its existing embedded Python
3.11.9 / PyTorch 2.6.0+cu124 environment, completed a FLUX.1-dev FP8 workflow on
an RTX 4090 (24,564 MiB). The control program used its separate Python 3.12
environment. No models or engine were installed by vgpu-local.

The owner-approved core-node workflow generated one 512x512 image in eight Euler
steps, with custom/API nodes disabled. Qualification dropped the actual engine's
successful submission reply, closed all test-browser tabs, and killed/restarted
the runtime while the engine was running. The same execution completed and its
result appeared when Chrome 153.0.8010.48 reopened. A forwarding counter measured
exactly one `/prompt` submission. Engine-reported execution was 19.26 seconds;
22.047 seconds included browser/runtime orchestration. These are single-run
measurements, not a performance benchmark.

This qualifies one real image workflow and runtime recovery while ComfyUI stays
alive. Long-video workflows, model checkpoint restoration after engine/OS failure,
GPU-backed cancellation, other hardware/versions and production account UI remain
separate qualifications. Model/output files stayed local.
