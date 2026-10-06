# Durable execution receipts

Adapters depend on the `ReceiptStore` protocol in `vgpu_local.journal`. Local
installations use the SQLite `Journal`; no hosted account or PostgreSQL service
is needed for a single-site installation. A hosted service can inject a shared
database implementation without copying the provider adapter.

The store must atomically bind the complete request fingerprint to its scoped
operation identity. Exactly one caller wins `begin`; exactly one caller wins a
given `transition`. The winning receipt must be durably committed before any
supplier call. `change` serializes updates and rolls back on exceptions. Connection
errors are uncertainty, not proof that a receipt does not exist.

Multiple workers must use the same authoritative store. Separate SQLite files,
missing mounts or an unavailable database cannot authorize another create.
Receipts do not expire while supplier resources may remain. Restoring an old
database backup needs reconciliation with provider inventory before provisioning
resumes. A database generation does not fence a GPU process or a shared-volume
writer.

The SQLite tests race 32 callers through independent connections and verify one
receipt, one create claim, all serialized changes and rollback preservation.
Qualify any alternative store against the same behavior and across processes.
