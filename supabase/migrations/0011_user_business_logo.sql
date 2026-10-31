-- Store the seller's business logo as a public object-storage reference.
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS logo_url VARCHAR(500);

INSERT INTO public.schema_migrations(version)
VALUES ('0011_user_business_logo')
ON CONFLICT (version) DO NOTHING;
