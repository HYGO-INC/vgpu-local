from .contracts.models import BackendCapabilities


def capabilities(provider: str) -> BackendCapabilities:
    if provider not in {"vast", "runpod", "theta", "kubernetes", "simulator"}:
        raise ValueError("unknown backend")
    engine = {"vast": "skypilot", "runpod": "skypilot", "theta": "theta_api",
              "kubernetes": "kubernetes", "simulator": "simulator"}[provider]
    return BackendCapabilities(
        provider=provider, engine=engine, allocation_modes=["whole_device"],
        supports_multi_node=provider == "kubernetes",
        # Restrict to the subset implemented by these adapters, not vendor marketing.
        supports_stop=provider == "theta",
        supports_spot=provider in {"vast", "runpod", "simulator"},
        guaranteed_notice_seconds=0, create_idempotency="reconcile_before_retry",
        workload_isolation="owner_only",
        evidence="simulated" if provider == "simulator" else "source_reviewed",
    )
