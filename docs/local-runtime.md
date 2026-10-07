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
The computer and engine must remain running. Automatic start after login/reboot,
model checkpoint restoration and engine restart recovery are separate features.

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
require qualification. Current tests use a controlled HTTP fixture matching
these queue/history/create/cancel routes; they do not prove a real GPU render.

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

Commands can start only an already approved recipe ID and content hash, or cancel
an identified job. They bind tenant, project, site, execution, generation, expiry
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
lost engine replies, actual process restarts and detached CLI lifetime. The browser
group is development-only. Use your own installed Chrome, never a signed-in user
session:

```sh
uv run --locked --group browser python scripts/qualify-runtime-browser.py --chrome /path/to/chrome --output /path/to/evidence
```

This closes the entire browser during a fixture job, verifies the same result on
reopen, and denies loopback permissions for a separate hosted-page fixture.
Its report distinguishes that transport check from production website qualification.
