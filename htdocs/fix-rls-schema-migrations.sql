-- =====================================================================
-- AGR.ID — Perbaikan issue Supabase Advisor:
-- "Table `public.schema_migrations` is public, but RLS has not been enabled."
--
-- Jalankan di: Supabase Dashboard -> SQL Editor -> New query -> Run
-- (Idempoten: aman dijalankan berulang kali.)
-- =====================================================================

-- 1. Pastikan tabel ada (dibuat oleh idempotency guard GitHub Actions)
create table if not exists schema_migrations (
  version    text primary key,
  name       text,
  applied_at timestamptz default now()
);

-- 2. Aktifkan Row Level Security -> anon/authenticated tidak melihat apa pun
alter table schema_migrations enable row level security;

-- 3. Cabut grant publik (lapisan kedua; hanya service_role yang boleh akses)
revoke all on schema_migrations from anon, authenticated;

-- 4. Verifikasi hasil
select
  c.relname                          as tabel,
  c.relrowsecurity                   as rls_aktif,
  pg_catalog.obj_description(c.oid)  as komentar
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relkind = 'r'
order by c.relname;

-- Cek cepat satu baris:
-- select relname, relrowsecurity from pg_class
-- where relname = 'schema_migrations';  -- => harus true
