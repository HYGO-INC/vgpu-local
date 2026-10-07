// Generated; edit protocol/backend.tsp.
export interface paths {
    "/api/v1/device/approval": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["DeviceEnrollment_approval"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/device/enroll": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["DeviceEnrollment_enroll"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/tenants/{tenant_id}/projects/{project_id}/sites": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["SiteFederation_enroll"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/tenants/{tenant_id}/projects/{project_id}/sites/{site_id}/commands": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["SiteFederation_command"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/tenants/{tenant_id}/projects/{project_id}/sites/{site_id}/commands/{command_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["SiteFederation_commandStatus"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/tenants/{tenant_id}/projects/{project_id}/sites/{site_id}/connection": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["SiteFederation_connection"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/tenants/{tenant_id}/projects/{project_id}/sites/{site_id}/connection/exchange": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["SiteFederation_exchange"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/tenants/{tenant_id}/projects/{project_id}/sites/{site_id}/connection/renew": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["SiteFederation_renew"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/tenants/{tenant_id}/projects/{project_id}/sites/{site_id}/connection/revoke": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["SiteFederation_disconnect"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/tenants/{tenant_id}/projects/{project_id}/sites/{site_id}/executions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["SiteFederation_executions"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/tenants/{tenant_id}/projects/{project_id}/sites/{site_id}/executions/{execution_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["SiteFederation_execution"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/tenants/{tenant_id}/projects/{project_id}/sites/{site_id}/revoke": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["SiteFederation_revoke"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
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
            workload?: components["schemas"]["BackendWorkloadStatus"];
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
        BackendWorkloadStatus: {
            job_id: components["schemas"]["BackendIdentifier"];
            /** @enum {string} */
            state: "queued" | "running" | "succeeded" | "failed" | "canceled" | "unknown";
        };
        Interruption: {
            /** @enum {number} */
            schema_version: 1;
            interruption_id: components["schemas"]["InterruptionId"];
            version: components["schemas"]["PositiveInteger"];
            /** @enum {string} */
            phase: "scheduled" | "releasing" | "completed" | "canceled";
            source: components["schemas"]["InterruptionSourceNotice"];
            release_by_ms: components["schemas"]["NonnegativeInteger"] | null;
            signal_at_ms: components["schemas"]["NonnegativeInteger"] | null;
        } & components["schemas"]["InterruptionScope"];
        /** @enum {string} */
        InterruptionAction: "ack" | "ready" | "request_extension";
        InterruptionEvent: {
            /** @enum {string} */
            specversion: "1.0";
            id: string;
            /** @enum {string} */
            source: "urn:vgpu:interruptions";
            /** @enum {string} */
            type: "com.vgpu.interruption.changed.v1";
            subject: string;
            /** @enum {string} */
            datacontenttype: "application/json";
            data: components["schemas"]["Interruption"];
        };
        InterruptionId: string;
        InterruptionReceipt: {
            /** @enum {number} */
            schema_version: 1;
            request_id: components["schemas"]["InterruptionRequestId"];
            interruption_id: components["schemas"]["InterruptionId"];
            participant_id: components["schemas"]["BackendIdentifier"];
            action: components["schemas"]["InterruptionAction"];
            request_fingerprint: string;
            /** @enum {string} */
            status: "accepted" | "rejected";
            code: components["schemas"]["BackendIdentifier"];
            notice_version: components["schemas"]["PositiveInteger"] | null;
            cursor: components["schemas"]["PositiveInteger"];
            /** @enum {string} */
            checkpoint_status: "none" | "unverified";
        } & components["schemas"]["InterruptionScope"];
        InterruptionRequest: {
            /** @enum {number} */
            schema_version: 1;
            request_id: components["schemas"]["InterruptionRequestId"];
            interruption_id: components["schemas"]["InterruptionId"];
            interruption_version: components["schemas"]["PositiveInteger"];
            participant_id: components["schemas"]["BackendIdentifier"];
            action: components["schemas"]["InterruptionAction"];
            checkpoint_manifest: components["schemas"]["BackendIdentifier"] | null;
            requested_release_by_ms: components["schemas"]["NonnegativeInteger"] | null;
        } & components["schemas"]["InterruptionScope"];
        InterruptionRequestId: string;
        InterruptionScope: {
            tenant_id: components["schemas"]["BackendIdentifier"];
            project_id: components["schemas"]["BackendIdentifier"];
            lease_id: components["schemas"]["BackendIdentifier"];
            job_id: components["schemas"]["BackendIdentifier"];
            attempt_id: components["schemas"]["BackendIdentifier"];
            generation: components["schemas"]["PositiveInteger"];
            controller_epoch: components["schemas"]["PositiveInteger"];
            agent_session_id: components["schemas"]["InterruptionSessionId"];
        };
        InterruptionSessionId: string;
        InterruptionSnapshot: {
            /** @enum {number} */
            schema_version: 1;
            cursor: components["schemas"]["NonnegativeInteger"];
            interruptions: components["schemas"]["Interruption"][];
        } & components["schemas"]["InterruptionScope"];
        InterruptionSourceNotice: {
            source_id: components["schemas"]["BackendIdentifier"];
            source_event_id: components["schemas"]["BackendIdentifier"];
            source_revision: components["schemas"]["PositiveInteger"];
            /** @enum {string} */
            authority: "provider" | "vgpu" | "local_owner";
            /** @enum {string} */
            state: "active" | "withdrawn";
            /** @enum {string} */
            kind: "preempt" | "stop" | "reboot" | "advisory";
            reason: components["schemas"]["BackendIdentifier"];
            observed_at_ms: components["schemas"]["NonnegativeInteger"];
            /** @enum {string} */
            source_time_kind: "action_at" | "not_before" | "vgpu_policy" | "unknown";
            source_action_at_ms: components["schemas"]["NonnegativeInteger"] | null;
            source_not_before_ms: components["schemas"]["NonnegativeInteger"] | null;
            release_by_ms: components["schemas"]["NonnegativeInteger"] | null;
            signal_at_ms: components["schemas"]["NonnegativeInteger"] | null;
            safety_margin_ms: components["schemas"]["NonnegativeInteger"];
            clock_uncertainty_ms: components["schemas"]["NonnegativeInteger"];
            mapping_policy: components["schemas"]["BackendIdentifier"];
            /** @enum {string} */
            notice_class: "best_effort" | "controlled" | "no_notice";
            allowed_actions: components["schemas"]["InterruptionAction"][];
            extension_limit_ms: components["schemas"]["NonnegativeInteger"] | null;
        };
        LocalCommandId: string;
        LocalCommandReceipt: {
            command_id: components["schemas"]["LocalCommandId"];
            request_sha256: components["schemas"]["LocalDigest"];
            accepted: boolean;
            error_code?: string;
        };
        LocalCommandStatus: {
            command: components["schemas"]["LocalExecutionCommand"];
            receipt?: components["schemas"]["LocalCommandReceipt"];
        };
        LocalDigest: string;
        LocalExchange: {
            receipts: components["schemas"]["LocalCommandReceipt"][];
            reports: components["schemas"]["LocalExecutionReport"][];
        };
        LocalExchangeResult: {
            tenant_id: components["schemas"]["BackendIdentifier"];
            project_id: components["schemas"]["BackendIdentifier"];
            site_id: components["schemas"]["SiteId"];
            commands: components["schemas"]["LocalExecutionCommand"][];
            command_receipts: components["schemas"]["LocalCommandId"][];
            report_receipts: components["schemas"]["LocalReportReceipt"][];
        };
        LocalExecutionCommand: {
            command_id: components["schemas"]["LocalCommandId"];
            tenant_id: components["schemas"]["BackendIdentifier"];
            project_id: components["schemas"]["BackendIdentifier"];
            site_id: components["schemas"]["SiteId"];
            execution_id: components["schemas"]["LocalExecutionId"];
            generation: components["schemas"]["PositiveInteger"];
            expires_at: components["schemas"]["PositiveInteger"];
            /** @enum {string} */
            action: "start" | "cancel";
            recipe_id: components["schemas"]["LocalRecipeId"];
            recipe_sha256: components["schemas"]["LocalDigest"];
            request_sha256: components["schemas"]["LocalDigest"];
        };
        LocalExecutionId: string;
        LocalExecutionReport: {
            execution_id: components["schemas"]["LocalExecutionId"];
            revision: components["schemas"]["PositiveInteger"];
            generation: components["schemas"]["PositiveInteger"];
            /** @enum {string} */
            state: "accepted" | "dispatching" | "queued" | "running" | "succeeded" | "failed" | "uncertain" | "cancel_requested" | "canceled";
            recipe_id: components["schemas"]["LocalRecipeId"];
            recipe_sha256: components["schemas"]["LocalDigest"];
            error_code?: string;
        };
        LocalRecipeId: string;
        LocalReportReceipt: {
            execution_id: components["schemas"]["LocalExecutionId"];
            revision: components["schemas"]["PositiveInteger"];
        };
        /** Format: int64 */
        NonnegativeInteger: number;
        /** Format: int64 */
        PositiveInteger: number;
        ProtocolError: {
            error: string;
        };
        SiteConnection: {
            site_id: components["schemas"]["SiteId"];
            tenant_id: components["schemas"]["BackendIdentifier"];
            project_id: components["schemas"]["BackendIdentifier"];
            name: string;
            /** @enum {string} */
            protocol_version: "vgpu.site.v1";
            /** @enum {string} */
            state: "active" | "expired" | "revoked";
            credential_expires_at: components["schemas"]["NonnegativeInteger"];
            /** @enum {boolean} */
            consumption_enabled: false;
            /** @enum {boolean} */
            contribution_enabled: false;
        };
        SiteCredential: string;
        SiteCredentialRotation: {
            rotation_id: components["schemas"]["SiteRotationId"];
            credential: components["schemas"]["SiteCredential"];
        };
        SiteEnrollment: {
            site_id: components["schemas"]["SiteId"];
            name: string;
            /** @enum {string} */
            protocol_version: "vgpu.site.v1";
            credential: components["schemas"]["SiteCredential"];
        };
        SiteEnrollmentApproval: {
            site_id: components["schemas"]["SiteId"];
            tenant_id: components["schemas"]["BackendIdentifier"];
            project_id: components["schemas"]["BackendIdentifier"];
            name: string;
        };
        SiteId: string;
        SiteRotationId: string;
        SiteRotationResult: {
            rotation_id: components["schemas"]["SiteRotationId"];
        } & components["schemas"]["SiteConnection"];
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    DeviceEnrollment_approval: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description The request has succeeded. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SiteEnrollmentApproval"];
                };
            };
            /** @description The server could not understand the request due to invalid syntax. */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Access is unauthorized. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Access is forbidden. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description The server cannot find the requested resource. */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description The request conflicts with the current state of the server. */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Service unavailable. */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
        };
    };
    DeviceEnrollment_enroll: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SiteEnrollment"];
            };
        };
        responses: {
            /** @description The request has succeeded and a new resource has been created as a result. */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SiteConnection"];
                };
            };
            /** @description The server could not understand the request due to invalid syntax. */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Access is unauthorized. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Access is forbidden. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description The server cannot find the requested resource. */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description The request conflicts with the current state of the server. */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Service unavailable. */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
        };
    };
    SiteFederation_enroll: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tenant_id: components["schemas"]["BackendIdentifier"];
                project_id: components["schemas"]["BackendIdentifier"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SiteEnrollment"];
            };
        };
        responses: {
            /** @description The request has succeeded and a new resource has been created as a result. */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SiteConnection"];
                };
            };
            /** @description The server could not understand the request due to invalid syntax. */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Access is unauthorized. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Access is forbidden. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description The server cannot find the requested resource. */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description The request conflicts with the current state of the server. */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Service unavailable. */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
        };
    };
    SiteFederation_command: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tenant_id: components["schemas"]["BackendIdentifier"];
                project_id: components["schemas"]["BackendIdentifier"];
                site_id: components["schemas"]["SiteId"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LocalExecutionCommand"];
            };
        };
        responses: {
            /** @description The request has succeeded. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocalExecutionCommand"];
                };
            };
            /** @description The server could not understand the request due to invalid syntax. */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Access is unauthorized. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Access is forbidden. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description The server cannot find the requested resource. */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description The request conflicts with the current state of the server. */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Service unavailable. */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
        };
    };
    SiteFederation_commandStatus: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tenant_id: components["schemas"]["BackendIdentifier"];
                project_id: components["schemas"]["BackendIdentifier"];
                site_id: components["schemas"]["SiteId"];
                command_id: components["schemas"]["LocalCommandId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description The request has succeeded. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocalCommandStatus"];
                };
            };
            /** @description The server could not understand the request due to invalid syntax. */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Access is unauthorized. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Access is forbidden. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description The server cannot find the requested resource. */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description The request conflicts with the current state of the server. */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Service unavailable. */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
        };
    };
    SiteFederation_connection: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tenant_id: components["schemas"]["BackendIdentifier"];
                project_id: components["schemas"]["BackendIdentifier"];
                site_id: components["schemas"]["SiteId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description The request has succeeded. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SiteConnection"];
                };
            };
            /** @description The server could not understand the request due to invalid syntax. */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Access is unauthorized. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Access is forbidden. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description The server cannot find the requested resource. */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description The request conflicts with the current state of the server. */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Service unavailable. */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
        };
    };
    SiteFederation_exchange: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tenant_id: components["schemas"]["BackendIdentifier"];
                project_id: components["schemas"]["BackendIdentifier"];
                site_id: components["schemas"]["SiteId"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LocalExchange"];
            };
        };
        responses: {
            /** @description The request has succeeded. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocalExchangeResult"];
                };
            };
            /** @description The server could not understand the request due to invalid syntax. */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Access is unauthorized. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Access is forbidden. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description The server cannot find the requested resource. */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description The request conflicts with the current state of the server. */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Service unavailable. */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
        };
    };
    SiteFederation_renew: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tenant_id: components["schemas"]["BackendIdentifier"];
                project_id: components["schemas"]["BackendIdentifier"];
                site_id: components["schemas"]["SiteId"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SiteCredentialRotation"];
            };
        };
        responses: {
            /** @description The request has succeeded. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SiteRotationResult"];
                };
            };
            /** @description The server could not understand the request due to invalid syntax. */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Access is unauthorized. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Access is forbidden. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description The server cannot find the requested resource. */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description The request conflicts with the current state of the server. */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Service unavailable. */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
        };
    };
    SiteFederation_disconnect: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tenant_id: components["schemas"]["BackendIdentifier"];
                project_id: components["schemas"]["BackendIdentifier"];
                site_id: components["schemas"]["SiteId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description The request has succeeded. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SiteConnection"];
                };
            };
            /** @description The server could not understand the request due to invalid syntax. */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Access is unauthorized. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Access is forbidden. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description The server cannot find the requested resource. */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description The request conflicts with the current state of the server. */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Service unavailable. */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
        };
    };
    SiteFederation_executions: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tenant_id: components["schemas"]["BackendIdentifier"];
                project_id: components["schemas"]["BackendIdentifier"];
                site_id: components["schemas"]["SiteId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description The request has succeeded. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocalExecutionReport"][];
                };
            };
            /** @description The server could not understand the request due to invalid syntax. */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Access is unauthorized. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Access is forbidden. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description The server cannot find the requested resource. */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description The request conflicts with the current state of the server. */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Service unavailable. */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
        };
    };
    SiteFederation_execution: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tenant_id: components["schemas"]["BackendIdentifier"];
                project_id: components["schemas"]["BackendIdentifier"];
                site_id: components["schemas"]["SiteId"];
                execution_id: components["schemas"]["LocalExecutionId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description The request has succeeded. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocalExecutionReport"];
                };
            };
            /** @description The server could not understand the request due to invalid syntax. */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Access is unauthorized. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Access is forbidden. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description The server cannot find the requested resource. */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description The request conflicts with the current state of the server. */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Service unavailable. */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
        };
    };
    SiteFederation_revoke: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tenant_id: components["schemas"]["BackendIdentifier"];
                project_id: components["schemas"]["BackendIdentifier"];
                site_id: components["schemas"]["SiteId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description The request has succeeded. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SiteConnection"];
                };
            };
            /** @description The server could not understand the request due to invalid syntax. */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Access is unauthorized. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Access is forbidden. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description The server cannot find the requested resource. */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description The request conflicts with the current state of the server. */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Client error */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
            /** @description Service unavailable. */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProtocolError"];
                };
            };
        };
    };
}
