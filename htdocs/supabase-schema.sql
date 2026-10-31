-- =====================================================================
-- AGR.BIZ.ID — Skema database Supabase (PostgreSQL)
-- Jalankan di: Supabase Dashboard -> SQL Editor -> New query -> Run
-- =====================================================================

create extension if not exists pgcrypto;

-- USERS (penjual, pembeli, admin)
create table if not exists users (
  id            bigint generated always as identity primary key,
  email         text unique not null,
  username      text unique not null,
  nama          text not null,
  password_hash text not null,               -- bcrypt dari gateway PHP
  role          text not null check (role in ('penjual','pembeli','admin')),
  tipe          text default 'Perorangan',   -- Sesuai peran: Penjual (Perorangan/Kelompok-Paguyuban/Koperasi/Perusahaan), Pembeli (Perorangan/Yayasan/Koperasi/Perusahaan)
  roles         jsonb not null default '[]'::jsonb,
  tipe_penjual  text,
  tipe_pembeli  text default 'Perorangan',
  alamat        text,
  lat           double precision,            -- koordinat GPS
  lng           double precision,
  no_hp         text,
  npwp          text,                        -- Yayasan/Koperasi/Perusahaan
  nib           text,
  crypto_address text,                       -- dompet AGR Coin (bridge Flask)
  created_at    timestamptz default now()
);

-- SESSIONS (token pengganti cookie, dibuat gateway api.php)
create table if not exists sessions (
  id         bigint generated always as identity primary key,
  user_id    bigint references users(id) on delete cascade,
  token      text unique not null,
  active_role text,
  expires_at timestamptz not null
);

-- MASTER PRODUK (auto-update saat penjual mengetik nama produk baru)
create table if not exists product_master (
  id         bigint generated always as identity primary key,
  nama       text unique not null,
  kategori   text,
  sub_kategori text,
  jenis      text,                            -- varietas/tipe
  auto_added boolean default false,
  created_at timestamptz default now()
);

-- PRODUCTS (listing penjual)
create table if not exists products (
  id           bigint generated always as identity primary key,
  user_id      bigint references users(id) on delete cascade,
  nama_product text not null,
  jenis        text,
  kategori     text not null,                 -- Pertanian/Perkebunan/Perikanan/Peternakan
  sub_kategori text,                          -- Sayuran/Buah-buahan/Air Tawar/Air Laut/Babi(dll)
  deskripsi    text,
  harga        numeric(14,2) not null,
  satuan       text not null,                 -- kg/pack/ekor/lusin
  stok         integer default 0,
  foto         text,                          -- URL Cloudinary (bucket publik)
  lat          double precision,
  lng          double precision,
  alamat_lahan text,
  status       text default 'aktif',
  created_at   timestamptz default now(),
  updated_at   timestamptz
);
create index if not exists idx_products_kategori on products(kategori, sub_kategori);
create index if not exists idx_products_seller   on products(user_id);

-- PESAN PRODUK (buyer ↔ seller pemilik listing). Akses aplikasi melalui RPC
-- terautentikasi di migration 0006_product_chat.sql; tabel tetap privat dari anon.
create table if not exists product_conversations (
  id bigint generated always as identity primary key,
  product_id bigint not null references products(id) on delete cascade,
  buyer_id bigint not null references users(id) on delete cascade,
  seller_id bigint not null references users(id) on delete cascade,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (product_id, buyer_id),
  check (buyer_id <> seller_id)
);
create index if not exists idx_product_conversations_buyer on product_conversations(buyer_id, updated_at desc);
create index if not exists idx_product_conversations_seller on product_conversations(seller_id, updated_at desc);
create table if not exists product_chat_messages (
  id bigint generated always as identity primary key,
  conversation_id bigint not null references product_conversations(id) on delete cascade,
  sender_id bigint references users(id) on delete set null,
  body text not null check (char_length(body) between 1 and 2000),
  is_system boolean not null default false,
  created_at timestamptz not null default now()
);
create index if not exists idx_product_chat_messages_conversation on product_chat_messages(conversation_id, created_at, id);

