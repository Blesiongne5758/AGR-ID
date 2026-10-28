# 🚀 Deploy AGR.BIZ.ID ke InfinityFree + Supabase + Cloudinary

## Langkah 1 — Buat project Supabase & jalankan skema
1. Buka https://supabase.com → **New project** (region Singapore, set password DB).
2. Tunggu provisioning, lalu **SQL Editor → New query**:
   - Tempel seluruh isi `supabase-schema.sql` → **Run** (membuat 12 tabel + RLS).
   - Tempel seluruh isi `seed-supabase.sql` → **Run** (produk master, kategori, harga pasar, pengaturan, akun demo).
3. Ambil kredensial di **Project Settings → API**:
   - **Project URL** → `https://<REF>.supabase.co` (atau cukup `<REF>`-nya saja)
   - **Legacy API Keys → anon public** (`eyJ...`) ← INI yang dipakai gateway.
   
   > ⚠️ **PENTING soal kunci `sb_publishable_` / `sb_secret_` (format baru):**
   > Kunci format baru hanya untuk **Supabase Auth & Storage**, TIDAK diterima
   > PostgREST/REST API yang dipakai `api.php`. Gateway wajib memakai
   > **anon public key (JWT `eyJ...`)**. Project Anda juga harus dibuat lebih
   > dulu — kedua kunci saja tidak cukup untuk menjalankan deploy database;
   > tanpa Project URL/REF, sistem tidak tahu ke mana request dikirim
   > (gateway akan menolak dengan pesan error yang jelas).
   >
   > 🔒 `sb_secret_` = service key super-privileged. Jangan pernah ditaruh di
   > htdocs/hosting publik; gunakan hanya di backend privat (Flask/Render).

## Langkah 2 — Konfigurasi file config
Di folder `htdocs/`, salin `config.example.php` menjadi `config.php` lalu isi:
```php
'supabase_url'   => 'https://<REF>.supabase.co',  // atau '<REF>' saja
'supabase_key'   => 'eyJ...jwt-key...',
'cloudinary_cloud'  => 'dxxxxxxx',                // dashboard.cloudinary.com -> Upload Settings/Pages? Keys
'cloudinary_key'    => '123456789012345',
'cloudinary_secret' => 'xxxxxxxxxxxxxxxx',
'flask_url'     => '',                             // opsional: backend Flask utk PG/blockchain/chat
'session_secret'=> 'string-acak-64-karakter',      // mis. hasil: php -r "echo bin2hex(random_bytes(32));"
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

## Troubleshooting
| Gejala | Solusi |
|---|---|
| `503 Supabase belum dikonfigurasi` | `config.php` belum ada / field kosong |
| `Kunci "sb_publishable..." bukan anon key` | Ganti `supabase_key` dengan **anon public** JWT (`eyJ...`) |
| `SUPABASE_URL tidak valid` | Isi ref/URL project yang benar (kolom alamat dashboard Supabase) |
| Login gagal padahal seed sudah jalan | Pastikan `seed-supabase.sql` dijalankan SETELAH schema; hash bcrypt demo butuh ~1 dtk/proses |
| Upload foto gagal | Cek 3 nilai Cloudinary; pastikan preset unsigned `agrid_unsigned` dibuat di Settings → Upload |
| Slow / limit FTP | InfinityFree gratis membatasi inode & request; aktifkan caching `.htaccess` bawaan |
