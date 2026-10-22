-- =====================================================================
-- AGR.ID — Migration 0003: Perbaikan RLS & Hak Akses Supabase
-- =====================================================================

-- 1. Izin skema dasar
grant usage on schema public to anon, authenticated, service_role;
grant all on all tables in schema public to service_role;
grant all on all sequences in schema public to service_role;
grant all on all routines in schema public to service_role;

-- 2. Hak akses tabel publik untuk anon & authenticated
grant select on public.users to anon, authenticated;
grant select on public.product_master to anon, authenticated;
grant select on public.products to anon, authenticated;
grant select on public.pengaturan to anon, authenticated;
grant select on public.ratings to anon, authenticated;
grant select on public.eviden to anon, authenticated;

-- 3. Hak akses sessions & registrasi untuk anon & authenticated
grant insert, select, delete, update on public.sessions to anon, authenticated;
grant insert, select on public.users to anon, authenticated;
grant usage, select on all sequences in schema public to anon, authenticated;

-- 4. Perbarui RLS policies
drop policy if exists "users_public_profile" on public.users;
drop policy if exists "users_public_login" on public.users;
create policy "users_public_login" on public.users
  for select using (role in ('penjual', 'pembeli', 'admin'));

drop policy if exists "users_public_insert" on public.users;
create policy "users_public_insert" on public.users
  for insert with check (role in ('penjual', 'pembeli'));

drop policy if exists "sessions_anon_all" on public.sessions;
create policy "sessions_anon_all" on public.sessions
  for all using (true) with check (true);

drop policy if exists "pengaturan_public_read" on public.pengaturan;
create policy "pengaturan_public_read" on public.pengaturan
  for select using (true);
