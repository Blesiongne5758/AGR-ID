# 🚀 Deploy AGR.BIZ.ID ke InfinityFree + Supabase + Cloudinary

## Langkah 1 — Buat project Supabase & jalankan skema
1. Buka https://supabase.com → **New project** (region Singapore, set password DB).
2. Tunggu provisioning, lalu **SQL Editor → New query**:
   - Tempel seluruh isi `supabase-schema.sql` → **Run** (membuat 12 tabel + RLS).
   - Tempel seluruh isi `seed-supabase.sql` → **Run** (produk master, kategori, harga pasar, pengaturan, akun demo).
3. Ambil kredensial di **Project Settings → API**:
   - **Project URL** → `https://<REF>.supabase.co` (atau cukup `<REF>`-nya saja)
   - **Publishable key** (`sb_publishable_...`) atau **Legacy API Keys → anon public** (`eyJ...`).
   
   > `sb_publishable_` adalah kunci publik dan dapat dipakai gateway. Jangan gunakan `sb_secret_` atau `service_role` pada hosting publik. Project Anda juga harus dibuat terlebih dahulu; tanpa Project URL/REF, sistem tidak tahu ke mana request dikirim.
   >
   > 🔒 `sb_secret_` = service key super-privileged. Jangan pernah ditaruh di htdocs/hosting publik; gunakan hanya di backend privat (Flask/Render).

## Langkah 2 — Konfigurasi file config
Di folder `htdocs/`, salin `config.example.php` menjadi `config.php` lalu isi:
```php
'supabase_url'   => 'https://<REF>.supabase.co',  // atau '<REF>' saja
'supabase_key'   => 'sb_publishable_... atau eyJ... legacy anon',
'cloudinary_cloud'  => 'dxxxxxxx',                // dashboard.cloudinary.com -> Upload Settings/Pages? Keys
'cloudinary_key'    => '123456789012345',
'cloudinary_secret' => 'xxxxxxxxxxxxxxxx',
'flask_url'     => '',                             // opsional: backend Flask utk PG/blockchain/chat
```

## Langkah 3 — Deploy via GitHub Actions (otomatis)
Push branch `main` → workflow `.github/workflows/deploy.yml` menyinkronkan
`htdocs/` ke FTP InfinityFree (`/htdocs/`). Secrets yang dibutuhkan:
`FTP_SERVER`, `FTP_USERNAME`, `FTP_PASSWORD` (dari area client InfinityFree →
FTP Accounts). File `config.php` **dikecualikan** dari sync demi keamanan —
upload sekali secara manual (Langkah 4).

## Langkah 4 — Upload config.php manual
InfinityFree → **Control Panel → Online File Manager** (atau FileZilla):
masuk folder `htdocs/` → upload `config.php` hasil Langkah 2.
Setelah itu buka `https://domain-anda.rf.gd/api.php?action=health` —
harus muncul `{"ok":true,...}`.

## Langkah 5 — Uji aplikasi
Buka domain Anda → Daftar/Login (demo: `penjual@agr.id / penjual123`,
`pembeli@agr.id / pembeli123`, `admin@agr.id / admin123`), posting produk,
buat penawaran → booking DP → bayar. Foto produk ter-upload langsung ke
Cloudinary (bucket publik), dokumen KYC ke folder privat dengan pre-signed URL.

## Jalur alternatif InfinityFree (tanpa menjalankan Flask)

Jalur ini mempertahankan aplikasi Flask dan semua fiturnya untuk server utama,
sementara portal statis `htdocs/` menggunakan PHP gateway (`api.php`) ke Supabase
REST dan upload bertanda tangan langsung dari browser ke Cloudinary. InfinityFree
tidak perlu koneksi PostgreSQL langsung, Python, atau service-role key.

- Pendaftaran dimulai sebagai pembeli; pengguna mengisi profil dan data usaha di
  Pengaturan sebelum mengaktifkan mode Penjual.
- Penjual dapat mengambil foto dari kamera ponsel (`capture="environment"`) atau
  memilih file. Kedua jalur mengunggah foto ke Cloudinary sebelum listing disimpan.
- Listing menyimpan stok serta kuota minimum/maksimum per pesanan. Pembeli dapat
  checkout langsung atau checkout penawaran yang disetujui; server memeriksa kuota
  dan mengurangi stok dalam satu transaksi database.
- Setelah checkout, portal membuka chat dengan pemilik listing. Favorit, profil,
  penawaran, checkout, transaksi, dan persetujuan pembayaran ditangani oleh RPC
  yang memvalidasi token sesi pada database.
- Admin dapat menonaktifkan Pembayaran, DP, dan Biaya di dashboard. Jika Pembayaran
  mati, pemesanan tetap tercatat dengan DP dan biaya layanan nol. Jika hanya DP mati,
  pesanan menunggu pelunasan penuh sesuai pengaturan pembayaran.

Migrasi `supabase/migrations/0013_infinityfree_marketplace.sql` menambah kolom kuota dan operasi order/penawaran transaksional. Migrasi `supabase/migrations/0015_infinityfree_gateway_security.sql` mengamankan login/sesi dan pembaruan listing. Migrasi `0016_private_payment_settings.sql` melindungi data rekening/QRIS penjual. Terapkan migrasi 0013 dan 0015–0016 sebelum portal dibuka untuk pengguna. Workflow database menerapkannya bersama
migrasi lain ketika perubahan masuk ke `main`; untuk instalasi baru, skema gabungan
di `supabase-schema.sql` sudah memuat SQL migrasi tersebut. Deploy `htdocs/` tetap
terpisah dari server Flask dan tidak menghapus atau menimpa kode backend utama.

## Troubleshooting
| Gejala | Solusi |
|---|---|
| `503 Supabase belum dikonfigurasi` | `config.php` belum ada / field kosong |
| `Kunci Supabase ditolak` | Gunakan **Publishable key** (`sb_publishable_...`) atau legacy **anon public** (`eyJ...`); jangan gunakan secret/service_role |
| `SUPABASE_URL tidak valid` | Isi ref/URL project yang benar (kolom alamat dashboard Supabase) |
| Login gagal padahal seed sudah jalan | Pastikan `seed-supabase.sql` dijalankan SETELAH schema; hash bcrypt demo butuh ~1 dtk/proses |
| Upload foto gagal | Cek 3 nilai Cloudinary; pastikan preset unsigned `agrid_unsigned` dibuat di Settings → Upload |
| Slow / limit FTP | InfinityFree gratis membatasi inode & request; aktifkan caching `.htaccess` bawaan |
