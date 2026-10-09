-- DASH-012: Email Cadence Engine tables

-- Email Cadences
create table if not exists public.email_cadences (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  description text,
  trigger_event text not null,
  is_active boolean not null default true,
  created_by uuid references public.profiles(id) on delete set null,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create unique index if not exists ux_email_cadences_name
  on public.email_cadences(name) where is_active = true;

alter table public.email_cadences enable row level security;

create policy email_cadences_staff on public.email_cadences
for all using (public.current_user_role() in ('admin', 'support'))
with check (public.current_user_role() in ('admin', 'support'));

-- Cadence Steps
create table if not exists public.cadence_steps (
  id uuid primary key default gen_random_uuid(),
  cadence_id uuid not null references public.email_cadences(id) on delete cascade,
  step_order int not null,
  delay_hours int not null default 0,
  channel text not null default 'email'
    check (channel in ('email', 'whatsapp')),
  subject text,
  body_template text not null,
  condition_sql text,
  is_active boolean not null default true,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  unique (cadence_id, step_order)
);

create index if not exists ix_cadence_steps_cadence
  on public.cadence_steps(cadence_id, step_order);

alter table public.cadence_steps enable row level security;

create policy cadence_steps_staff on public.cadence_steps
for all using (public.current_user_role() in ('admin', 'support'))
with check (public.current_user_role() in ('admin', 'support'));

-- Cadence Enrollments
create table if not exists public.cadence_enrollments (
  id uuid primary key default gen_random_uuid(),
  cadence_id uuid not null references public.email_cadences(id) on delete cascade,
  lead_id uuid not null references public.leads_beta(id) on delete cascade,
  status text not null default 'active'
    check (status in ('active', 'paused', 'completed', 'cancelled')),
  current_step int not null default 0,
  next_step_at timestamptz,
  enrolled_at timestamptz not null default timezone('utc', now()),
  completed_at timestamptz,
  cancelled_at timestamptz,
  cancel_reason text,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create unique index if not exists ux_cadence_enrollments_active
  on public.cadence_enrollments(cadence_id, lead_id)
  where status = 'active';

create index if not exists ix_cadence_enrollments_next_step
  on public.cadence_enrollments(next_step_at)
  where status = 'active' and next_step_at is not null;

alter table public.cadence_enrollments enable row level security;

create policy cadence_enrollments_staff on public.cadence_enrollments
for all using (public.current_user_role() in ('admin', 'support'))
with check (public.current_user_role() in ('admin', 'support'));

-- Email Sends
create table if not exists public.email_sends (
  id uuid primary key default gen_random_uuid(),
  enrollment_id uuid not null references public.cadence_enrollments(id) on delete cascade,
  step_id uuid not null references public.cadence_steps(id) on delete cascade,
  lead_id uuid not null references public.leads_beta(id) on delete cascade,
  status text not null default 'pending'
    check (status in ('pending', 'sending', 'delivered', 'opened', 'clicked', 'bounced', 'complained', 'failed', 'skipped')),
  channel text not null default 'email',
  to_address text not null,
  subject text,
  sent_at timestamptz,
  delivered_at timestamptz,
  opened_at timestamptz,
  clicked_at timestamptz,
  bounced_at timestamptz,
  provider_message_id text,
  error_message text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists ix_email_sends_enrollment on public.email_sends(enrollment_id);
create index if not exists ix_email_sends_lead on public.email_sends(lead_id, created_at desc);
create index if not exists ix_email_sends_status_pending on public.email_sends(status) where status = 'pending';

alter table public.email_sends enable row level security;

create policy email_sends_staff on public.email_sends
for all using (public.current_user_role() in ('admin', 'support'))
with check (public.current_user_role() in ('admin', 'support'));

-- Cadence Metrics View
create or replace view analytics.vw_cadence_metrics as
select
  cs.cadence_id,
  cs.id as step_id,
  cs.step_order,
  cs.subject,
  count(es.id) as total_sends,
  count(es.id) filter (where es.status = 'delivered') as delivered,
  count(es.id) filter (where es.status in ('opened', 'clicked')) as opened,
  count(es.id) filter (where es.status = 'clicked') as clicked,
  count(es.id) filter (where es.status = 'bounced') as bounced,
  count(es.id) filter (where es.status = 'complained') as complained,
  count(es.id) filter (where es.status = 'failed') as failed,
  count(es.id) filter (where es.status = 'skipped') as skipped,
  case when count(es.id) > 0
    then count(es.id) filter (where es.status in ('opened', 'clicked'))::numeric / count(es.id)
    else 0
  end as open_rate,
  case when count(es.id) > 0
    then count(es.id) filter (where es.status = 'clicked')::numeric / count(es.id)
    else 0
  end as click_rate,
  case when count(es.id) > 0
    then count(es.id) filter (where es.status = 'bounced')::numeric / count(es.id)
    else 0
  end as bounce_rate
from public.cadence_steps cs
left join public.email_sends es on es.step_id = cs.id
group by cs.cadence_id, cs.id, cs.step_order, cs.subject;

-- Seed: Default cadences
insert into public.email_cadences (name, trigger_event, description) values
  ('Trial Onboarding', 'account_created', 'Sequencia de nurturing para novos trials'),
  ('Win-back', 'trial_expired', 'Recuperacao de leads com trial expirado'),
  ('Post Conversion', 'subscription_activated', 'Boas-vindas para assinantes')
on conflict do nothing;
