-- Index auction foreign-key columns that are queried during event and package lookups.
CREATE INDEX IF NOT EXISTS ix_lelang_events_pemenang_id
  ON public.lelang_events(pemenang_id);
CREATE INDEX IF NOT EXISTS ix_lelang_items_product_id
  ON public.lelang_items(product_id);

INSERT INTO public.schema_migrations(version)
VALUES ('0014_auction_foreign_key_indexes')
ON CONFLICT (version) DO NOTHING;
