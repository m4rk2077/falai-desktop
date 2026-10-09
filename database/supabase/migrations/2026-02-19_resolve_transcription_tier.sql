-- FALAI - Speed tiers helper (trial/start/pro) for transcription pipeline
-- Date: 2026-02-19
-- Safe to execute multiple times.

create or replace function public.resolve_transcription_tier(p_user_id uuid default null::uuid)
returns table(
  tier text,
  plan_code text,
  entitlement_source text,
  daily_minutes_limit int
)
language plpgsql
set search_path = 'public'
as $$
declare
  v_uid uuid := coalesce(p_user_id, auth.uid());
  v_sub record;
  v_ent public.user_entitlements%rowtype;
begin
  if v_uid is null then
    return query select 'trial'::text, 'trial'::text, 'none'::text, null::int;
    return;
  end if;

  -- Priority 1: active/trialing subscription linked to plan code.
  select
    p.code as code,
    case
      when (p.limits ? 'daily_minutes_limit') then nullif(p.limits ->> 'daily_minutes_limit', '')::int
      else null::int
    end as daily_limit
  into v_sub
  from public.subscriptions s
  join public.plans p on p.id = s.plan_id
  where s.user_id = v_uid
    and s.status in ('active', 'trialing')
  order by
    case when s.status = 'active' then 2 else 1 end desc,
    coalesce(s.updated_at, s.created_at) desc
  limit 1;

  if found and coalesce(v_sub.code, '') <> '' then
    if v_sub.code = 'pro' then
      return query select 'pro'::text, 'pro'::text, 'subscription'::text, v_sub.daily_limit;
      return;
    end if;
    if v_sub.code = 'start' then
      return query select 'start'::text, 'start'::text, 'subscription'::text, v_sub.daily_limit;
      return;
    end if;
  end if;

  -- Priority 2: entitlement fallback (beta/manual/promo scenarios).
  select *
  into v_ent
  from public.user_entitlements
  where user_id = v_uid
  limit 1;

  if v_ent.user_id is null then
    return query select 'trial'::text, 'trial'::text, 'none'::text, null::int;
    return;
  end if;

  if v_ent.daily_minutes_limit is null then
    return query select 'pro'::text, 'pro'::text, coalesce(v_ent.source, 'plan')::text, null::int;
    return;
  end if;

  if v_ent.daily_minutes_limit >= 30 then
    return query select 'start'::text, 'start'::text, coalesce(v_ent.source, 'plan')::text, v_ent.daily_minutes_limit;
    return;
  end if;

  return query
    select 'trial'::text, 'trial'::text, coalesce(v_ent.source, 'plan')::text, v_ent.daily_minutes_limit;
end;
$$;
