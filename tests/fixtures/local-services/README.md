# Local service security conformance, version 1.0.0

This is the canonical, transport-neutral attack corpus for local services.
Each consumer runs it against its actual network entry points. Tests do not
need credentials, accounts, GPUs, cloud services or access to this repository.
This directory alone is MIT licensed for bundling into public consumers.

## Two explicit policies

| Profile | Origin | Host | Authentication |
|---|---|---|---|
| hosted-websocket | Exact configured website origins; absent Origin allowed for native clients | Bound IPv4 loopback address and port, plus localhost at that port for older clients | No runtime pairing token today |
| local-http-bearer | Exact local console origin; absent Origin allowed for native clients | Exact numeric loopback authority and port | Bearer required for every API call |

A hosted website contacting a loopback WebSocket legitimately sends cross-site
Fetch Metadata. That field cannot replace the hosted profile's Origin allowlist.
The local HTTP console rejects cross-site requests even with a correct bearer.
Neither policy trusts forwarded headers. Reject ambiguous duplicate security
headers rather than relying on a framework's first/last value rule. Binding to
`127.0.0.1` stays explicit in each server and is tested separately through its
actual listener.

`cases.json` contains ordered header values, including duplicates. Start from
`baseHeaders`; each case replaces headers case-insensitively. An empty list
removes a header. Preserve the specified spelling when transmitting it. Substitute
`{authority}`, `{port}`, `{allowed_origin}`, `{other_scheme_origin}`,
`{other_port_origin}` and a freshly generated `{token}` supplied by the harness.
The alternate port must differ from the actual listener and the allowed origin.
Run every case declaring the consumer's profile; report its case ID on failure.
Do not normalize URLs into an allowlist match or pre-filter attacks in a harness.
HTTP success / WebSocket upgrade means allow; only an explicit 4xx rejection
means deny. A timeout, reset, exception or 5xx is a test failure, not a rejection.

## Distribution and updates

The reviewed fixture directory is copied byte-for-byte from a full shared commit
with `scripts/sync-local-service-conformance.mjs`. `upstream.json` records its
version, source commit and SHA-256 of each bundled file. Consumers check those
hashes in their normal tests; `--check` compares a consumer to its pinned source.
No private package or Git checkout is needed during consumer installation or CI.
Keep these files under test fixtures, outside runtime wheels and source packages.

```text
node scripts/sync-local-service-conformance.mjs FULL_COMMIT CONSUMER_FIXTURE_DIR
node scripts/sync-local-service-conformance.mjs FULL_COMMIT CONSUMER_FIXTURE_DIR --check
node --test scripts/local-service-conformance.test.mjs
```

Edit the canonical cases here, bump the version, run both actual consumers, then
update their pinned copies together. Product origin lists, server startup,
authentication, ttyd capabilities and job lifecycle remain in their products.
Existing ws, Node HTTP, Starlette and Uvicorn handle transports and parsing.

## Scope of the guarantee

Loopback binding and browser Origin checks protect against remote machines and
untrusted browser origins; they do not authenticate an OS user or a native
program. A local program can forge Origin. The hosted profile's intentional
Origin-less native access does not isolate other OS users, local processes,
extensions or a compromised allowed website. The bearer profile adds a secret but
does not sandbox processes that can read that secret. These are boundary
conformance tests, not an audit of all runtime commands, browsers or terminal
capabilities.
