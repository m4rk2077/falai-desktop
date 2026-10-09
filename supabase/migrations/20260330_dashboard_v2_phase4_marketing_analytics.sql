-- DASH-018: Marketing Analytics - Cohort View + Attribution MV

-- Weekly Cohort View
create or replace view analytics.vw_cohort_weekly as
with cohorts as (
  select
    id,
    date_trunc('week', created_at)::date as cohort_week,
    created_at,
    first_login_at,
    first_transcription_at,
    converted_at,
    status
  from public.leads_beta
  where created_at >= timezone('utc', now()) - interval '90 days'
),
weeks as (
  select generate_series(0, 12) as week_offset
)
select
  c.cohort_week,
  count(distinct c.id) as cohort_size,
  w.week_offset,
  count(distinct c.id) filter (
    where c.first_login_at is not null
      and c.first_login_at < c.cohort_week + ((w.week_offset + 1) * interval '7 days')
  ) as logged_in,
  count(distinct c.id) filter (
    where c.first_transcription_at is not null
      and c.first_transcription_at < c.cohort_week + ((w.week_offset + 1) * interval '7 days')
  ) as transcribed,
  count(distinct c.id) filter (
    where c.converted_at is not null
      and c.converted_at < c.cohort_week + ((w.week_offset + 1) * interval '7 days')
  ) as converted
from cohorts c
cross join weeks w
where c.cohort_week + (w.week_offset * interval '7 days') <= timezone('utc', now())
group by c.cohort_week, w.week_offset
order by c.cohort_week desc, w.week_offset asc;

-- Marketing Attribution Materialized View
create materialized view if not exists analytics.marketing_attribution_mv as
with lead_with_source as (
  select
    lb.id,
    lb.created_at,
    lb.status,
    lb.converted_at,
    lb.utm_source,
    lb.utm_medium,
    lb.utm_campaign,
    lb.landing_variant,
    coalesce(lb.utm_source, 'direct') as source_channel,
    case
      when lb.gclid is not null then 'google_ads'
      when lb.fbclid is not null then 'meta_ads'
      when lb.utm_source is not null then lb.utm_source
      else 'organic'
    end as attribution_channel
  from public.leads_beta lb
)
select
  attribution_channel,
  coalesce(utm_campaign, '(none)') as campaign,
  coalesce(utm_medium, '(none)') as medium,
  coalesce(landing_variant, '(none)') as landing_variant,
  count(*) as total_leads,
  count(*) filter (where converted_at is not null) as conversions,
  case when count(*) > 0
    then count(*) filter (where converted_at is not null)::numeric / count(*)
    else 0
  end as conversion_rate,
  avg(extract(epoch from (converted_at - created_at)) / 86400)
    filter (where converted_at is not null) as avg_days_to_conversion
from lead_with_source
group by attribution_channel, utm_campaign, utm_medium, landing_variant;

create unique index if not exists ux_marketing_attribution_mv
  on analytics.marketing_attribution_mv(attribution_channel, campaign, medium, landing_variant);

-- Schedule daily refresh at 03:00 UTC
select cron.schedule(
  'refresh-marketing-attribution',
  '0 3 * * *',
  'refresh materialized view concurrently analytics.marketing_attribution_mv'
);

-- CAC Estimation View
create or replace view analytics.vw_cac_estimation as
select
  case
    when lb.gclid is not null then 'google_ads'
    when lb.fbclid is not null then 'meta_ads'
    when lb.utm_source is not null then lb.utm_source
    else 'organic'
  end as channel,
  count(*) as total_leads,
  count(*) filter (where lb.converted_at is not null) as conversions
from public.leads_beta lb
group by 1;
