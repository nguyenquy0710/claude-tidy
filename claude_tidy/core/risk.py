from __future__ import annotations

from claude_tidy.core.models import Activity, RiskLevel


def classify(
    activity: Activity, last_write: float, now: float, recent_hours: float = 24
) -> RiskLevel:
    if activity is Activity.ACTIVE:
        return RiskLevel.DANGER
    if activity is Activity.MAYBE_ACTIVE or now - last_write < recent_hours * 3600:
        return RiskLevel.WARNING
    return RiskLevel.SAFE
