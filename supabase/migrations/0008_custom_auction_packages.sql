-- Allow seller auctions to describe a custom package without reserving listings.
ALTER TABLE IF EXISTS public.lelang_events
  ADD COLUMN IF NOT EXISTS kriteria_paket TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS paket_kustom BOOLEAN NOT NULL DEFAULT FALSE;
