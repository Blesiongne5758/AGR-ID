-- =====================================================================
-- AGR.ID — Perbaikan RLS & Hak Akses Supabase
-- Menjamin user & admin dapat login, sesi dapat disimpan,
-- dan registrasi serta pengaturan dapat diakses.
-- Idempoten: aman dijalankan berulang kali.
-- =====================================================================

create table if not exists schema_migrations (
  version    text primary key,
  applied_at timestamptz default now(),
  checksum   text
);

alter table schema_migrations enable row level security;
revoke all on schema_migrations from anon, authenticated;

insert into public.schema_migrations (version)
values ('002_rls_schema_migrations')
on conflict (version) do nothing;

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
-- Users: izinkan select untuk autentikasi semua role (penjual, pembeli, admin)
drop policy if exists "users_public_profile" on public.users;
drop policy if exists "users_public_login" on public.users;
create policy "users_public_login" on public.users
  for select using (role in ('penjual', 'pembeli', 'admin'));

-- Users: izinkan registrasi publik (penjual & pembeli)
drop policy if exists "users_public_insert" on public.users;
create policy "users_public_insert" on public.users
  for insert with check (role in ('penjual', 'pembeli'));

-- Sessions: izinkan pengelolaan sesi login
drop policy if exists "sessions_anon_all" on public.sessions;
create policy "sessions_anon_all" on public.sessions
  for all using (true) with check (true);

-- Pengaturan: izinkan publik membaca pengaturan platform
drop policy if exists "pengaturan_public_read" on public.pengaturan;
create policy "pengaturan_public_read" on public.pengaturan
  for select using (true);

insert into public.schema_migrations (version)
values ('003_fix_rls_and_permissions')
on conflict (version) do nothing;

-- Audit: daftar SEMUA tabel publik beserta status RLS-nya
select c.relname as tabel,
       case when c.relrowsecurity then 'AKTIF' else '❌ BELUM' end as rls
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind = 'r'
order by c.relname;
