from .contracts.models import BackendCapabilities


def capabilities(provider: str) -> BackendCapabilities:
    if provider not in {"kubernetes", "simulator"}:
        raise ValueError("local backend required")
    engine = provider
    return BackendCapabilities(
        provider=provider, engine=engine, allocation_modes=["whole_device"],
        # The native Job renderer creates one Pod; cluster size is not job support.
        supports_multi_node=False,
        # Restrict to the subset implemented by these adapters, not vendor marketing.
        supports_stop=False,
        supports_spot=provider == "simulator",
        guaranteed_notice_seconds=0, create_idempotency="reconcile_before_retry",
        workload_isolation="owner_only",
        evidence="simulated" if provider == "simulator" else "source_reviewed",
    )