-- OFFERS (penawaran harga buyer -> seller)
create table if not exists offers (
  id           bigint generated always as identity primary key,
  product_id   bigint references products(id) on delete cascade,
  buyer_id     bigint references users(id),
  harga_tawar  numeric(14,2) not null,
  jumlah       numeric(12,2) default 1,
  catatan      text,
  status       text default 'menunggu',       -- menunggu/diterima/ditolak/kedaluwarsa
  responded_at timestamptz,
  created_at   timestamptz default now()
);

-- BOOKINGS (DP sebagai pengikat)
create table if not exists bookings (
  id           bigint generated always as identity primary key,
  offer_id     bigint references offers(id) on delete set null,
  buyer_id     bigint references users(id),
  total        numeric(14,2) not null,
  dp           numeric(14,2) not null,        -- dihitung dari persen_dp pengaturan
  sisa         numeric(14,2) not null,
  metode_dp    text default 'Transfer Bank',  -- Tunai/Transfer Bank/QRIS
  jadwal_kirim text,
  ekspedisi    text,
  tracking_code text,
  status       text default 'dp_pending',     -- dp_pending/dp_paid/dikirim/completed/dibatalkan
  created_at   timestamptz default now()
);

-- TRANSAKSI (laporan penjualan & pembelian + keuangan admin)
create table if not exists transaksi (
  id                bigint generated always as identity primary key,
  booking_id        bigint references bookings(id) on delete set null,
  product_id        bigint references products(id) on delete set null,
  seller_id         bigint references users(id),
  buyer_id          bigint references users(id),
  harga_total       numeric(14,2) not null,
  dp                numeric(14,2) default 0,
  potongan_platform numeric(14,2) default 0,  -- biaya penanganan admin
  metode_bayar      text,
  ref_payment       text,                      -- referensi payment gateway
  bukti_transfer    text,                      -- folder privat Cloudinary
  catatan_pelunasan text,
  tracking_code     text,
  ekspedisi         text,
  status            text default 'dp_pending', -- dp_pending/dp_paid/menunggu_approval/lunas/dikirim/completed/dibatalkan
  created_at        timestamptz default now()
);
create index if not exists idx_tx_seller on transaksi(seller_id);
create index if not exists idx_tx_buyer  on transaksi(buyer_id);

-- EVIDEN (verifikasi & ketelusuran: foto + GPS tiap tahap)
create table if not exists eviden (
  id             bigint generated always as identity primary key,
  transaction_id bigint references transaksi(id) on delete cascade,
  uploader_id    bigint references users(id),
  tahap          text not null,                -- panen/sortasi/pengemasan/pengiriman/penerimaan
  keterangan     text,
  foto           text,                         -- URL Cloudinary
  lat            double precision,
  lng            double precision,
  created_at     timestamptz default now()
);

-- RATINGS (penilaian kepuasan dua arah)
create table if not exists ratings (
  id             bigint generated always as identity primary key,
  transaction_id bigint references transaksi(id) on delete cascade,
  from_user      bigint references users(id),
  to_user        bigint references users(id),
  skor           int check (skor between 1 and 5),
  ulasan         text,
  aspek          jsonb default '{}'::jsonb,
  created_at     timestamptz default now()
);

-- FAVORITES (penjual/produk favorit pembeli)
create table if not exists favorites (
  id          bigint generated always as identity primary key,
  buyer_id    bigint references users(id) on delete cascade,
  target_type text check (target_type in ('produk','penjual')),
  target_id   bigint not null,
  created_at  timestamptz default now(),
  unique (buyer_id, target_type, target_id)
);

-- PENGATURAN (toggle fitur, persen DP, biaya, footer, API keys)
create table if not exists pengaturan (
  key   text primary key,
  value text
);
insert into pengaturan(key,value) values
  ('persen_dp','20'), ('biaya_penanganan','2.5'), ('biaya_tambahan_flat','0'),
  ('fitur_chat_ai','1'), ('fitur_crypto','0'), ('fitur_storage_cloud','1')
on conflict (key) do nothing;

