// Provider-neutral reclaim notices. GPU driver context switching is unrelated.
namespace Vgpu.V1;

@pattern("^int_[a-f0-9]{32}(?![\\s\\S])")
scalar InterruptionId extends string;
@pattern("^irq_[a-f0-9]{32}(?![\\s\\S])")
scalar InterruptionRequestId extends string;
@pattern("^igs_[a-f0-9]{32}(?![\\s\\S])")
scalar InterruptionSessionId extends string;

// Integer Unix milliseconds. null means unknown, never zero or "no warning".
alias InterruptionTime = NonnegativeInteger | null;
union InterruptionAction { "ack", "ready", "request_extension" }

model InterruptionScope {
  tenant_id: BackendIdentifier;
  project_id: BackendIdentifier;
  lease_id: BackendIdentifier;
  job_id: BackendIdentifier;
  attempt_id: BackendIdentifier;
  generation: PositiveInteger;
  controller_epoch: PositiveInteger;
  agent_session_id: InterruptionSessionId;
}

// Supplied by a trusted adapter, not by a workload. Read errors are not updates.
model InterruptionSourceNotice {
  source_id: BackendIdentifier;
  source_event_id: BackendIdentifier;
  source_revision: PositiveInteger;
  authority: "provider" | "vgpu" | "local_owner";
  state: "active" | "withdrawn";
  kind: "preempt" | "stop" | "reboot" | "advisory";
  reason: BackendIdentifier;
  observed_at_ms: NonnegativeInteger;
  source_time_kind: "action_at" | "not_before" | "vgpu_policy" | "unknown";
  source_action_at_ms: InterruptionTime;
  source_not_before_ms: InterruptionTime;
  release_by_ms: InterruptionTime;
  signal_at_ms: InterruptionTime;
  safety_margin_ms: NonnegativeInteger;
  clock_uncertainty_ms: NonnegativeInteger;
  mapping_policy: BackendIdentifier;
  notice_class: "best_effort" | "controlled" | "no_notice";
  @maxItems(3)
  allowed_actions: InterruptionAction[];
  extension_limit_ms: InterruptionTime;
}

model Interruption extends InterruptionScope {
  schema_version: 1;
  interruption_id: InterruptionId;
  version: PositiveInteger;
  phase: "scheduled" | "releasing" | "completed" | "canceled";
  source: InterruptionSourceNotice;
  // Updated only by the reclaim authority; a request never changes these.
  release_by_ms: InterruptionTime;
  signal_at_ms: InterruptionTime;
}

model InterruptionSnapshot extends InterruptionScope {
  schema_version: 1;
  cursor: NonnegativeInteger;
  @maxItems(128)
  interruptions: Interruption[];
}

model InterruptionRequest extends InterruptionScope {
  schema_version: 1;
  request_id: InterruptionRequestId;
  interruption_id: InterruptionId;
  interruption_version: PositiveInteger;
  participant_id: BackendIdentifier;
  action: InterruptionAction;
  // Only a ready request may claim a manifest. A claim is not validation.
  checkpoint_manifest: BackendIdentifier | null;
  // Only an extension request supplies a later target. The old target remains.
  requested_release_by_ms: InterruptionTime;
}

model InterruptionReceipt extends InterruptionScope {
  schema_version: 1;
  request_id: InterruptionRequestId;
  interruption_id: InterruptionId;
  participant_id: BackendIdentifier;
  action: InterruptionAction;
  @pattern("^sha256:[a-f0-9]{64}(?![\\s\\S])")
  request_fingerprint: string;
  status: "accepted" | "rejected";
  code: BackendIdentifier;
  notice_version: PositiveInteger | null;
  cursor: PositiveInteger;
  checkpoint_status: "none" | "unverified";
}

// Structured CloudEvents change envelope. Files contain snapshots, not envelopes.
model InterruptionEvent {
  specversion: "1.0";
  @pattern("^ice_[a-f0-9]{64}(?![\\s\\S])")
  id: string;
  source: "urn:vgpu:interruptions";
  type: "com.vgpu.interruption.changed.v1";
  @minLength(1) @maxLength(600)
  subject: string;
  datacontenttype: "application/json";
  data: Interruption;
}
