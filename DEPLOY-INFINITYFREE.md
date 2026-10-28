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
1. Buat project di https://supabase.com → Project Settings → API: salin **URL** & **anon public key**.
   Gateway PHP memakai anon key dan kebijakan RLS; jangan gunakan service-role key di hosting atau workflow.
2. SQL Editor → Run isi `htdocs/supabase-schema.sql` (membuat 12 tabel + RLS).
3. Jalankan migration `0004_multi_role_accounts.sql`, `0005_registration_profile_activation.sql`, dan `0006_product_chat.sql` untuk mode akun, aktivasi penjual, serta pesan produk. Workflow database menerapkan migration tersebut otomatis bila `SUPABASE_PROJECT_REF` dan `SUPABASE_MANAGEMENT_TOKEN` valid.
4. Jalankan `htdocs/seed-supabase.sql` bila ingin memasukkan akun dan katalog demo.
5. Authentication → Sign In / Up → matikan "Confirm email" agar registrasi via gateway jalan.

## Langkah 2 — Cloudinary
1. Dashboard → Product Library → Create Media Library (bucket public + private).
2. Settings → Upload → tambahkan folder prefix `agrid/`.
3. Catat: Cloud name, API Key, API Secret (dipakai api.php menandatangani upload).

## Langkah 3 — Secrets deploy
1. Di GitHub → Settings → Secrets and variables → Actions, isi secrets wajib:
   `FTP_SERVER`, `FTP_USERNAME`, `FTP_PASSWORD`, `SUPABASE_ANON_KEY`, dan `AGR_ID_SESSION_SECRET`.
2. `AGR_ID_SESSION_SECRET` harus acak dan minimal 64 karakter. Untuk upload foto,
   isi `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, dan `CLOUDINARY_API_SECRET`
   dari Cloudinary Dashboard → Settings → Access Keys. `AGR_ID_API_URL` opsional.
3. Workflow membuat `htdocs/config.php` saat build dan mengirimnya lewat FTP; file itu tetap diabaikan Git.
   Push ke `main` pada folder `htdocs/` menjalankan deploy otomatis.

## Langkah 4 — Frontend statis
1. Export halaman Flask menjadi HTML statis, taruh di `htdocs/agrid-web/`:
   `python3 tools/export_static.py` (index.html, marketplace.html, login/register dll.)
2. JS frontend memanggil `/api.php?action=...` dengan header `X-Agr-Token`
   (token didapat dari aksi `login`; disimpan di localStorage).

## Langkah 5 — Akun demo awal
Jalankan sekali di SQL Editor Supabase (password penjual123 sudah di-bcrypt):
lihat bagian bawah file ini.

## Catatan Keamanan
- `config.php` TIDAK di-commit (.gitignore); workflow membuatnya dari GitHub Secrets.
- Anon key boleh di browser karena RLS menolak INSERT/UPDATE/DELETE langsung;
  penulisan data hanya lewat api.php yang memverifikasi token sesi + role.
- Bila service-role key pernah tersimpan di file atau riwayat GitHub publik, rotasi key itu di Supabase sebelum deploy berikutnya.
- Dokumen KYC privat: folder `agrid/private/<user_id>` di Cloudinary, diakses
  hanya via `api.php?action=media-private-url` (signed URL 5 menit, cek status DP).
- Foto produk: frontend meminta signature sementara ke `api.php?action=media-signature`,
  lalu mengunggah langsung ke Cloudinary `image/upload`. API Secret hanya berada di
  server. Upload produk hanya diberikan kepada sesi dengan mode penjual aktif;
  format JPG/PNG/WebP, maksimal 8 MB. Pastikan endpoint `api.php?action=health`
  menampilkan `cloudinary: true` setelah deploy.
- Rate limit InfinityFree ± 40k hit/hari; ticker harga sebaiknya di-cache
  sisi klien (localStorage 10 menit) agar hemat request.

## Seed akun demo (SQL Editor Supabase)
```sql
insert into users(email,username,nama,password_hash,role,tipe,alamat,no_hp) values
 ('penjual@agr.id','tani_jaya','Tani Jaya',     '<bcrypt-penjual123>','penjual','Perorangan','Brebes','08123'),
 ('koperasi@agr.id','kopi_mitra','Kopi Mitra',  '<bcrypt-penjual123>','penjual','Koperasi','Bandung','08124'),
 ('pembeli@agr.id','bu_sari','Bu Sari',          '<bcrypt-pembeli123>','pembeli','Perorangan','Jakarta','08125'),
 ('corporate@agr.id','pt_segar','PT Segar',      '<bcrypt-corporate123>','pembeli','Perusahaan','Surabaya','08126'),
 ('admin@agr.id','admin_agrid','Admin AGR',      '<bcrypt-admin123>','admin','Perorangan','','');
```
Buat hash bcrypt via `php -r "echo password_hash('penjual123', PASSWORD_BCRYPT);"`.

