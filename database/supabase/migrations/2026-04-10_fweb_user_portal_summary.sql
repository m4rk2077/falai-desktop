-- FWEB-012 — vw_user_portal_summary
-- Single query powering the portal dashboard. Joins plan, trial, 30d usage and active pairings.
-- Designed to run in < 50ms for a single user via RLS.

begin;

create or replace view public.vw_user_portal_summary
with (security_invoker = true)
as
with me as (
  select auth.uid() as user_id
),
plan_info as (
  select
    m.user_id,
    coalesce(s.status, 'none')                                      as subscription_status,
    coalesce(p.code, 'trial')                                       as plan_code,
    coalesce(p.tier, 'trial')                                       as plan_tier,
    s.current_period_end                                            as current_period_end,
    s.trial_ends_at                                                 as trial_ends_at,
    greatest(0, extract(epoch from (s.trial_ends_at - now()))/86400.0)::numeric(10,2) as trial_days_left
  from me m
  left join public.subscriptions s on s.user_id = m.user_id and s.status in ('trialing','active','past_due')
  left join public.plans p on p.id = s.plan_id
),
usage_30d as (
  select
    m.user_id,
    coalesce(sum(t.audio_duration_seconds),0)::bigint               as audio_seconds_30d,
    coalesce(sum(t.word_count),0)::bigint                           as words_30d,
    coalesce(count(*),0)::bigint                                    as transcriptions_30d
  from me m
  left join public.transcriptions t
    on t.user_id = m.user_id
   and t.created_at >= now() - interval '30 days'
   and coalesce(t.status,'done') = 'done'
  group by m.user_id
),
pairings_active as (
  select
    m.user_id,
    coalesce(count(*) filter (
      where ep.revoked_at is null
        and ep.used_at is not null
        and ep.expires_at > now() - interval '180 days'
    ),0)::bigint as active_pairings
  from me m
  left join public.extension_pairings ep on ep.user_id = m.user_id
  group by m.user_id
)
select
  pi.user_id,
  pi.plan_code,
  pi.plan_tier,
  pi.subscription_status,
  pi.current_period_end,
  pi.trial_ends_at,
  pi.trial_days_left,
  u.audio_seconds_30d,
  round(u.audio_seconds_30d / 60.0, 2)                               as minutes_used_30d,
  u.words_30d,
  u.transcriptions_30d,
  -- Time saved estimate: assume speaking 150 wpm, typing 40 wpm.
  round((u.words_30d::numeric / nullif(40,0)) - (u.words_30d::numeric / nullif(150,0)), 2) as time_saved_minutes_30d,
  pa.active_pairings,
  (pi.plan_tier = 'pro' and pi.subscription_status in ('active','trialing')) as has_desktop_access
from plan_info pi
join usage_30d u on u.user_id = pi.user_id
join pairings_active pa on pa.user_id = pi.user_id;

comment on view public.vw_user_portal_summary is
  'FWEB-012 — one-shot dashboard summary for the portal. security_invoker = RLS of underlying tables applies.';

grant select on public.vw_user_portal_summary to authenticated;

commit;
