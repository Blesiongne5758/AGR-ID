-- Satu akun dapat beroperasi sebagai penjual maupun pembeli.
-- Peran aktif disimpan per sesi agar perangkat yang berbeda dapat memakai mode berbeda.

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS roles jsonb,
  ADD COLUMN IF NOT EXISTS tipe_penjual text,
  ADD COLUMN IF NOT EXISTS tipe_pembeli text;

UPDATE public.users
SET roles = CASE
      WHEN roles IS NULL OR roles = '[]'::jsonb THEN
        CASE WHEN role = 'admin' THEN '["admin"]'::jsonb
             ELSE '["penjual","pembeli"]'::jsonb END
      ELSE roles
    END,
    tipe_penjual = COALESCE(
      tipe_penjual,
      CASE WHEN role = 'penjual' AND tipe IN ('Perorangan','Kelompok/Paguyuban','Koperasi','Perusahaan')
           THEN tipe END,
      NULL
    ),
    tipe_pembeli = COALESCE(
      tipe_pembeli,
      CASE WHEN tipe IN ('Perorangan','Yayasan','Koperasi','Perusahaan')
           THEN tipe END,
      'Perorangan'
    );

ALTER TABLE public.users
  ALTER COLUMN roles SET DEFAULT '["pembeli"]'::jsonb,
  ALTER COLUMN roles SET NOT NULL,
  ALTER COLUMN tipe_penjual DROP DEFAULT,
  ALTER COLUMN tipe_pembeli SET DEFAULT 'Perorangan';

ALTER TABLE public.sessions
  ADD COLUMN IF NOT EXISTS active_role text;

UPDATE public.sessions AS s
SET active_role = u.role
FROM public.users AS u
WHERE s.user_id = u.id AND s.active_role IS NULL;

CREATE INDEX IF NOT EXISTS idx_users_roles ON public.users USING gin (roles);
