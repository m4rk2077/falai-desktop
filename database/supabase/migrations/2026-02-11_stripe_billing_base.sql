-- FALAI - Stripe billing baseline (app + supabase alignment)
-- Safe to run multiple times.

-- 1) Profiles: store Stripe customer mapping (1:1)
alter table if exists public.profiles
  add column if not exists stripe_customer_id text;

do $$
begin
  if not exists (
    select 1
    from pg_indexes
    where schemaname = 'public'
      and tablename = 'profiles'
      and indexname = 'ux_profiles_stripe_customer_id'
  ) then
    create unique index ux_profiles_stripe_customer_id
      on public.profiles(stripe_customer_id)
      where stripe_customer_id is not null;
  end if;
end;
$$;

-- 2) Plans: Stripe references (price + payment link)
alter table if exists public.plans
  add column if not exists stripe_price_id text,
  add column if not exists stripe_payment_link_url text;

-- 3) Subscriptions: provider identifiers to reconcile webhooks
alter table if exists public.subscriptions
  add column if not exists provider_customer_id text,
  add column if not exists provider_price_id text,
  add column if not exists provider_checkout_session_id text;

create index if not exists ix_subscriptions_provider_subscription_id
  on public.subscriptions(provider_subscription_id);

create index if not exists ix_subscriptions_provider_customer_id
  on public.subscriptions(provider_customer_id);

-- 4) Align Start plan with product UI (30 min/day = 900 min/month)
update public.plans
set limits = jsonb_set(
      jsonb_set(coalesce(limits, '{}'::jsonb), '{daily_minutes_limit}', '30'::jsonb, true),
      '{monthly_minutes_limit}', '900'::jsonb, true
    ),
    updated_at = timezone('utc', now())
where code = 'start'
  and (
    coalesce((limits ->> 'daily_minutes_limit')::int, 0) <> 30
    or coalesce((limits ->> 'monthly_minutes_limit')::int, 0) <> 900
  );

-- 5) Keep function hardening in source-of-truth migrations too
do $$
begin
  if exists (
    select 1
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and p.proname = 'set_updated_at'
  ) then
    execute 'alter function public.set_updated_at() set search_path = public, pg_temp';
  end if;

  if exists (
    select 1
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and p.proname = 'word_count_from_text'
      and pg_get_function_identity_arguments(p.oid) = 'input_text text'
  ) then
    execute 'alter function public.word_count_from_text(input_text text) set search_path = public, pg_temp';
  end if;
end;
$$;
