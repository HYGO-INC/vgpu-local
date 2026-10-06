// Public source of truth. Hosted consumers import a pinned, hash-checked copy.
import "./federation.tsp";
namespace Vgpu.V1;

@minLength(1)
@maxLength(255)
scalar BackendIdentifier extends string;

@minValue(0)
@maxValue(9007199254740991)
scalar NonnegativeInteger extends int64;

@minValue(1)
@maxValue(9007199254740991)
scalar PositiveInteger extends int64;

union BackendProvider { "vast", "runpod", "theta", "kubernetes", "simulator" }

model BackendCapabilities {
  provider: BackendProvider;
  engine: "skypilot" | "theta_api" | "kubernetes" | "simulator";
  @minItems(1)
  allocation_modes: ("whole_device" | "mig" | "software_shared")[];
  supports_multi_node: boolean;
  supports_stop: boolean;
  supports_spot: boolean;
  guaranteed_notice_seconds: NonnegativeInteger;
  create_idempotency: "native" | "reconcile_before_retry";
  workload_isolation: "owner_only" | "qualified_multitenant";
  evidence: "simulated" | "source_reviewed" | "live_verified";
}

model BackendRequest {
  tenant_id: BackendIdentifier;
  project_id: BackendIdentifier;
  account_id: BackendIdentifier;
  operation_id: BackendIdentifier;
  generation: PositiveInteger;
  provider: BackendProvider;
  image: BackendIdentifier;
  gpu_model: BackendIdentifier;
  gpu_count: PositiveInteger;
  num_nodes: PositiveInteger;
  region: BackendIdentifier;
  capacity_mode: "on_demand" | "spot";
  workload_trust: "owner" | "untrusted";
  max_hourly_price_microusd: PositiveInteger;
  @minItems(1)
  command: string[];
}

model BackendObservation {
  tenant_id: BackendIdentifier;
  project_id: BackendIdentifier;
  account_id: BackendIdentifier;
  operation_id: BackendIdentifier;
  provider: BackendProvider;
  resource_id: BackendIdentifier;
  generation: PositiveInteger;
  revision: PositiveInteger;
  state: "provisioning" | "running" | "paused" | "lost" | "released" | "unknown";
  supplier_state: "allocated" | "released" | "unknown";
}

model BurstPolicy {
  mode: "disabled" | "manual" | "automatic";
  allowed_providers: BackendProvider[];
  allowed_regions: string[];
  max_hourly_price_microusd: NonnegativeInteger;
  max_total_spend_microusd: NonnegativeInteger;
  max_concurrent_remote_jobs: NonnegativeInteger;
  local_wait_seconds: NonnegativeInteger;
  data_policy: "local_only" | "artifacts_only";
}
