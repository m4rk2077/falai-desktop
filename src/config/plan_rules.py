"""Shared plan and entitlement rules used by desktop billing/UI flows."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

TRIAL_DAYS = 7
TRIAL_DAILY_MINUTES = 15
TRIAL_MONTHLY_MINUTES = 450
START_DAILY_MINUTES = 30
START_MONTHLY_MINUTES = 900

ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing"}
PAID_PLAN_CODES = {"start", "pro"}


@dataclass(frozen=True)
class EntitlementPlan:
    plan_code: str
    plan_name: str
    blocked: bool


def normalize_int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_iso_datetime(value: Any) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_trial_quota_limits(daily_minutes_limit: Any, monthly_minutes_limit: Any) -> bool:
    daily = normalize_int_or_none(daily_minutes_limit)
    monthly = normalize_int_or_none(monthly_minutes_limit)
    return daily is not None and monthly is not None and daily <= TRIAL_DAILY_MINUTES and monthly <= TRIAL_MONTHLY_MINUTES


def trial_plan_name() -> str:
    return f"Trial {TRIAL_DAYS} dias"


def trial_plan_subtitle() -> str:
    return f"Teste grátis por {TRIAL_DAYS} dias · {TRIAL_DAILY_MINUTES} min/dia · Sem cartão"


def trial_expired_title() -> str:
    return "Seu teste acabou"


def trial_expired_body() -> str:
    return (
        f"Seu teste de {TRIAL_DAYS} dias foi encerrado.\n"
        "Para continuar usando, veja as opções de planos disponíveis."
    )


def entitlement_expired_message() -> str:
    return f"Teste encerrado ({TRIAL_DAYS} dias). Veja planos."


def plan_display_name(plan_code: str) -> str:
    code = str(plan_code or "").strip().lower()
    if code == "trial":
        return trial_plan_name()
    if code == "start":
        return "Start"
    if code == "pro":
        return "Pro"
    return "--"


def infer_entitlement_plan(
    *,
    can_transcribe: bool,
    effective_until: Any = "",
    daily_minutes_limit: Any = None,
    monthly_minutes_limit: Any = None,
    has_paid_subscription: bool = False,
) -> EntitlementPlan:
    until_dt = parse_iso_datetime(effective_until)
    expired = bool(until_dt and until_dt <= datetime.now(timezone.utc))
    blocked = expired or (not bool(can_transcribe))
    if blocked:
        return EntitlementPlan(plan_code="", plan_name="", blocked=True)

    if is_trial_quota_limits(daily_minutes_limit, monthly_minutes_limit) and not has_paid_subscription:
        return EntitlementPlan(plan_code="trial", plan_name=trial_plan_name(), blocked=False)

    daily = normalize_int_or_none(daily_minutes_limit)
    if daily is None:
        return EntitlementPlan(plan_code="pro", plan_name="Pro", blocked=False)
    if daily >= START_DAILY_MINUTES:
        return EntitlementPlan(plan_code="start", plan_name="Start", blocked=False)
    return EntitlementPlan(plan_code="trial", plan_name=trial_plan_name(), blocked=False)


def format_seconds_compact(value: Any) -> str:
    try:
        total_seconds = max(0, int(round(float(value))))
    except (TypeError, ValueError):
        return "--"

    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours > 0:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m {seconds:02d}s"


def effective_message_format_mode(requested_mode: Any, correction_enabled: bool) -> str:
    raw = str(requested_mode or "").strip().lower()
    if not correction_enabled:
        return "balanced"
    return "message" if raw == "message" else "balanced"


def access_block_message(reason: str, access: dict | None = None) -> str:
    mapping = {
        "unauthenticated": "Sessão expirada. Faça login.",
        "no_entitlement": "Conta sem acesso (entitlement).",
        "transcription_disabled": "Seu plano não permite transcrição.",
        "entitlement_not_started": "Acesso ainda não iniciou.",
        "entitlement_expired": entitlement_expired_message(),
        "daily_limit_reached": "Limite diário atingido.",
        "daily_remaining_insufficient": "Tempo restante insuficiente.",
        "monthly_limit_reached": "Limite mensal atingido.",
        "monthly_remaining_insufficient": "Tempo mensal restante insuficiente.",
    }
    message = mapping.get(str(reason or "").strip(), "Acesso bloqueado.")
    if not isinstance(access, dict):
        return message

    if str(reason or "").startswith("monthly"):
        remaining = access.get("remaining_month_seconds", None)
        if remaining is not None:
            return f"{message} (restante no mês: {format_seconds_compact(remaining)})"
        return message

    remaining = access.get("remaining_seconds", None)
    if remaining is not None:
        return f"{message} (restante hoje: {format_seconds_compact(remaining)})"
    return message