-- =====================================================================
-- SCHEMA MIGRATIONS (dipakai idempotency guard GitHub Actions)
-- Tabel internal CI: TIDAK boleh diakses publik -> RLS + revoke grant.
-- =====================================================================
create table if not exists schema_migrations (
  version    text primary key,            -- mis. '001_init' / hash commit
  name       text,
  applied_at timestamptz default now()
);

-- =====================================================================
-- ROW LEVEL SECURITY — kunci akses browser HANYA lewat anon key,
-- semua operasi sah dimediasi api.php (tabel sessions).
-- Karena gateway memakai service-role key di server, RLS di bawah ini
-- memblokir akses langsung dari klien terhadap data sensitif.
-- =====================================================================
alter table users        enable row level security;
alter table sessions     enable row level security;
alter table product_master enable row level security;
alter table products     enable row level security;
alter table offers       enable row level security;
alter table bookings     enable row level security;
alter table transaksi    enable row level security;
alter table eviden       enable row level security;
alter table ratings      enable row level security;
alter table favorites    enable row level security;
alter table pengaturan   enable row level security;
alter table product_conversations enable row level security;
alter table product_chat_messages enable row level security;

-- Publik boleh membaca listing produk & master produk (untuk autocomplete)
create policy "products_public_read"  on products      for select using (status = 'aktif');
create policy "master_public_read"    on product_master for select using (true);
create policy "users_public_profile"  on users         for select using (role in ('penjual','pembeli'));

-- Tanpa policy tulis untuk anon => INSERT/UPDATE/DELETE dari browser ditolak;
-- hanya gateway PHP (service_role) yang boleh menulis.

-- schema_migrations: tabel internal CI. RLS TANPA policy = nol baris
-- terlihat/dapat ditulis oleh anon & authenticated (hanya service_role
-- yang menembus RLS). Revoke grant menambah lapisan pengaman.
alter table schema_migrations enable row level security;
revoke all on schema_migrations from anon, authenticated;
revoke all on product_conversations, product_chat_messages from public, anon, authenticated;

