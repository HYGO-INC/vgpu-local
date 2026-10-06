// Generated; edit protocol/backend.tsp.
export type paths = Record<string, never>;
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        BackendCapabilities: {
            provider: components["schemas"]["BackendProvider"];
            /** @enum {string} */
            engine: "skypilot" | "theta_api" | "kubernetes" | "simulator";
            allocation_modes: ("whole_device" | "mig" | "software_shared")[];
            supports_multi_node: boolean;
            supports_stop: boolean;
            supports_spot: boolean;
            guaranteed_notice_seconds: components["schemas"]["NonnegativeInteger"];
            /** @enum {string} */
            create_idempotency: "native" | "reconcile_before_retry";
            /** @enum {string} */
            workload_isolation: "owner_only" | "qualified_multitenant";
            /** @enum {string} */
            evidence: "simulated" | "source_reviewed" | "live_verified";
        };
        BackendIdentifier: string;
        BackendObservation: {
            tenant_id: components["schemas"]["BackendIdentifier"];
            project_id: components["schemas"]["BackendIdentifier"];
            account_id: components["schemas"]["BackendIdentifier"];
            operation_id: components["schemas"]["BackendIdentifier"];
            provider: components["schemas"]["BackendProvider"];
            resource_id: components["schemas"]["BackendIdentifier"];
            generation: components["schemas"]["PositiveInteger"];
            revision: components["schemas"]["PositiveInteger"];
            /** @enum {string} */
            state: "provisioning" | "running" | "paused" | "lost" | "released" | "unknown";
            /** @enum {string} */
            supplier_state: "allocated" | "released" | "unknown";
        };
        /** @enum {string} */
        BackendProvider: "vast" | "runpod" | "theta" | "kubernetes" | "simulator";
        BackendRequest: {
            tenant_id: components["schemas"]["BackendIdentifier"];
            project_id: components["schemas"]["BackendIdentifier"];
            account_id: components["schemas"]["BackendIdentifier"];
            operation_id: components["schemas"]["BackendIdentifier"];
            generation: components["schemas"]["PositiveInteger"];
            provider: components["schemas"]["BackendProvider"];
            image: components["schemas"]["BackendIdentifier"];
            gpu_model: components["schemas"]["BackendIdentifier"];
            gpu_count: components["schemas"]["PositiveInteger"];
            num_nodes: components["schemas"]["PositiveInteger"];
            region: components["schemas"]["BackendIdentifier"];
            /** @enum {string} */
            capacity_mode: "on_demand" | "spot";
            /** @enum {string} */
            workload_trust: "owner" | "untrusted";
            max_hourly_price_microusd: components["schemas"]["PositiveInteger"];
            command: string[];
        };
        BurstPolicy: {
            /** @enum {string} */
            mode: "disabled" | "manual" | "automatic";
            allowed_providers: components["schemas"]["BackendProvider"][];
            allowed_regions: string[];
            max_hourly_price_microusd: components["schemas"]["NonnegativeInteger"];
            max_total_spend_microusd: components["schemas"]["NonnegativeInteger"];
            max_concurrent_remote_jobs: components["schemas"]["NonnegativeInteger"];
            local_wait_seconds: components["schemas"]["NonnegativeInteger"];
            /** @enum {string} */
            data_policy: "local_only" | "artifacts_only";
        };
        /** Format: int64 */
        NonnegativeInteger: number;
        /** Format: int64 */
        PositiveInteger: number;
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export type operations = Record<string, never>;
