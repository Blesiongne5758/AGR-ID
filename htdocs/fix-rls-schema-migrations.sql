-- =====================================================================
-- AGR.ID — Perbaikan issue Supabase Advisor:
-- "Table public.schema_migrations is public, but RLS has not been enabled."
-- Sekaligus audit RLS seluruh tabel publik.
-- Jalankan di: Supabase Dashboard -> SQL Editor -> Run (idempoten)
-- =====================================================================

create table if not exists schema_migrations (
  version    text primary key,
  name       text,
  applied_at timestamptz default now()
);

alter table schema_migrations enable row level security;
revoke all on schema_migrations from anon, authenticated;

insert into public.schema_migrations (version, name)
values ('002_rls_schema_migrations','RLS on schema_migrations')
on conflict (version) do nothing;

-- Audit: daftar SEMUA tabel publik beserta status RLS-nya
select c.relname as tabel,
       case when c.relrowsecurity then 'AKTIF' else '❌ BELUM' end as rls
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind = 'r'
order by c.relname;
