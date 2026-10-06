# Provider integrations

## Vast.ai and Runpod

Use `vgpu_local.skypilot_backend.SkyPilotBackend` from an isolated execution
environment containing `skypilot[vast,runpod]==0.14.0`. The core local package does
not install or start the cloud engine. Keep provider accounts and their SkyPilot
server state isolated between credential domains.

The adapter builds a provider-specific task, preserves a durable operation scope
(tenant/project/account/provider/operation/generation), and records its intent in
SQLite before submission. Repeated calls with the same request return its receipt;
different requests under the same identity fail. A lost reply becomes uncertain.
Known SkyPilot request IDs can be reconciled without another launch. If the SDK
submission reply itself is lost, supplier inventory reconciliation is still needed;
the adapter refuses a second launch. Do not delete the journal to force a retry.

The adapter is restricted to single-node owner workloads. The reviewed provider
paths do not implement multi-node execution. Runpod's SkyPilot path does not
implement stop, even though Runpod itself offers stopped Pods. Neither adapter
claims mounted object-store support. No minimum interruption notice is guaranteed.
SkyPilot's supplier credential mounts need qualification before exposing its
runtime to arbitrary customer code; `workload_trust=untrusted` is rejected.

`max_hourly_cost` is passed to SkyPilot's resource selection. This is not proof of
a complete spending cap, storage/egress accounting or an atomic financial grant.
Those responsibilities belong to the calling product's policy and reservation layer.
Successful SDK completion and live resource behavior must be tested per supplier.

Sources: [SkyPilot installation](https://docs.skypilot.ai/en/latest/getting-started/installation.html),
[Vast source](https://github.com/skypilot-org/skypilot/blob/v0.14.0/sky/clouds/vast.py),
[Runpod source](https://github.com/skypilot-org/skypilot/blob/v0.14.0/sky/clouds/runpod.py),
[Vast interruption behavior](https://docs.vast.ai/guides/instances/choosing/instance-types),
[Runpod restart behavior](https://docs.runpod.io/pods/troubleshooting/zero-gpus).

## Theta EdgeCloud

`ThetaClient` uses the project-scoped GPU Node API v1, with a supplied API key and
a fixed HTTPS endpoint. It supports resources/templates, create/list/inspect,
start/stop/delete and events/logs. Native response bodies remain intact: this
client does not guess a deployment-state mapping from undocumented response fields.

Create requires a resource, template, region, image, SSH public key and price
ceiling. It records a hashed request binding before POST and uses a deterministic
native name as a correlation hint. The name is not server-enforced idempotency.
Timeouts, server errors or unreadable mutation receipts become uncertain. A second
create with that operation identity is refused until reconciled. The adapter does
not automatically adopt a similarly named deployment; live inventory fields and
uniqueness must be qualified first. Lifecycle calls do not auto-retry. Their caller
must reconcile an uncertain outcome before requesting another mutation.

Use project credentials from a secret store or the calling process, never in
configuration committed to a repository. Start creates billable capacity;
stop and delete have distinct semantics. The native community-node create price
ceiling is transmitted at creation. Inference and dedicated-model APIs are separate
integrations and are not implemented by this GPU Node client.

Sources: [API overview](https://docs.thetatoken.org/docs/theta-edgecloud-api),
[GPU discovery](https://docs.thetatoken.org/docs/edgecloud-gpu-resources-api),
[GPU lifecycle](https://docs.thetatoken.org/docs/edgecloud-gpu-node-api).

## Simulator

`Simulator` stores resources and receipts in SQLite, survives process restart,
and injects lost create replies, warning/no-warning interruptions, failed teardown,
stale observations and duplicate event delivery. Its clock advances explicitly;
tests do not sleep or rent GPUs. Events are simulator fixtures, not the complete
customer interruption protocol or proof that financial settlement is implemented.
