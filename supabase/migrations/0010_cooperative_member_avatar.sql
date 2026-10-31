-- Store the member profile image reference used by the digital cooperative card.
-- The object itself stays in the configured object storage/CDN, not PostgreSQL.
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(500);

INSERT INTO public.schema_migrations(version)
VALUES ('0010_cooperative_member_avatar')
ON CONFLICT (version) DO NOTHING;
