# Integrasi registri anggota KOPERASI → AGR-ID Marketplace

Integrasi ini menghubungkan direktori koperasi dan roster anggota resmi di KOPERASI dengan AGR-ID. Pengguna marketplace memilih koperasi, memasukkan nomor anggota dan nama terdaftar; AGR-ID memverifikasi data itu terhadap roster hasil sinkronisasi.

## Alur pengguna

1. Pengguna masuk ke AGR-ID dan membuka Pengaturan Akun → Keanggotaan Koperasi.
2. Pengguna memilih koperasi aktif, lalu mengisi nomor anggota dan nama sesuai catatan koperasi.
3. Jika nomor dan nama cocok dengan roster aktif, status menjadi terdaftar. Pengajuan yang tidak cocok masuk ke antrean verifikasi admin AGR-ID.
4. Status koperasi atau keanggotaan yang nonaktif tidak dapat diverifikasi sebagai anggota aktif.

## Pengirim KOPERASI

Repo `Blesiongne5758/AGR-ID_KOPERASI` kini memiliki `server/agrid-sync.mjs` dan perintah `npm run sync:agrid`. Pengirim membaca `cooperatives`, `memberships`, dan nama pengguna dari Supabase; nomor anggota diambil dari `memberships.member_number` dengan fallback `users.member_id`. Data contoh UI tidak dipakai.

Konfigurasikan hanya di secret manager pada server KOPERASI:

- `SUPABASE_URL` — URL proyek sumber.
- `SUPABASE_SERVICE_ROLE_KEY` — akses server; jangan masukkan ke frontend.
- `AGRID_BASE_URL` — URL deployment AGR-ID.
- `AGRID_API_TOKEN` — token integrasi role `koperasi` dari Dashboard Admin AGR-ID.

Jalankan `npm run sync:agrid` untuk sinkron manual. Scheduler server dapat menjalankannya setiap hari pukul 02.00 WIB (`0 2 * * *`). Job memakai HTTPS, menolak snapshot kosong, mencoba ulang maksimal tiga kali, dan tidak mencatat token atau payload anggota ke log. GitHub PAT hanya untuk akses repository, bukan kredensial API.

Payload tidak mengirim email, telepon, password, simpanan, atau pinjaman. `snapshot: true` mencakup seluruh koperasi dan status keanggotaan aktif/nonaktif agar roster AGR-ID mengikuti sumber.

## Penerima AGR-ID

`POST /api/v1/cooperatives/sync` menerima Bearer token ber-role `koperasi`. Endpoint dan alur pemilihan anggota sudah dibuat pada workspace AGR-ID; migrasi tabel ada di `supabase/migrations/0009_cooperative_membership.sql`. Admin AGR-ID membuat token terbatas dari panel Direktori Koperasi.

## Batas integrasi

Sinkronisasi ini hanya mencakup direktori koperasi dan validasi keanggotaan pengguna marketplace. Katalog produk, stok, pesanan, saldo, dan pembayaran tidak disinkronkan oleh job ini. Penerima AGR-ID pada workspace perlu dideploy terlebih dahulu; setelah secrets KOPERASI dikonfigurasi, jalankan sinkron pertama dan pastikan respons sukses sebelum menggunakan verifikasi otomatis.
