# vgpu-local engineering

This is the public, standalone local product. Keep it installable without private
repositories, private package registries or a vgpu.com account. Local execution,
optional cloud consumption and optional capacity contribution are distinct.

Use upstream Kubernetes/Kueue and existing engines; do not build another generic
GPU scheduler. State exactly which behavior is implemented and hardware-tested.
Never imply that pooling devices transparently combines their VRAM.

Edit public contracts in `protocol/backend.tsp`; use `pnpm generate` and
`pnpm check`. Coordinate pinned protocol imports with hosted consumers. No tests
may provision paid resources or mutate a real cluster without explicit test setup.

Continue authorized work after recording passing evidence; milestones are not
approval checkpoints. Keep genuine blockers visible and work around partial ones.
Use david <david@hygo.com> for commits without assistant attribution.
