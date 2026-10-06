# Optional cloud connection

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
vgpu-local cloud disconnect
```

The CLI generates a random site credential and saves it in the OS credential
store before sending enrollment. Supported stores are Windows Credential Manager,
macOS Keychain and Linux Secret Service. There is no plaintext fallback. If no
supported store is available, connection fails; local GPU commands still work.
`--config` selects a metadata file (default `~/.config/vgpu-local/cloud.json`). It
contains only the origin, scope, site ID and name. Changing its origin/scope does
not cause the existing credential to be sent elsewhere.

If enrollment times out, retry the same command/config after refreshing the user
session if needed. The same site ID and key are reused. Enrollment replay never
extends credential validity. The server sets expiration; expired or revoked sites
cannot authenticate status calls. Re-enrollment with a new configuration creates
a new site and credential. Credential rotation/renewal is a separate future flow.

Disconnect revokes only this connection and can be retried after a lost response.
It does not stop local jobs or delete the config/key, so revocation remains safely
retryable. The cloud-side owner's revoke API can revoke the site when its key is
lost. Responses and redirects cannot choose a different scope or forward tokens.
HTTP is accepted only on numeric loopback addresses for integration tests.

Actual overflow still requires durable local admission fencing, immutable artifact
grants, server-side spending reservations and recovery of remote jobs while a site
is offline. Connection is not evidence those features are implemented.
