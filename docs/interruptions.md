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

### Local command-line exchange

The CLI now connects the durable controller and Linux mailboxes. Keep an operator
configuration outside every workload mailbox. Copy `examples/interruption-relay.json`
to a controller-owned directory, replace its example scope with this allocation's
runtime identity, and assign distinct mailbox paths to all expected participants.
Paths are relative to the configuration file. The SQLite journal is single-host
operator state, never a workload mount or a shared network database.

```sh
# Operator: initialize and publish a first empty snapshot.
vgpu-local interruption relay --config /var/lib/vgpu/runtime/relay.json --initialize --once
# Configure OS ownership/groups for the workload's requests directory and read views.
# Operator: persist a normalized notice supplied by the selected reclaim authority.
vgpu-local interruption publish --config /var/lib/vgpu/runtime/relay.json --notice notice.json
# Operator: supervised relay; use --once for a bounded reconciliation pass.
vgpu-local interruption relay --config /var/lib/vgpu/runtime/relay.json

# Workload: read a view using its separately provided runtime scope.
vgpu-local interruption snapshot --mailbox /run/vgpu/interruptions --scope scope.json --participant coordinator
# request.json is an InterruptionRequest with this notice/version and one persistent request ID.
vgpu-local interruption submit --mailbox /run/vgpu/interruptions --request request.json --wait-seconds 5
vgpu-local interruption receipt --mailbox /run/vgpu/interruptions --request request.json
```

The example notice has unknown timing; replace it with observed source data. It
does not fabricate a future warning interval. `receipt_pending` means no correlated
receipt arrived within the requested wait; it is not acceptance or rejection.
Keep and retry the identical request after a lost response. Changed intent needs
a new request ID and the current notice version.

One file lock admits a publisher for each canonical journal path. Relays reject
overlapping participant mailboxes, operator state inside them, another runtime's
snapshot and a journal that has fallen behind already published state. Each
participant has a bounded batch; a forged participant response remains unacknowledged.
The relay never invokes a shell, sends a stop signal, grants extensions, confirms
release or changes billing. Those remain the external reclaim controller's work.
Do not mount the operator journal/configuration into workload containers.

### Local Kubernetes reclaim

The owner can now connect the exchange to the identified Kubernetes backend with
one bounded reconciliation command. Initialize the allocation journal, provision
the job and record its resource ID through the `kubernetes` CLI first. The notice
runtime must already exist; missing recovery state is rejected before cluster
access. Its tenant/project/generation must match the allocation request.

```sh
vgpu-local kubernetes reclaim --config site.json --journal operations.db \
  --account-id home-site --request job.json --resource-id k8s:previously-observed-job-uid \
  --interruption-config /var/lib/vgpu/runtime/relay.json
```

The command immutably binds that runtime to the complete request and resource.
It returns `waiting` until all expected participants are ready or a known stop
time is due. An ack alone, an advisory or an unknown deadline cannot trigger
teardown. Source withdrawals and explicit extension grants are re-read before
authorization. Once authorization commits, a later withdrawal cannot undo it.

Reclamation first observes the exact resource, then uses the existing backend's
UID-preconditioned deletion. Lost replies are reconciled on the next invocation.
`releasing` persists while the Job or its owned pods remain; `completed` requires
backend release evidence and closes the notice. A crash after backend release can
finish notice publication without deleting again. Repeat the file relay to publish
the updated snapshot to workloads. No command changes a financial ledger or
validates a claimed checkpoint manifest.

This is a local-owner reconciliation step, not a deployed deadline supervisor,
hard power/storage fence or hosted lifecycle integration. Kubernetes retains its
termination grace period and cleanup ownership. Scheduling this step late or
losing access to the node cannot establish a guaranteed shutdown time. Do not run
it alongside another lifecycle owner controlling the same allocation. Live cluster
execution remains unqualified; the command path passes with a controlled API
including retained orphan pods. Supplier watchers and agent installation remain.

The controller tests cover cancellation/release races, duplicate/late updates,
receipt replay, participant aggregation, scoped runtime rejection, multiple
constraints, explicit extensions and confirmed release. Linux file tests exercise
real descriptor operations, symlink substitution, FIFOs, oversized files, stale
snapshots and failure after a response commits. Ordinary offline checks do not
provision GPUs or send stop signals.

The local file relay is implemented; it is not yet a deployed node agent. Runtime supervisor wiring,
provider notice watchers, authenticated local sockets/HTTP, hosted API/SSE and
signed webhook delivery still need integration. Neither vendor metadata emulation
nor universal unchanged-handler compatibility is claimed. Use named, separately
tested compatibility profiles for AWS, GCP, Azure, Mithril or scheduler handlers.

The event envelope follows [CloudEvents 1.0.2](https://github.com/cloudevents/spec/blob/v1.0.2/cloudevents/spec.md).
Snapshot files are resource views; event envelopes are change notifications, not
interchangeable bytes. Conditional versions fence protocol requests, not hardware
or shared-volume writes; the selected backend must enforce those boundaries.
