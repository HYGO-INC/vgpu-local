// Generated; edit protocol/backend.tsp.
export interface paths {
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
