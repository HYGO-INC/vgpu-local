"""Pure eligibility checks. These do not reserve money or launch remote work."""
from dataclasses import dataclass

from .contracts.models import BurstPolicy


@dataclass(frozen=True)
class OverflowContext:
    local_state: str
    waited_seconds: int
    provider: str
    region: str
    hourly_price_microusd: int
    reservation_microusd: int
    spent_and_reserved_microusd: int
    active_remote_jobs: int
    artifacts_ready: bool
    manually_requested: bool = False


def overflow_denials(policy: BurstPolicy, context: OverflowContext) -> list[str]:
    if policy.mode == "disabled":
        return ["cloud_disabled"]
    reasons = []
    numbers = (context.waited_seconds, context.hourly_price_microusd, context.reservation_microusd,
               context.spent_and_reserved_microusd, context.active_remote_jobs)
    if any(type(value) is not int or not 0 <= value <= 9007199254740991 for value in numbers):
        return ["invalid_observation"]
    if policy.mode == "manual" and not context.manually_requested:
        reasons.append("manual_request_required")
    # Queued alone is not enough: it can still be admitted locally while submitting remotely.
    if context.local_state != "fenced":
        reasons.append("local_execution_not_fenced")
    if context.waited_seconds < policy.local_wait_seconds:
        reasons.append("local_wait_threshold")
    if context.provider not in policy.allowed_providers or context.provider in {"kubernetes", "simulator"}:
        reasons.append("provider_not_allowed")
    if context.region not in policy.allowed_regions:
        reasons.append("region_not_allowed")
    if context.hourly_price_microusd <= 0 or context.hourly_price_microusd > policy.max_hourly_price_microusd:
        reasons.append("hourly_price_limit")
    if context.reservation_microusd <= 0 or context.spent_and_reserved_microusd + context.reservation_microusd > policy.max_total_spend_microusd:
        reasons.append("spending_limit")
    if context.active_remote_jobs >= policy.max_concurrent_remote_jobs:
        reasons.append("remote_concurrency_limit")
    if policy.data_policy != "artifacts_only" or context.artifacts_ready is not True:
        reasons.append("data_export_not_ready")
    return reasons
