# Interruption notices and participant responses

The native protocol reclaims an allocation or attempt. It does not switch GPU
driver contexts or combine GPU memory. Public definitions live in
`protocol/interruptions.tsp` and generate the same JSON Schema, TypeScript and
Python models as the provider/federation protocol.

`InterruptionController` is a reusable, durable domain component over the
`ReceiptStore` interface. A local controller can use SQLite; an orchestrator can
provide a transactional shared store. The controller is separate from delivery,
resource enforcement, checkpoint validation and billing.

## State and authority

Each runtime binds tenant, project, lease, job, attempt, generation, controller
epoch and an agent session. Its required participants are registered by the
controller before requests are accepted. Runtime identity and idempotency are
checked before a response takes effect. A guest cannot choose the authenticated
participant by editing its request JSON.

Each source event has its own retained notice, source revision and notice version.
Several warnings can coexist. Duplicate source updates have no effect; conflicting
content under one source revision is rejected. A source read error is unknown,
never a withdrawal. Confirmed withdrawals cancel scheduled notices; after release
authorization they are recorded without promising to undo reclamation. A canceled
event cannot be revived by a delayed active update. Terminal notices remain in
snapshots, and changes have stable, replayable CloudEvents identities.

| Response | Recorded effect |
|---|---|
| `ack` | This participant received this version. It grants no extra time. |
| `ready` | This participant consents to reclamation of this runtime. All registered participants must be ready for the same version before early release. |
| `request_extension` | A request only. The current target remains until the reclaim authority explicitly grants a new version. |

Requests return durable, correlated receipts with a fingerprint of the entire
request. A duplicate returns its original result even if the notice has since
changed. Stale versions are rejected; readiness never transfers to a newer notice.
A claimed checkpoint is labeled `unverified`, never recoverable merely because
the workload supplied a manifest name.

The reclaim authority may authorize release when all participants are ready or a
known stop/release target is due. An acknowledgement is not required at that limit.
This commits `releasing` intent before the external backend acts. Only a trusted
backend observation can complete release, closing every active notice for that
same allocation. These methods never stop processes or change a ledger.

Provider notices cannot advertise extension support in this implementation.
For owned capacity an explicit grant respects the configured limit and all other
active constraints, including an earlier stop signal. An active constraint with
unknown timing prevents a grant. Raw provider `action_at` and `not_before` values
remain distinct from local operational targets. Unknown timestamps are JSON null;
the protocol never invents a warning interval.

The runtime book allows at most 128 source notices, 64 registered participants
and 4,096 response identities. Retain its history when rotating a runtime. This is
not an unbounded metrics/event store. Calls into publisher/reclaim methods are a
trusted service port; exposing them directly to a workload is unsupported.

## Linux file transport

`InterruptionFiles` exposes snapshot reading, request submission and receipt
reading. Its publisher methods forward requests to the controller and publish
snapshots. One instance is bound to one participant and runtime:

```text
/run/vgpu/interruptions/
  state.json
  requests/irq_<request-id>.json
  receipts/irq_<request-id>.json
```

Mount the parent directory, so atomic replacements stay visible. A successful
request-file write means submitted locally; wait for its matching receipt to know
whether the controller accepted it. Receipt delivery can fail after the database
commit; replaying the same request recovers the same outcome.

The installer must keep the parent, snapshot and receipts writable only by the
publisher, and grant the workload access only to its own `requests/` directory.
The library creates directories with restrictive permissions; it does not guess
container UIDs or change ownership. Give separate participants separate mailboxes
bound by the publisher's configuration. These permissions are not protection from
root inside a customer-controlled VM: reclamation still belongs outside it.

The transport pins directory descriptors, refuses symlinks and special files,
bounds file sizes and batches, rejects duplicate JSON keys, and atomically writes
snapshots/receipts. Request creation does not overwrite a different intent.
Invalid entries are reported and remain unacknowledged; supervisors must isolate
and rate-limit mailboxes so one participant cannot starve another. Local Windows
users run this transport in Linux/WSL; native Windows is explicitly refused.

## Qualification and remaining integration

The controller tests cover cancellation/release races, duplicate/late updates,
receipt replay, participant aggregation, scoped runtime rejection, multiple
constraints, explicit extensions and confirmed release. Linux file tests exercise
real descriptor operations, symlink substitution, FIFOs, oversized files, stale
snapshots and failure after a response commits. Ordinary offline checks do not
provision GPUs or send stop signals.

This component is not yet a deployed node agent. Runtime supervisor wiring,
provider notice watchers, authenticated local sockets/HTTP, hosted API/SSE and
signed webhook delivery still need integration. Neither vendor metadata emulation
nor universal unchanged-handler compatibility is claimed. Use named, separately
tested compatibility profiles for AWS, GCP, Azure, Mithril or scheduler handlers.

The event envelope follows [CloudEvents 1.0.2](https://github.com/cloudevents/spec/blob/v1.0.2/cloudevents/spec.md).
Snapshot files are resource views; event envelopes are change notifications, not
interchangeable bytes. Conditional versions fence protocol requests, not hardware
or shared-volume writes; the selected backend must enforce those boundaries.
