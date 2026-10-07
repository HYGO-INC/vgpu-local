# Local execution with optional hosted management

The local product's purpose is using the owner's GPUs. It contains the smallest
useful runtime and public interoperability contracts. Hosted scheduling, supplier
adapters, pricing, spending policy, account services and billing belong to the
hosted product, not this distribution.

## Installation and execution

The initial package has no third-party dependencies. `doctor` inspects this
computer; `engine status` probes an explicit existing loopback engine. Neither
downloads anything. Engines, model weights and cluster support are chosen later.
Existing installations and model caches should be reused after compatibility
checks. No opaque install-all script runs at startup.

The same local execution layer serves two modes:

- **Standalone:** local CLI and, when implemented, a local browser console. No
  cloud account, hosted stack or Internet requirement for installed workloads.
- **Connected:** optional account pairing and vgpu.com management. The agent
  connects outward; the user's computer needs no public IP, forwarded port,
  cluster, Cloudflare account or cloud database.

Kubernetes/Kueue is an optional local-pool integration in either mode. Account
ownership is unrelated to whether a GPU pool needs a cluster. An unconnected
user is not required to install the hosted platform.

## Public boundary

Keep local inventory, engine connectors, local execution/recovery receipts,
interruption handling, optional pool integration, minimal local UI and the thin
account-connection client here. Keep tests and necessary build/install tooling.
Do not bundle engines or weights in the starter.

Supplier backends and budget/overflow decisions have moved out. Existing backend
provider identifiers remain in the shared envelope to preserve compatibility,
but there is no Vast, Runpod or Theta implementation in this package. No provider
credential is required. Protocol identifiers are not enabled capabilities.

## Authority and disconnection

The local owner chooses permitted engines, GPU allocation, filesystem locations,
workload recipes, availability and remote control. Pairing does not authorize
arbitrary remote shell commands, data upload, spending or capacity contribution.
Future commands must bind site, project, execution ID, revision, expiry and retry
identity; only explicitly installed/approved recipes may be remotely launched.
The agent rejects replay, stale generations and mismatched scopes.

Local execution receipts survive a lost connection. Accepted local work follows
its local policy; a website outage must not turn it into paid cloud work. Revoke
disables future hosted commands, while the owner retains local cancellation.
Account tokens stay in the OS credential store. The local engine or Docker socket
must not be exposed through an unrestricted web tunnel.

## Current implementation versus target

Implemented: the dependency-free starter, optional outbound scoped enrollment and
recoverable renewal, interruption protocol and Linux file exchange, durable local
receipt store, offline simulator and optional Kubernetes/Kueue execution/reclaim.

Pending: browser/device login, authenticated continuous command transport,
standalone job supervision and engine submission/recovery, minimal local console,
signed installers/updater, measured optional-download manifest, multi-host
standalone coordination and hardware qualification of cluster setup.

Reuse upstream engines and schedulers. Do not implement a second generic GPU
scheduler or suggest multiple devices provide transparent combined VRAM.
