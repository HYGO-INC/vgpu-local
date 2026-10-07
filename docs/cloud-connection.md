# Optional cloud connection

Install the `vgpu-local[cloud]` extra only when choosing connected mode. It adds
the HTTP client, schema validation and OS credential-store support; it adds no
Kubernetes dependency. Connection is for management of the owner's local GPUs.
The initial dependency-free package and standalone use remain independent.

`vgpu-local cloud connect` enrolls this installation in one cloud project. It
uses outbound HTTPS only. Local operation does not require this command or any
account. Enrollment enables neither paid overflow nor contribution of local GPUs.
No kubeconfig, local file, dataset or provider credential is uploaded.

Set `VGPU_USER_ACCESS_TOKEN` in the process environment from your authenticated
session; do not put it in a command argument or commit it. A browser/device login
flow is not yet integrated. Use an explicitly configured endpoint; this does not
claim the vgpu.com production API is deployed.

```text
vgpu-local cloud connect --endpoint https://your-cloud-origin --tenant ten_example0 --project prj_example0 --name Office
vgpu-local cloud status
vgpu-local cloud renew
vgpu-local cloud disconnect
```

The CLI generates a random site credential and saves it in the OS credential
store before sending enrollment. Supported stores are Windows Credential Manager,
macOS Keychain and Linux Secret Service. There is no plaintext fallback. If no
supported store is available, connection fails; local GPU commands still work.
`--config` selects a metadata file (default `~/.config/vgpu-local/cloud.json`). It
contains only the origin, scope, site ID and name. Changing its origin/scope does
not cause the existing credential to be sent elsewhere. Temporary renewal state
also stays in the OS credential store, never this metadata file.

If enrollment times out, retry the same command/config after refreshing the user
session if needed. The same site ID and key are reused. Enrollment replay never
extends credential validity. The server sets expiration; expired or revoked sites
cannot authenticate status calls. A connected background runtime checks on startup
and every hour, renewing active credentials with at most one day left. If you use
only the cloud CLI, use `cloud renew` before expiry. An expired/revoked connection requires
user-authorized enrollment with a new configuration. `connect` replays initial
enrollment; use `status`/`renew` to manage an already renewed connection.

Renewal saves the old credential, replacement and random retry identity together
in one OS credential entry before the request. Retry `cloud renew` after response
loss: it sends the same identity and key. The server accepts the old key only for
that exact committed rotation while its replacement is current. Normal requests
reject the old key immediately. A replay never extends the new expiry again.
`cloud status` can independently confirm the replacement and recover local state.
The background runtime performs this recovery automatically before reporting or
fetching work. It resumes an uncommitted pending renewal with the same key and
retry identity. No manual command is needed while the connected runtime is running.
If the computer is offline until its key expires, explicit enrollment is still
required; the program never silently changes accounts or reactivates a revoked site.

Commands share a hard OS file lock for the connection identity, including copied
configs. Locks contain no credentials and release when the process dies. This uses
the pinned upstream [filelock](https://py-filelock.readthedocs.io/en/latest/)
package. Concurrent commands fail with a retryable busy message instead of
overwriting each other's OS credential entry.

Disconnect revokes only this connection and can be retried after a lost response.
It does not stop local jobs or delete the config/key, so revocation remains safely
retryable. The cloud-side owner's revoke API can revoke the site when its key is
lost. Responses and redirects cannot choose a different scope or forward tokens.
HTTP is accepted only on numeric loopback addresses for integration tests.

The optional [background runtime](local-runtime.md) exchanges authenticated recipe
commands with the account API. Browser pairing and the production website dashboard
remain separate integration work. This connection does not provide cloud overflow.
