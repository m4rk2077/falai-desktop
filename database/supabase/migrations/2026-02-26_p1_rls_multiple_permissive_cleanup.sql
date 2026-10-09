-- P1 performance pass:
-- Remove multiple permissive SELECT overlap by replacing FOR ALL policies
-- with explicit INSERT/UPDATE/DELETE policies.

-- ---------------------------------------------------------------------------
-- user_devices
-- ---------------------------------------------------------------------------
drop policy if exists user_devices_modify_own on public.user_devices;

create policy user_devices_insert_own
on public.user_devices
as permissive
for insert
to public
with check (user_id = (select auth.uid()));

create policy user_devices_update_own
on public.user_devices
as permissive
for update
to public
using (user_id = (select auth.uid()))
with check (user_id = (select auth.uid()));

create policy user_devices_delete_own
on public.user_devices
as permissive
for delete
to public
using (user_id = (select auth.uid()));

-- ---------------------------------------------------------------------------
-- user_settings
-- ---------------------------------------------------------------------------
drop policy if exists user_settings_modify_own on public.user_settings;

create policy user_settings_insert_own
on public.user_settings
as permissive
for insert
to public
with check (user_id = (select auth.uid()));

create policy user_settings_update_own
on public.user_settings
as permissive
for update
to public
using (user_id = (select auth.uid()))
with check (user_id = (select auth.uid()));

create policy user_settings_delete_own
on public.user_settings
as permissive
for delete
to public
using (user_id = (select auth.uid()));

-- ---------------------------------------------------------------------------
-- device_settings
-- ---------------------------------------------------------------------------
drop policy if exists device_settings_modify_own on public.device_settings;

create policy device_settings_insert_own
on public.device_settings
as permissive
for insert
to public
with check (
  exists (
    select 1
    from public.user_devices d
    where d.id = device_settings.device_id
      and d.user_id = (select auth.uid())
  )
);

create policy device_settings_update_own
on public.device_settings
as permissive
for update
to public
using (
  exists (
    select 1
    from public.user_devices d
    where d.id = device_settings.device_id
      and d.user_id = (select auth.uid())
  )
)
with check (
  exists (
    select 1
    from public.user_devices d
    where d.id = device_settings.device_id
      and d.user_id = (select auth.uid())
  )
);

create policy device_settings_delete_own
on public.device_settings
as permissive
for delete
to public
using (
  exists (
    select 1
    from public.user_devices d
    where d.id = device_settings.device_id
      and d.user_id = (select auth.uid())
  )
);

