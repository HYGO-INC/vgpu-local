# Local ownership and optional cloud connection

The local product owns its site configuration, queues, workloads and data.
Kubernetes/Kueue owns local admission and execution. A cloud connection uses
outbound requests with a scoped site/project token; no cluster-admin kubeconfig
is sent to the service. Installed local execution remains usable without a cloud
account or Internet connection.

## Implemented

- Inventory and native suspended Job rendering/submission through an explicitly
  selected Kubernetes context.
- TypeSpec backend capability/request/observation and overflow policy contracts.
- Reusable Vast/Runpod SkyPilot adapters, a Theta GPU Node HTTP client and a
  persistent offline simulator. Live provider qualification remains outstanding.
- Conservative overflow eligibility checks. Cloud execution itself remains off.
- [Outbound connection enrollment](cloud-connection.md), with retry-stable site
  credentials in the OS credential store. Enrollment enables neither spending nor
  contribution. Client failure behavior is tested offline; production deployment
  and the browser/device login flow remain outstanding.

## Work still required

- Site enrollment and durable authentication, controller reconciliation, local
  console, upgrades/restore and hardware-qualified installation profiles.
- Hosted deployment of the federation HTTP endpoints and credential renewal.
  The connection handshake uses `vgpu.site.v1`; it is not a live service claim.
- Atomic budget reservations in the cloud; quotes, maximum runtime, cleanup and
  reconciliation of continuing remote costs during site disconnection.
- A persisted handoff: fence the local submission against admission, stop/drain
  an active attempt when recovering, and confirm storage writer exclusion before
  a remote replacement starts. A queued status alone does not prove handoff safety.
- Artifact preparation and explicit export grants. Do not copy local directories
  or credentials when cloud overflow is enabled. `local_only` data stays local.
- Workload recipes, multi-node JobSets, model endpoints, qualified sharing and
  optional community capacity contribution.

Overflow can mean placing a queued job, restoring a checkpoint on another backend,
or routing inference to a compatible endpoint. It does not mean live migration of
arbitrary GPU memory. Regional/provider allowlists, hourly and total spend limits,
concurrency limits, queue wait policy and interruption tolerance belong in the
policy. Current eligibility tests do not implement the atomic reservation or the
actual fencing mechanism; both must exist before an automatic submitter is enabled.

Consumption and contribution are independent. Enabling overflow never rents the
owner's GPUs to others. An optional contribution service needs separate enrollment,
reserved local capacity, availability windows, isolation, metering and reclaim
notices. Theta is an optional supplier/operator integration, not a requirement for
local operation. Blockchains or token rewards are not prerequisites for these functions.

`protocol/backend.tsp` is the public contract source. Hosted consumers import a
specific revision with recorded hashes. Independent copies must not evolve without
a protocol revision and conformance checks. Experimental contracts can change;
published stable contracts will require explicit migration compatibility.
