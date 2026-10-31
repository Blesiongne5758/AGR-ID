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


-- InfinityFree-compatible marketplace path. All privileged writes are exposed
-- only as token-scoped RPCs; PHP never needs a Supabase service-role key.
ALTER TABLE public.products
  ADD COLUMN IF NOT EXISTS kuota_minimum integer NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS kuota_maksimum integer;
ALTER TABLE public.bookings
  ADD COLUMN IF NOT EXISTS product_id bigint REFERENCES public.products(id) ON DELETE SET NULL;
ALTER TABLE public.products ALTER COLUMN kuota_minimum SET DEFAULT 1;

INSERT INTO public.pengaturan(key,value) VALUES
  ('fitur_pembayaran','1'), ('fitur_booking_dp','1'), ('fitur_biaya','1')
ON CONFLICT (key) DO NOTHING;

CREATE OR REPLACE FUNCTION public.agr_role_switch(p_token text,p_role text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE uid bigint; u public.users%ROWTYPE; roles_json jsonb; sess public.sessions%ROWTYPE;
BEGIN
  SELECT * INTO sess FROM public.sessions WHERE token=p_token AND expires_at>now() FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Sesi tidak valid' USING ERRCODE='42501'; END IF;
  SELECT * INTO u FROM public.users WHERE id=sess.user_id FOR UPDATE;
  IF u.role='admin' OR p_role IS NULL OR p_role NOT IN ('pembeli','penjual') THEN RAISE EXCEPTION 'Mode akun tidak dapat diganti' USING ERRCODE='42501'; END IF;
  roles_json:=COALESCE(u.roles,'[]'::jsonb);
  IF p_role='penjual' AND NOT (roles_json ? 'penjual') THEN
    IF COALESCE(btrim(u.nama),'')='' OR lower(btrim(u.nama))=lower(btrim(u.username)) OR COALESCE(btrim(u.no_hp),'')='' OR
       COALESCE(btrim(u.alamat),'')='' OR COALESCE(btrim(u.kota),'')='' OR COALESCE(btrim(u.provinsi),'')='' OR
       u.lat IS NULL OR u.lng IS NULL OR COALESCE(btrim(u.tipe_penjual),'') NOT IN ('Perorangan','Kelompok/Paguyuban','Koperasi','Perusahaan') OR
       (u.tipe_penjual<>'Perorangan' AND (COALESCE(btrim(u.npwp),'')='' OR COALESCE(btrim(u.nib),'')='')) THEN
      RAISE EXCEPTION 'Lengkapi profil, alamat, GPS, tipe penjual dan data usaha sebelum mengaktifkan mode penjual' USING ERRCODE='22023';
    END IF;
    roles_json:=roles_json||jsonb_build_array('penjual');
    UPDATE public.users SET roles=roles_json WHERE id=u.id;
  ELSIF NOT (roles_json ? p_role) THEN
    RAISE EXCEPTION 'Peran ini belum diaktifkan pada akun' USING ERRCODE='42501';
  END IF;
  UPDATE public.sessions SET active_role=p_role WHERE id=sess.id;
  RETURN jsonb_build_object('ok',true,'user',jsonb_build_object('id',u.id,'email',u.email,'username',u.username,'nama',u.nama,
    'role',p_role,'roles',roles_json,'tipe',CASE WHEN p_role='penjual' THEN u.tipe_penjual ELSE u.tipe_pembeli END,
    'tipe_penjual',u.tipe_penjual,'tipe_pembeli',u.tipe_pembeli,'alamat',u.alamat,'lat',u.lat,'lng',u.lng));
END; $$;

CREATE OR REPLACE FUNCTION public.agr_product_create(p_token text,p_payload jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE uid bigint; active text; roles_json jsonb; u public.users%ROWTYPE; p public.products%ROWTYPE;
  nm text; cat text; unit_name text; price numeric; stock integer; qmin integer; qmax integer;
BEGIN
  SELECT u.id,s.active_role,u.roles INTO uid,active,roles_json FROM public.sessions s JOIN public.users u ON u.id=s.user_id
    WHERE s.token=p_token AND s.expires_at>now();
  IF uid IS NULL OR active<>'penjual' OR NOT (COALESCE(roles_json,'[]'::jsonb)?'penjual') THEN RAISE EXCEPTION 'Aktifkan mode penjual untuk memposting' USING ERRCODE='42501'; END IF;
  SELECT * INTO u FROM public.users WHERE id=uid;
  nm:=btrim(COALESCE(p_payload->>'nama_product','')); cat:=btrim(COALESCE(p_payload->>'kategori','')); unit_name:=btrim(COALESCE(p_payload->>'satuan',''));
  price:=NULLIF(p_payload->>'harga','')::numeric; stock:=COALESCE(NULLIF(p_payload->>'stok','')::integer,0);
  qmin:=COALESCE(NULLIF(p_payload->>'kuota_minimum','')::integer,1); qmax:=NULLIF(p_payload->>'kuota_maksimum','')::integer;
  IF nm='' OR cat NOT IN ('Pertanian','Perkebunan','Perikanan','Peternakan') OR unit_name='' OR price IS NULL OR price<=0 THEN RAISE EXCEPTION 'Nama, kategori, harga positif, dan satuan wajib diisi' USING ERRCODE='22023'; END IF;
  IF stock<1 OR qmin<1 OR qmin>stock OR (qmax IS NOT NULL AND (qmax<qmin OR qmax>stock)) THEN RAISE EXCEPTION 'Stok dan kuota minimum/maksimum tidak valid' USING ERRCODE='22023'; END IF;
  INSERT INTO public.product_master(nama,kategori,sub_kategori,jenis,auto_added) VALUES(nm,cat,p_payload->>'sub_kategori',p_payload->>'jenis',true) ON CONFLICT(nama) DO NOTHING;
  INSERT INTO public.products(user_id,nama_product,jenis,kategori,sub_kategori,deskripsi,harga,satuan,stok,foto,lat,lng,alamat_lahan,status,kuota_minimum,kuota_maksimum,created_at)
  VALUES(uid,nm,COALESCE(p_payload->>'jenis',''),cat,COALESCE(p_payload->>'sub_kategori',''),COALESCE(p_payload->>'deskripsi',''),price,unit_name,stock,
    COALESCE(p_payload->>'foto',''),COALESCE(NULLIF(p_payload->>'lat','')::double precision,u.lat),COALESCE(NULLIF(p_payload->>'lng','')::double precision,u.lng),
    COALESCE(NULLIF(p_payload->>'alamat_lahan',''),u.alamat), 'aktif',qmin,qmax,now()) RETURNING * INTO p;
  RETURN to_jsonb(p);
END; $$;

CREATE OR REPLACE FUNCTION public.agr_offer_create(p_token text,p_product_id bigint,p_price numeric,p_quantity numeric,p_note text DEFAULT '')
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE uid bigint; active text; roles_json jsonb; p public.products%ROWTYPE; o public.offers%ROWTYPE;
BEGIN
  SELECT u.id,s.active_role,u.roles INTO uid,active,roles_json FROM public.sessions s JOIN public.users u ON u.id=s.user_id WHERE s.token=p_token AND s.expires_at>now();
  IF uid IS NULL OR active<>'pembeli' OR NOT (COALESCE(roles_json,'[]'::jsonb)?'pembeli') THEN RAISE EXCEPTION 'Login dengan mode pembeli diperlukan' USING ERRCODE='42501'; END IF;
  SELECT * INTO p FROM public.products WHERE id=p_product_id AND status='aktif' FOR UPDATE;
  IF NOT FOUND OR p.user_id=uid THEN RAISE EXCEPTION 'Produk tidak tersedia' USING ERRCODE='P0002'; END IF;
  IF p_price<=0 OR p_quantity<COALESCE(p.kuota_minimum,1) OR p_quantity<>trunc(p_quantity) OR p_quantity>p.stok OR (p.kuota_maksimum IS NOT NULL AND p_quantity>p.kuota_maksimum) THEN
    RAISE EXCEPTION 'Harga/jumlah penawaran tidak valid; jumlah harus memenuhi kuota dan stok' USING ERRCODE='22023';
  END IF;
  INSERT INTO public.offers(product_id,buyer_id,harga_tawar,jumlah,catatan,status,created_at) VALUES(p.id,uid,p_price,p_quantity,left(COALESCE(p_note,''),1000),'menunggu',now()) RETURNING * INTO o;
  RETURN to_jsonb(o);
END; $$;

CREATE OR REPLACE FUNCTION public.agr_order_create(p_token text,p_product_id bigint,p_quantity numeric,p_offer_id bigint DEFAULT 0,
  p_method text DEFAULT '',p_delivery text DEFAULT '',p_carrier text DEFAULT '')
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE uid bigint; active text; roles_json jsonb; p public.products%ROWTYPE; o public.offers%ROWTYPE;
  buyer_id bigint; qty numeric; unit_price numeric; total numeric; dp_amount numeric; fee numeric; dp_pct numeric;
  pay_on boolean; dp_on boolean; fees_on boolean; tx_status text; bk public.bookings%ROWTYPE; tx public.transaksi%ROWTYPE;
BEGIN
  SELECT u.id,s.active_role,u.roles INTO uid,active,roles_json FROM public.sessions s JOIN public.users u ON u.id=s.user_id WHERE s.token=p_token AND s.expires_at>now();
  IF uid IS NULL OR active<>'pembeli' OR NOT (COALESCE(roles_json,'[]'::jsonb)?'pembeli') THEN RAISE EXCEPTION 'Login dengan mode pembeli diperlukan' USING ERRCODE='42501'; END IF;
  SELECT * INTO p FROM public.products WHERE id=p_product_id AND status='aktif' FOR UPDATE;
  IF NOT FOUND OR p.stok<1 THEN RAISE EXCEPTION 'Produk tidak tersedia atau stok habis' USING ERRCODE='P0002'; END IF;
  qty:=p_quantity;
  IF COALESCE(p_offer_id,0)>0 THEN
    SELECT * INTO o FROM public.offers WHERE id=p_offer_id FOR UPDATE;
    IF NOT FOUND OR o.product_id<>p.id OR o.buyer_id<>uid OR o.status<>'diterima' THEN RAISE EXCEPTION 'Penawaran tidak tersedia untuk checkout' USING ERRCODE='42501'; END IF;
    IF EXISTS(SELECT 1 FROM public.bookings WHERE offer_id=o.id) THEN RAISE EXCEPTION 'Penawaran sudah dipesan' USING ERRCODE='23505'; END IF;
    qty:=o.jumlah; unit_price:=o.harga_tawar;
  ELSE
    unit_price:=p.harga;
  END IF;
  IF qty<COALESCE(p.kuota_minimum,1) OR qty<>trunc(qty) OR qty>p.stok OR (p.kuota_maksimum IS NOT NULL AND qty>p.kuota_maksimum) THEN
    RAISE EXCEPTION 'Jumlah pesanan harus memenuhi kuota listing dan tidak melebihi stok' USING ERRCODE='22023';
  END IF;
  total:=round(unit_price*qty,2);
  SELECT COALESCE((SELECT value FROM public.pengaturan WHERE key='fitur_pembayaran'),'1')<>'0',
         COALESCE((SELECT value FROM public.pengaturan WHERE key='fitur_booking_dp'),'1')<>'0',
         COALESCE((SELECT value FROM public.pengaturan WHERE key='fitur_biaya'),'1')<>'0'
    INTO pay_on,dp_on,fees_on;
  dp_pct:=COALESCE(NULLIF((SELECT value FROM public.pengaturan WHERE key='persen_dp'),'')::numeric,20);
  IF NOT pay_on THEN dp_on:=false; END IF;
  IF pay_on AND COALESCE(p_method,'') NOT IN ('Transfer Bank','QRIS','Tunai') THEN RAISE EXCEPTION 'Pilih metode pembayaran yang tersedia' USING ERRCODE='22023'; END IF;
  dp_amount:=CASE WHEN pay_on AND dp_on THEN round(total*greatest(0,least(dp_pct,100))/100,2) ELSE 0 END;
  fee:=CASE WHEN pay_on AND fees_on THEN round(total*COALESCE(NULLIF((SELECT value FROM public.pengaturan WHERE key='biaya_penanganan'),'')::numeric,0)/100
      +COALESCE(NULLIF((SELECT value FROM public.pengaturan WHERE key='biaya_tambahan_flat'),'')::numeric,0),2) ELSE 0 END;
  tx_status:=CASE WHEN NOT pay_on THEN 'dipesan' WHEN dp_amount>0 THEN 'dp_pending' ELSE 'menunggu_pembayaran' END;
  INSERT INTO public.bookings(offer_id,product_id,buyer_id,total,dp,sisa,metode_dp,jadwal_kirim,ekspedisi,status,created_at)
    VALUES(NULLIF(p_offer_id,0),p.id,uid,total,dp_amount,total-dp_amount,CASE WHEN pay_on THEN p_method ELSE '' END,
      left(COALESCE(p_delivery,''),80),left(COALESCE(p_carrier,''),100),tx_status,now()) RETURNING * INTO bk;
  INSERT INTO public.transaksi(booking_id,product_id,seller_id,buyer_id,harga_total,dp,potongan_platform,metode_bayar,status,created_at)
    VALUES(bk.id,p.id,p.user_id,uid,total,dp_amount,fee,CASE WHEN pay_on THEN p_method ELSE '' END,tx_status,now()) RETURNING * INTO tx;
  UPDATE public.products SET stok=stok-qty::integer,updated_at=now() WHERE id=p.id;
  IF COALESCE(p_offer_id,0)>0 THEN UPDATE public.offers SET status='dibooking' WHERE id=o.id; END IF;
  RETURN jsonb_build_object('booking',to_jsonb(bk),'transaksi',to_jsonb(tx),'payment_enabled',pay_on,'dp_enabled',dp_on,
    'fees_enabled',pay_on AND fees_on,'persen_dp',CASE WHEN dp_on THEN dp_pct ELSE 0 END,'quantity',qty,'product_id',p.id,'seller_id',p.user_id);
END; $$;

CREATE OR REPLACE FUNCTION public.agr_favorite_toggle(p_token text,p_target_type text,p_target_id bigint)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE uid bigint; active text; roles_json jsonb; found_id bigint;
BEGIN
  SELECT u.id,s.active_role,u.roles INTO uid,active,roles_json FROM public.sessions s JOIN public.users u ON u.id=s.user_id WHERE s.token=p_token AND s.expires_at>now();
  IF uid IS NULL OR active<>'pembeli' OR NOT (COALESCE(roles_json,'[]'::jsonb)?'pembeli') THEN RAISE EXCEPTION 'Login dengan mode pembeli diperlukan' USING ERRCODE='42501'; END IF;
  IF p_target_type NOT IN ('produk','penjual') OR p_target_id IS NULL THEN RAISE EXCEPTION 'Target favorit tidak valid' USING ERRCODE='22023'; END IF;
  IF p_target_type='produk' AND NOT EXISTS(SELECT 1 FROM public.products WHERE id=p_target_id AND status='aktif') THEN RAISE EXCEPTION 'Produk tidak ditemukan' USING ERRCODE='P0002'; END IF;
  IF p_target_type='penjual' AND NOT EXISTS(SELECT 1 FROM public.users WHERE id=p_target_id AND roles ? 'penjual') THEN RAISE EXCEPTION 'Penjual tidak ditemukan' USING ERRCODE='P0002'; END IF;
  SELECT id INTO found_id FROM public.favorites WHERE buyer_id=uid AND target_type=p_target_type AND target_id=p_target_id;
  IF found_id IS NOT NULL THEN DELETE FROM public.favorites WHERE id=found_id; RETURN jsonb_build_object('favorit',false); END IF;
  INSERT INTO public.favorites(buyer_id,target_type,target_id,created_at) VALUES(uid,p_target_type,p_target_id,now());
  RETURN jsonb_build_object('favorit',true);
END; $$;

CREATE OR REPLACE FUNCTION public.agr_admin_settings_save(p_token text,p_settings jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE uid bigint; active text; k text; v text;
BEGIN
  SELECT u.id,s.active_role INTO uid,active FROM public.sessions s JOIN public.users u ON u.id=s.user_id WHERE s.token=p_token AND s.expires_at>now();
  IF uid IS NULL OR active<>'admin' THEN RAISE EXCEPTION 'Akses admin diperlukan' USING ERRCODE='42501'; END IF;
  IF jsonb_typeof(p_settings)<>'object' OR p_settings IS NULL THEN RAISE EXCEPTION 'Pengaturan tidak valid' USING ERRCODE='22023'; END IF;
  FOR k,v IN SELECT key,value FROM jsonb_each_text(p_settings) LOOP
    IF k NOT IN ('fitur_pembayaran','fitur_booking_dp','fitur_biaya','persen_dp','biaya_penanganan','biaya_tambahan_flat','biaya_verifikasi','fitur_marketplace','fitur_favorit','fitur_chat_ai','fitur_crypto','fitur_storage_cloud','fitur_eviden_gps','fitur_rating','fitur_payment_gateway','beranda_aktif','footer_tagline','footer_email','footer_wa','footer_alamat','footer_copy') THEN
      RAISE EXCEPTION 'Kunci pengaturan tidak diizinkan: %',k USING ERRCODE='22023';
    END IF;
    IF k IN ('fitur_pembayaran','fitur_booking_dp','fitur_biaya') AND v NOT IN ('0','1') THEN RAISE EXCEPTION 'Nilai toggle harus 0 atau 1' USING ERRCODE='22023'; END IF;
    IF k='persen_dp' AND (v::numeric<0 OR v::numeric>100) THEN RAISE EXCEPTION 'Persentase DP harus 0 sampai 100' USING ERRCODE='22023'; END IF;
    IF k='biaya_penanganan' AND (v::numeric<0 OR v::numeric>100) THEN RAISE EXCEPTION 'Biaya penanganan harus 0 sampai 100' USING ERRCODE='22023'; END IF;
    IF k='biaya_tambahan_flat' AND (v::numeric<0 OR v::numeric>100000000) THEN RAISE EXCEPTION 'Biaya tambahan flat tidak valid' USING ERRCODE='22023'; END IF;
    INSERT INTO public.pengaturan(key,value) VALUES(k,v) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value;
  END LOOP;
  RETURN jsonb_build_object('ok',true);
END; $$;

CREATE OR REPLACE FUNCTION public.agr_profile_update(p_token text,p_payload jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE uid bigint; u public.users%ROWTYPE; lat_value double precision; lng_value double precision; tipe text;
BEGIN
  SELECT user_id INTO uid FROM public.sessions WHERE token=p_token AND expires_at>now();
  IF uid IS NULL THEN RAISE EXCEPTION 'Sesi tidak valid' USING ERRCODE='42501'; END IF;
  lat_value:=NULLIF(p_payload->>'lat','')::double precision; lng_value:=NULLIF(p_payload->>'lng','')::double precision;
  IF (lat_value IS NOT NULL AND lat_value NOT BETWEEN -90 AND 90) OR (lng_value IS NOT NULL AND lng_value NOT BETWEEN -180 AND 180) THEN
    RAISE EXCEPTION 'Koordinat GPS tidak valid' USING ERRCODE='22023';
  END IF;
  tipe:=NULLIF(btrim(p_payload->>'tipe_penjual'),'');
  IF tipe IS NOT NULL AND tipe NOT IN ('Perorangan','Kelompok/Paguyuban','Koperasi','Perusahaan') THEN RAISE EXCEPTION 'Tipe penjual tidak valid' USING ERRCODE='22023'; END IF;
  UPDATE public.users SET nama=COALESCE(btrim(p_payload->>'nama'),nama),no_hp=COALESCE(btrim(p_payload->>'no_hp'),''),
    alamat=COALESCE(btrim(p_payload->>'alamat'),''),kota=COALESCE(btrim(p_payload->>'kota'),''),provinsi=COALESCE(btrim(p_payload->>'provinsi'),''),
    tipe_penjual=tipe,npwp=COALESCE(btrim(p_payload->>'npwp'),''),nib=COALESCE(btrim(p_payload->>'nib'),''),lat=lat_value,lng=lng_value
    WHERE id=uid RETURNING * INTO u;
  RETURN jsonb_build_object('ok',true,'user',jsonb_build_object('id',u.id,'email',u.email,'username',u.username,'nama',u.nama,'role',
    (SELECT active_role FROM public.sessions WHERE token=p_token),'roles',u.roles,'tipe',u.tipe,'tipe_penjual',u.tipe_penjual,
    'tipe_pembeli',u.tipe_pembeli,'alamat',u.alamat,'kota',u.kota,'provinsi',u.provinsi,'no_hp',u.no_hp,'npwp',u.npwp,'nib',u.nib,'lat',u.lat,'lng',u.lng));
END; $$;

CREATE OR REPLACE FUNCTION public.agr_offer_respond(p_token text,p_offer_id bigint,p_decision text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE uid bigint; active text; o public.offers%ROWTYPE; p public.products%ROWTYPE;
BEGIN
  SELECT u.id,s.active_role INTO uid,active FROM public.sessions s JOIN public.users u ON u.id=s.user_id WHERE s.token=p_token AND s.expires_at>now();
  IF uid IS NULL OR active<>'penjual' THEN RAISE EXCEPTION 'Mode penjual diperlukan' USING ERRCODE='42501'; END IF;
  SELECT * INTO o FROM public.offers WHERE id=p_offer_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Penawaran tidak ditemukan' USING ERRCODE='P0002'; END IF;
  SELECT * INTO p FROM public.products WHERE id=o.product_id;
  IF p.user_id<>uid THEN RAISE EXCEPTION 'Penawaran bukan milik listing Anda' USING ERRCODE='42501'; END IF;
  IF o.status<>'menunggu' OR p_decision NOT IN ('terima','tolak') THEN RAISE EXCEPTION 'Penawaran sudah diproses atau keputusan tidak valid' USING ERRCODE='22023'; END IF;
  UPDATE public.offers SET status=CASE WHEN p_decision='terima' THEN 'diterima' ELSE 'ditolak' END,responded_at=now() WHERE id=o.id RETURNING * INTO o;
  RETURN to_jsonb(o);
END; $$;

CREATE OR REPLACE FUNCTION public.agr_offers_list(p_token text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE uid bigint; active text; result jsonb;
BEGIN
  SELECT u.id,s.active_role INTO uid,active FROM public.sessions s JOIN public.users u ON u.id=s.user_id WHERE s.token=p_token AND s.expires_at>now();
  IF uid IS NULL OR active NOT IN ('pembeli','penjual') THEN RAISE EXCEPTION 'Login diperlukan' USING ERRCODE='42501'; END IF;
  SELECT COALESCE(jsonb_agg(to_jsonb(o) ORDER BY o.created_at DESC),'[]'::jsonb) INTO result FROM public.offers o
    WHERE (active='pembeli' AND o.buyer_id=uid) OR (active='penjual' AND EXISTS(SELECT 1 FROM public.products p WHERE p.id=o.product_id AND p.user_id=uid));
  RETURN result;
END; $$;

CREATE OR REPLACE FUNCTION public.agr_transactions_list(p_token text,p_side text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE uid bigint; active text; result jsonb;
BEGIN
  SELECT u.id,s.active_role INTO uid,active FROM public.sessions s JOIN public.users u ON u.id=s.user_id WHERE s.token=p_token AND s.expires_at>now();
  IF uid IS NULL OR active NOT IN ('pembeli','penjual','admin') OR p_side NOT IN ('pembelian','penjualan') THEN RAISE EXCEPTION 'Login diperlukan' USING ERRCODE='42501'; END IF;
  SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY t.created_at DESC),'[]'::jsonb) INTO result FROM public.transaksi t
    WHERE (active='admin') OR (p_side='pembelian' AND t.buyer_id=uid) OR (p_side='penjualan' AND t.seller_id=uid);
  RETURN result;
END; $$;

CREATE OR REPLACE FUNCTION public.agr_favorites_list(p_token text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE uid bigint; active text; result jsonb;
BEGIN
  SELECT u.id,s.active_role INTO uid,active FROM public.sessions s JOIN public.users u ON u.id=s.user_id WHERE s.token=p_token AND s.expires_at>now();
  IF uid IS NULL OR active<>'pembeli' THEN RAISE EXCEPTION 'Mode pembeli diperlukan' USING ERRCODE='42501'; END IF;
  SELECT COALESCE(jsonb_agg(to_jsonb(f) ORDER BY f.created_at DESC),'[]'::jsonb) INTO result FROM public.favorites f WHERE f.buyer_id=uid;
  RETURN result;
END; $$;

CREATE OR REPLACE FUNCTION public.agr_payment_submit(p_token text,p_transaction_id bigint,p_proof text,p_note text,p_reference text DEFAULT '')
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE uid bigint; active text; tx public.transaksi%ROWTYPE; next_status text;
BEGIN
  SELECT u.id,s.active_role INTO uid,active FROM public.sessions s JOIN public.users u ON u.id=s.user_id WHERE s.token=p_token AND s.expires_at>now();
  IF uid IS NULL OR active<>'pembeli' THEN RAISE EXCEPTION 'Mode pembeli diperlukan' USING ERRCODE='42501'; END IF;
  SELECT * INTO tx FROM public.transaksi WHERE id=p_transaction_id AND buyer_id=uid FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Transaksi tidak ditemukan' USING ERRCODE='P0002'; END IF;
  IF tx.status='dp_pending' THEN
    UPDATE public.transaksi SET status='dp_paid',ref_payment=left(COALESCE(p_reference,''),80),bukti_transfer=left(COALESCE(p_proof,''),500) WHERE id=tx.id RETURNING * INTO tx;
    UPDATE public.bookings SET status='dp_paid' WHERE id=tx.booking_id; next_status:='dp_paid';
  ELSIF tx.status IN ('dp_paid','lunas_dp','menunggu_approval','menunggu_pembayaran') THEN
    UPDATE public.transaksi SET status='menunggu_approval',bukti_transfer=left(COALESCE(p_proof,''),500),catatan_pelunasan=left(COALESCE(p_note,''),1000) WHERE id=tx.id RETURNING * INTO tx;
    UPDATE public.bookings SET status='menunggu_approval' WHERE id=tx.booking_id; next_status:='menunggu_approval';
  ELSE RAISE EXCEPTION 'Status transaksi tidak menerima konfirmasi pembayaran' USING ERRCODE='22023'; END IF;
  RETURN jsonb_build_object('ok',true,'status',next_status);
END; $$;

CREATE OR REPLACE FUNCTION public.agr_payment_approve(p_token text,p_transaction_id bigint,p_approve boolean)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE uid bigint; active text; tx public.transaksi%ROWTYPE; next_status text;
BEGIN
  SELECT u.id,s.active_role INTO uid,active FROM public.sessions s JOIN public.users u ON u.id=s.user_id WHERE s.token=p_token AND s.expires_at>now();
  IF uid IS NULL OR active<>'penjual' THEN RAISE EXCEPTION 'Mode penjual diperlukan' USING ERRCODE='42501'; END IF;
  SELECT * INTO tx FROM public.transaksi WHERE id=p_transaction_id AND seller_id=uid FOR UPDATE;
  IF NOT FOUND OR tx.status<>'menunggu_approval' THEN RAISE EXCEPTION 'Transaksi tidak menunggu persetujuan Anda' USING ERRCODE='P0002'; END IF;
  next_status:=CASE WHEN p_approve THEN 'lunas' ELSE CASE WHEN tx.dp>0 THEN 'dp_paid' ELSE 'menunggu_pembayaran' END END;
  UPDATE public.transaksi SET status=next_status WHERE id=tx.id;
  UPDATE public.bookings SET status=next_status WHERE id=tx.booking_id;
  RETURN jsonb_build_object('ok',true,'status',next_status);
END; $$;

REVOKE ALL ON FUNCTION public.agr_role_switch(text,text),public.agr_product_create(text,jsonb),
  public.agr_offer_create(text,bigint,numeric,numeric,text),public.agr_order_create(text,bigint,numeric,bigint,text,text,text),
  public.agr_favorite_toggle(text,text,bigint),public.agr_admin_settings_save(text,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.agr_role_switch(text,text),public.agr_product_create(text,jsonb),
  public.agr_offer_create(text,bigint,numeric,numeric,text),public.agr_order_create(text,bigint,numeric,bigint,text,text,text),
  public.agr_favorite_toggle(text,text,bigint),public.agr_admin_settings_save(text,jsonb) TO anon,authenticated;
REVOKE ALL ON FUNCTION public.agr_profile_update(text,jsonb),public.agr_offer_respond(text,bigint,text),public.agr_offers_list(text),
  public.agr_transactions_list(text,text),public.agr_favorites_list(text),public.agr_payment_submit(text,bigint,text,text,text),public.agr_payment_approve(text,bigint,boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.agr_profile_update(text,jsonb),public.agr_offer_respond(text,bigint,text),public.agr_offers_list(text),
  public.agr_transactions_list(text,text),public.agr_favorites_list(text),public.agr_payment_submit(text,bigint,text,text,text),public.agr_payment_approve(text,bigint,boolean) TO anon,authenticated;
