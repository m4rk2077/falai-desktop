from datetime import datetime, timedelta, timezone

from src.config.plan_rules import (
    access_block_message,
    effective_message_format_mode,
    entitlement_expired_message,
    infer_entitlement_plan,
    is_trial_quota_limits,
    plan_display_name,
    trial_expired_body,
    trial_plan_name,
    trial_plan_subtitle,
)


def test_trial_copy_uses_current_window():
    assert trial_plan_name() == "Trial 7 dias"
    assert trial_plan_subtitle() == "Teste grátis por 7 dias · 15 min/dia · Sem cartão"
    assert "7 dias" in trial_expired_body()
    assert entitlement_expired_message() == "Teste encerrado (7 dias). Veja planos."


def test_trial_limits_are_detected_from_entitlement_values():
    assert is_trial_quota_limits(15, 450) is True
    assert is_trial_quota_limits(30, 900) is False
    assert is_trial_quota_limits(None, 450) is False


def test_infer_entitlement_plan_classifies_trial_start_and_pro():
    trial_plan = infer_entitlement_plan(
        can_transcribe=True,
        effective_until=(datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
        daily_minutes_limit=15,
        monthly_minutes_limit=450,
        has_paid_subscription=False,
    )
    assert trial_plan.plan_code == "trial"
    assert trial_plan.plan_name == "Trial 7 dias"
    assert trial_plan.blocked is False

    start_plan = infer_entitlement_plan(
        can_transcribe=True,
        effective_until="",
        daily_minutes_limit=30,
        monthly_minutes_limit=900,
        has_paid_subscription=True,
    )
    assert start_plan.plan_code == "start"
    assert start_plan.plan_name == "Start"
    assert start_plan.blocked is False

    pro_plan = infer_entitlement_plan(
        can_transcribe=True,
        effective_until="",
        daily_minutes_limit=None,
        monthly_minutes_limit=None,
        has_paid_subscription=True,
    )
    assert pro_plan.plan_code == "pro"
    assert pro_plan.plan_name == "Pro"
    assert pro_plan.blocked is False


def test_infer_entitlement_plan_marks_expired_or_disabled_as_blocked():
    expired = infer_entitlement_plan(
        can_transcribe=True,
        effective_until=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        daily_minutes_limit=15,
        monthly_minutes_limit=450,
        has_paid_subscription=False,
    )
    assert expired.blocked is True
    assert expired.plan_code == ""

    disabled = infer_entitlement_plan(
        can_transcribe=False,
        effective_until="",
        daily_minutes_limit=30,
        monthly_minutes_limit=900,
        has_paid_subscription=True,
    )
    assert disabled.blocked is True
    assert disabled.plan_code == ""


def test_access_block_message_formats_remaining_time_for_daily_and_monthly_caps():
    daily_msg = access_block_message(
        "daily_remaining_insufficient",
        {"remaining_seconds": 75},
    )
    assert daily_msg == "Tempo restante insuficiente. (restante hoje: 1m 15s)"

    monthly_msg = access_block_message(
        "monthly_remaining_insufficient",
        {"remaining_month_seconds": 3665},
    )
    assert monthly_msg == "Tempo mensal restante insuficiente. (restante no mês: 1h 01m)"


def test_plan_display_name_uses_shared_trial_label():
    assert plan_display_name("trial") == "Trial 7 dias"
    assert plan_display_name("start") == "Start"
    assert plan_display_name("pro") == "Pro"


def test_effective_message_format_mode_depends_on_correction_toggle():
    assert effective_message_format_mode("message", correction_enabled=True) == "message"
    assert effective_message_format_mode("balanced", correction_enabled=True) == "balanced"
    assert effective_message_format_mode("message", correction_enabled=False) == "balanced"
