# Panduan Deploy AGR.ID ke InfinityFree (docroot: htdocs)

## Arsitektur
```
Browser ──► InfinityFree (htdocs/)            ──► Supabase PostgREST (data)
              ├─ index.html + agrid-web/      ──► Cloudinary (media, signed upload)
              └─ api.php (gateway PHP)        ──► Flask API opsional (payment/crypto/AI)
```
InfinityFree tidak mengizinkan koneksi DB langsung (port 5432 diblokir), sehingga
semua akses Supabase & Cloudinary dimediasi `htdocs/api.php` (server-side cURL).

## Langkah 1 — Supabase
1. Buat project di https://supabase.com → Project Settings → API: salin **URL** & **anon key**.
   Simpan **service_role key** hanya untuk gateway (jangan diekspos ke browser).
2. SQL Editor → Run isi `htdocs/supabase-schema.sql` (membuat 12 tabel + RLS).
3. Authentication → Sign In / Up → matikan "Confirm email" agar registrasi via gateway jalan.

## Langkah 2 — Cloudinary
1. Dashboard → Product Library → Create Media Library (bucket public + private).
2. Settings → Upload → tambahkan folder prefix `agrid/`.
3. Catat: Cloud name, API Key, API Secret (dipakai api.php menandatangani upload).

## Langkah 3 — Gateway (htdocs/api.php)
1. Salin `config.example.php` → `config.php`, isi kredensial Supabase + Cloudinary.
2. `flask_url` kosongkan dulu; isi URL backend Flask bila ingin payment gateway,
   blockchain AGR Coin, dan AI chat agent aktif (Render free tier cocok).
3. Upload seluruh isi folder `htdocs/` ke docroot InfinityFree bernama **htdocs**
   (via Online File Manager atau FTP akun *.epizy/rf.gd — root folder = `htdocs`).

## Langkah 4 — Frontend statis
1. Export halaman Flask menjadi HTML statis, taruh di `htdocs/agrid-web/`:
   `python3 tools/export_static.py` (index.html, marketplace.html, login/register dll.)
2. JS frontend memanggil `/api.php?action=...` dengan header `X-Agr-Token`
   (token didapat dari aksi `login`; disimpan di localStorage).

## Langkah 5 — Akun demo awal
Jalankan sekali di SQL Editor Supabase (password penjual123 sudah di-bcrypt):
lihat bagian bawah file ini.

## Catatan Keamanan
- `config.php` TIDAK di-commit (.gitignore) — upload manual via File Manager.
- Anon key boleh di browser karena RLS menolak INSERT/UPDATE/DELETE langsung;
  penulisan data hanya lewat api.php yang memverifikasi token sesi + role.
- Dokumen KYC privat: folder `agrid/private/<user_id>` di Cloudinary, diakses
  hanya via `api.php?action=media-private-url` (signed URL 5 menit, cek status DP).
- Rate limit InfinityFree ± 40k hit/hari; ticker harga sebaiknya di-cache
  sisi klien (localStorage 10 menit) agar hemat request.

## Seed akun demo (SQL Editor Supabase)
```sql
insert into users(email,nama,password_hash,role,tipe,alamat,no_hp) values
 ('penjual@agr.id','Tani Jaya',     '<bcrypt-penjual123>','penjual','Perorangan','Brebes','08123'),
 ('koperasi@agr.id','Kopi Mitra',   '<bcrypt-penjual123>','penjual','Koperasi','Bandung','08124'),
 ('pembeli@agr.id','Bu Sari',       '<bcrypt-pembeli123>','pembeli','Perorangan','Jakarta','08125'),
 ('corporate@agr.id','PT Segar',    '<bcrypt-corporate123>','pembeli','Corporate','Surabaya','08126'),
 ('admin@agr.id','Admin AGR',       '<bcrypt-admin123>','admin','Perorangan','','');
```
Buat hash bcrypt via `php -r "echo password_hash('penjual123', PASSWORD_BCRYPT);"`.
