# vgpu-local engineering

This is the standalone local product intended for public release. Keep it installable without private
repositories, private package registries or a vgpu.com account. Local execution,
optional cloud consumption and optional capacity contribution are distinct.

Release rule: public only when the vgpu.com site is ready. Until then the
repository is intended to be private. If the remote is still public, keep work
local: do not push or publish packages, images or releases. Its current visibility
does not override this rule. An organization owner's visibility action is separate
from engineering work; do not stop independent local work waiting for it.

Use upstream Kubernetes/Kueue and existing engines; do not build another generic
GPU scheduler. State exactly which behavior is implemented and hardware-tested.
Never imply that pooling devices transparently combines their VRAM.

Edit public contracts in `protocol/backend.tsp`, `protocol/federation.tsp` and `protocol/interruptions.tsp`; use `pnpm generate` and
`pnpm check`. Coordinate pinned protocol imports with hosted consumers. No tests
may provision paid resources or mutate a real cluster without explicit test setup.

Continue authorized work after recording passing evidence; milestones are not
approval checkpoints. Keep genuine blockers visible and work around partial ones.
Use `david <238609058+hygodavid@users.noreply.github.com>` for both author and
committer on future commits. Never use a personal or work email. Do not add Claude,
Codex or other assistant attribution in commit titles, bodies or co-author trailers.
Existing history stays intact unless the owner explicitly requests a rewrite.
