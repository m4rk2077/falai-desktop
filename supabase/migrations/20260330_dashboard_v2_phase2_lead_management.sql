-- DASH-006: Lead Management - Notes table + Funnel/At-Risk views

-- Helper function for RLS policies (create if not exists)
create or replace function public.current_user_role()
returns text
language sql
security definer
stable
as $$
  select coalesce(
    (select role from public.profiles where id = auth.uid()),
    'anonymous'
  );
$$;

-- Lead Notes table
create table if not exists public.lead_notes (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid not null references public.leads_beta(id) on delete cascade,
  author_id uuid not null references public.profiles(id) on delete set null,
  body text not null,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists ix_lead_notes_lead_created
  on public.lead_notes(lead_id, created_at desc);

alter table public.lead_notes enable row level security;

create policy lead_notes_staff_all on public.lead_notes
for all using (public.current_user_role() in ('admin', 'support'))
with check (public.current_user_role() in ('admin', 'support'));

-- Funnel Summary View
create or replace view analytics.vw_lead_funnel_summary as
with stages as (
  select
    count(*) filter (where true) as total,
    count(*) filter (where status = 'novo') as novos,
    count(*) filter (where status = 'provisionando') as provisionando,
    count(*) filter (where status = 'contatado') as contatados,
    count(*) filter (where status = 'ativado') as ativados,
    count(*) filter (where status = 'trial_expirado') as trial_expirados,
    count(*) filter (where status = 'convertido') as convertidos,
    count(*) filter (where status = 'desqualificado') as desqualificados,
    count(*) filter (where status = 'erro') as erros,
    count(*) filter (where created_at >= timezone('utc', now()) - interval '24 hours') as novos_24h,
    count(*) filter (where created_at >= timezone('utc', now()) - interval '7 days') as novos_7d,
    count(*) filter (where created_at >= timezone('utc', now()) - interval '30 days') as novos_30d
  from public.leads_beta
),
velocity as (
  select
    avg(extract(epoch from (first_login_at - created_at)) / 3600)
      filter (where first_login_at is not null) as avg_hours_to_login,
    avg(extract(epoch from (first_transcription_at - first_login_at)) / 3600)
      filter (where first_transcription_at is not null and first_login_at is not null)
      as avg_hours_to_first_transcription,
    avg(extract(epoch from (converted_at - created_at)) / 86400)
      filter (where converted_at is not null) as avg_days_to_conversion
  from public.leads_beta
)
select
  s.*,
  case when s.total > 0 then s.convertidos::numeric / s.total else 0 end as conversion_rate,
  case when s.total > 0 then s.contatados::numeric / s.total else 0 end as contact_rate,
  case when s.total > 0 then s.ativados::numeric / s.total else 0 end as activation_rate,
  v.avg_hours_to_login,
  v.avg_hours_to_first_transcription,
  v.avg_days_to_conversion
from stages s
cross join velocity v;

-- At-Risk Leads View
create or replace view analytics.vw_leads_at_risk as
select
  lb.id,
  lb.nome,
  lb.email,
  lb.status,
  lb.trial_ends_at,
  lb.first_login_at,
  lb.first_transcription_at,
  lb.created_at,
  extract(epoch from (lb.trial_ends_at - timezone('utc', now()))) / 3600 as hours_until_trial_end,
  case
    when lb.first_transcription_at is null and lb.first_login_at is not null
      then 'logged_in_no_transcription'
    when lb.first_login_at is null
      then 'never_logged_in'
    when lb.trial_ends_at <= timezone('utc', now()) + interval '48 hours'
      then 'trial_expiring_soon'
    else 'other'
  end as risk_reason
from public.leads_beta lb
where lb.status in ('contatado', 'ativado', 'provisionando')
  and lb.converted_at is null
  and (
    (lb.trial_ends_at is not null and lb.trial_ends_at <= timezone('utc', now()) + interval '48 hours')
    or (lb.provisioned_at is not null and lb.first_login_at is null
        and lb.provisioned_at <= timezone('utc', now()) - interval '24 hours')
    or (lb.first_login_at is not null and lb.first_transcription_at is null
        and lb.first_login_at <= timezone('utc', now()) - interval '48 hours')
  )
order by lb.trial_ends_at asc nulls last;