-- Direktori koperasi, roster anggota resmi, dan tautan akun marketplace.
CREATE TABLE IF NOT EXISTS public.koperasi (
  id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  kode VARCHAR(40) NOT NULL UNIQUE,
  nama VARCHAR(160) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'aktif',
  external_id VARCHAR(100) UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.koperasi_anggota (
  id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  koperasi_id BIGINT NOT NULL REFERENCES public.koperasi(id) ON DELETE CASCADE,
  external_id VARCHAR(100) NOT NULL,
  nomor_anggota VARCHAR(80) NOT NULL,
  nama VARCHAR(160) NOT NULL,
  email VARCHAR(160),
  status VARCHAR(20) NOT NULL DEFAULT 'aktif',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_roster_koperasi_nomor UNIQUE (koperasi_id, nomor_anggota)
);
CREATE INDEX IF NOT EXISTS idx_koperasi_anggota_external_id
  ON public.koperasi_anggota(koperasi_id, external_id);

CREATE TABLE IF NOT EXISTS public.keanggotaan_koperasi (
  id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  koperasi_id BIGINT NOT NULL REFERENCES public.koperasi(id) ON DELETE CASCADE,
  nomor_anggota VARCHAR(80) NOT NULL,
  nama_terdaftar VARCHAR(160) NOT NULL DEFAULT '',
  status VARCHAR(20) NOT NULL DEFAULT 'menunggu',
  catatan VARCHAR(500),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  diverifikasi_pada TIMESTAMPTZ,
  CONSTRAINT uq_koperasi_nomor_anggota UNIQUE (koperasi_id, nomor_anggota)
);
CREATE INDEX IF NOT EXISTS idx_keanggotaan_koperasi_user
  ON public.keanggotaan_koperasi(user_id);
CREATE INDEX IF NOT EXISTS idx_keanggotaan_koperasi_status
  ON public.keanggotaan_koperasi(status);

ALTER TABLE public.koperasi ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.koperasi_anggota ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.keanggotaan_koperasi ENABLE ROW LEVEL SECURITY;

-- Referensi foto profil kartu anggota disimpan di object storage/CDN.
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(500);

INSERT INTO public.schema_migrations(version)
VALUES ('0009_cooperative_membership'), ('0010_cooperative_member_avatar')
ON CONFLICT (version) DO NOTHING;

-- Seller payment instructions are stored in the shared settings table.
-- Writes must pass through this function because the PHP gateway uses anon key.
CREATE OR REPLACE FUNCTION public.agr_seller_payment_settings_save(
  p_token text,
  p_settings jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_user_id bigint;
  v_active_role text;
  v_user_role text;
  v_roles jsonb;
  v_methods jsonb;
  v_settings jsonb;
BEGIN
  SELECT u.id, COALESCE(s.active_role, u.role), u.role, u.roles
    INTO v_user_id, v_active_role, v_user_role, v_roles
  FROM public.sessions s
  JOIN public.users u ON u.id = s.user_id
  WHERE s.token = p_token AND s.expires_at > now();

  IF v_user_id IS NULL
     OR v_active_role IS DISTINCT FROM 'penjual'
     OR (v_user_role <> 'penjual' AND NOT (COALESCE(v_roles, '[]'::jsonb) ? 'penjual')) THEN
    RAISE EXCEPTION 'Login dengan mode penjual diperlukan' USING ERRCODE = '42501';
  END IF;

  IF jsonb_typeof(COALESCE(p_settings->'metode_dp', '[]'::jsonb)) <> 'array'
     OR length(COALESCE(p_settings->>'rekening', '')) > 160
     OR length(COALESCE(p_settings->>'qris', '')) > 500
     OR length(COALESCE(p_settings->>'tujuan_tunai', '')) > 300 THEN
    RAISE EXCEPTION 'Data pembayaran tidak valid' USING ERRCODE = '22023';
  END IF;

  SELECT COALESCE(jsonb_agg(method), '["Transfer Bank"]'::jsonb)
    INTO v_methods
  FROM (
    SELECT DISTINCT item.method
    FROM jsonb_array_elements_text(COALESCE(p_settings->'metode_dp', '[]'::jsonb)) AS item(method)
    WHERE item.method IN ('Transfer Bank', 'QRIS', 'Tunai')
  ) allowed_methods;

  v_settings := jsonb_build_object(
    'metode_dp', v_methods,
    'rekening', trim(COALESCE(p_settings->>'rekening', '')),
    'qris', trim(COALESCE(p_settings->>'qris', '')),
    'tujuan_tunai', trim(COALESCE(p_settings->>'tujuan_tunai', ''))
  );

  INSERT INTO public.pengaturan(key, value)
    VALUES ('pembayaran_penjual_' || v_user_id::text, v_settings::text)
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

  RETURN v_settings;
END;
$$;

REVOKE ALL ON FUNCTION public.agr_seller_payment_settings_save(text, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.agr_seller_payment_settings_save(text, jsonb) TO anon, authenticated;

select 'AGR.BIZ.ID skema supabase siap' as status;

-- User business logo migration.
-- Store the seller's business logo as a public object-storage reference.
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS logo_url VARCHAR(500);

INSERT INTO public.schema_migrations(version)
VALUES ('0011_user_business_logo')
ON CONFLICT (version) DO NOTHING;


-- Seller auction event, package, participant, bid, and winner schema.
-- Auction schema aligned with the Flask models and seller/admin workflows.
-- Packages may be custom criteria, so lelang_items is optional for each event.
CREATE TABLE IF NOT EXISTS public.lelang_events (
  id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  seller_id BIGINT NOT NULL REFERENCES public.users(id),
  judul VARCHAR(160) NOT NULL,
  deskripsi TEXT NOT NULL,
  kriteria_paket TEXT NOT NULL DEFAULT '',
  paket_kustom BOOLEAN NOT NULL DEFAULT FALSE,
  syarat_ketentuan TEXT NOT NULL DEFAULT '',
  foto VARCHAR(500) NOT NULL,
  alamat_lokasi VARCHAR(255) NOT NULL,
  lat DOUBLE PRECISION NOT NULL,
  lng DOUBLE PRECISION NOT NULL,
  mulai TIMESTAMP WITHOUT TIME ZONE NOT NULL,
  selesai TIMESTAMP WITHOUT TIME ZONE NOT NULL,
  batas_bayar_pemenang TIMESTAMP WITHOUT TIME ZONE,
  jadwal_pengambilan TIMESTAMP WITHOUT TIME ZONE,
  harga_awal DOUBLE PRECISION NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'diajukan',
  catatan_admin TEXT,
  biaya_peserta DOUBLE PRECISION NOT NULL DEFAULT 0,
  biaya_penjual DOUBLE PRECISION NOT NULL DEFAULT 0,
  biaya_penjual_lunas BOOLEAN NOT NULL DEFAULT FALSE,
  ref_biaya_penjual VARCHAR(80),
  disetujui_pada TIMESTAMP WITHOUT TIME ZONE,
  pemenang_id BIGINT REFERENCES public.users(id),
  harga_pemenang DOUBLE PRECISION,
  pemenang_bayar_lunas BOOLEAN NOT NULL DEFAULT FALSE,
  ref_bayar_pemenang VARCHAR(80),
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.lelang_items (
  id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  event_id BIGINT NOT NULL REFERENCES public.lelang_events(id) ON DELETE CASCADE,
  product_id BIGINT REFERENCES public.products(id) ON DELETE SET NULL,
  nama_produk VARCHAR(120) NOT NULL,
  kategori VARCHAR(40) NOT NULL,
  subkategori VARCHAR(60),
  jumlah DOUBLE PRECISION NOT NULL,
  satuan VARCHAR(20) NOT NULL,
  harga_listing DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS public.lelang_participants (
  id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  event_id BIGINT NOT NULL REFERENCES public.lelang_events(id) ON DELETE CASCADE,
  buyer_id BIGINT NOT NULL REFERENCES public.users(id),
  biaya_administrasi DOUBLE PRECISION NOT NULL DEFAULT 0,
  biaya_lunas BOOLEAN NOT NULL DEFAULT FALSE,
  ref_pembayaran VARCHAR(80),
  dibayar_pada TIMESTAMP WITHOUT TIME ZONE,
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_lelang_participant UNIQUE (event_id, buyer_id)
);

CREATE TABLE IF NOT EXISTS public.lelang_bids (
  id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  event_id BIGINT NOT NULL REFERENCES public.lelang_events(id) ON DELETE CASCADE,
  buyer_id BIGINT NOT NULL REFERENCES public.users(id),
  nominal DOUBLE PRECISION NOT NULL,
  catatan VARCHAR(255),
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.lelang_awards (
  id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  event_id BIGINT NOT NULL REFERENCES public.lelang_events(id) ON DELETE CASCADE,
  buyer_id BIGINT NOT NULL REFERENCES public.users(id),
  nominal DOUBLE PRECISION NOT NULL,
  batas_bayar TIMESTAMP WITHOUT TIME ZONE NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'menunggu',
  ref_pembayaran VARCHAR(80),
  ditetapkan_pada TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
  dibayar_pada TIMESTAMP WITHOUT TIME ZONE
);

CREATE INDEX IF NOT EXISTS ix_lelang_events_seller_id ON public.lelang_events(seller_id);
CREATE INDEX IF NOT EXISTS ix_lelang_items_event_id ON public.lelang_items(event_id);
CREATE INDEX IF NOT EXISTS ix_lelang_participants_event_id ON public.lelang_participants(event_id);
CREATE INDEX IF NOT EXISTS ix_lelang_participants_buyer_id ON public.lelang_participants(buyer_id);
CREATE INDEX IF NOT EXISTS ix_lelang_bids_event_id ON public.lelang_bids(event_id);
CREATE INDEX IF NOT EXISTS ix_lelang_bids_buyer_id ON public.lelang_bids(buyer_id);
CREATE INDEX IF NOT EXISTS ix_lelang_awards_event_id ON public.lelang_awards(event_id);
CREATE INDEX IF NOT EXISTS ix_lelang_awards_buyer_id ON public.lelang_awards(buyer_id);

ALTER TABLE public.lelang_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.lelang_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.lelang_participants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.lelang_bids ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.lelang_awards ENABLE ROW LEVEL SECURITY;

INSERT INTO public.schema_migrations(version)
VALUES ('0012_auction_schema')
ON CONFLICT (version) DO NOTHING;
