-- Pendaftaran minimum: email, username, kata sandi.
-- Akun baru memulai sebagai pembeli dan baru mendapat mode penjual setelah
-- profil lengkap melalui pengaturan pengguna.

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS username text;

UPDATE public.users
SET username = COALESCE(
  NULLIF(btrim(username), ''),
  COALESCE(NULLIF(regexp_replace(lower(split_part(email, '@', 1)), '[^a-z0-9_.-]', '', 'g'), ''), 'user') || '_' || id::text
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON public.users(username);
ALTER TABLE public.users ALTER COLUMN username SET NOT NULL;
