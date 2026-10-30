# 🌾 AGR.ID — Marketplace Pertanian, Perkebunan, Perikanan & Peternakan

**AGR.ID** adalah marketplace B2B/B2C yang mempertemukan **penjual** (petani, nelayan, peternak, koperasi, kelompok tani/paguyuban) langsung dengan **pembeli** (perorangan, yayasan, koperasi, maupun perusahaan) — dilengkapi **AI Chat Agent**, alur **penawaran harga → booking dengan DP → payment gateway → jadwal pengiriman → verifikasi eviden (foto + GPS)**, serta **laporan transaksi** untuk penjual, pembeli, dan admin.

Dibangun dengan **Python Flask + SQLAlchemy** untuk aplikasi lokal/server dan frontend statis **HTML/CSS/JavaScript + PHP API gateway** untuk hosting InfinityFree. Database produksi memakai **Supabase (PostgreSQL/PostgREST)**; SQLite digunakan untuk pengembangan Flask lokal.

---

## ✨ Fitur Utama

### Marketplace & Katalog
- **4 kategori utama**: Pertanian, Perkebunan, Perikanan, Peternakan.
- **Sub kategori**:
  - Pertanian → *Sayuran, Buah-buahan, Pupuk, Obat Kimia Pertanian, Vitamin & Nutrisi Tanaman*
  - Perkebunan → *Tanaman Tahunan, Tanaman Industri, Rempah Perkebunan, Karet & Getah, Serat & Lainnya, Pupuk, Obat Kimia Perkebunan, Vitamin & Nutrisi Tanaman*
  - Perikanan → *Air Tawar, Air Laut, Pakan Ikan, Obat Kimia Perikanan, Vitamin & Suplemen Ikan*
  - Peternakan → kategori hasil ternak dan *Pakan Ternak, Obat Kimia Peternakan, Vitamin & Suplemen Ternak*.
- **Master produk dan jenis/varietas** tersedia per sub kategori di `agrid/masterdata.py`, termasuk pupuk organik/NPK, insektisida/fungisida/herbisida, pakan ikan dan ternak, serta vitamin dan suplemen.
- **Label ⚠️ NON HALAL** otomatis pada sub kategori **Babi** (badge di listing, detail produk, form posting) + toggle filter "sembunyikan Non Halal" di marketplace.
- **Ticker harga market** berjalan (animated marquee) berisi ±75 komoditas dengan harga & persentase naik/turun harian.
- **Database Produk auto-update**: saat penjual mengetik nama produk baru di form, autocomplete memanggil `/api/produk-master`; nama yang belum ada **otomatis disimpan ke tabel `produk_master`** (flag `auto_added`).
- **Pesan langsung produk**: pembeli dapat menghubungi pemilik listing dari halaman produk; penjual membalas lewat menu **Pesan**. Setiap percakapan diawali pengingat privasi AGR.ID dan hanya dapat dibaca oleh kedua pihak.

### Lelang Terbuka
- Penjual membuat event lelang untuk satu paket yang terdiri dari beberapa listing dan seluruh stok yang dipilih, misalnya hasil panen, buah di pohon, atau ternak.
- Event mencatat deskripsi paket, foto pendukung, jadwal mulai/tutup, alamat, dan koordinat GPS lokasi lelang/pengambilan.
- Penjual menyertakan syarat dan ketentuan yang harus disetujui semua peserta. Pengajuan ditinjau admin; setelah disetujui, event tayang setelah biaya lelang penjual dibayar.
- Admin mengatur tarif biaya event dan biaya administrasi peserta. Peserta mendaftar dan melunasi biaya administrasi sebelum bisa menawar; tarif disimpan sebagai snapshot saat event disetujui.
- Penjual menentukan jadwal buka/tutup, batas pembayaran pemenang, dan jadwal pengambilan opsional. Semua tawaran tampil live di halaman event.
- Tawaran berlaku untuk total paket dan harus melampaui harga pembukaan atau tawaran tertinggi saat ini. Event menutup otomatis sesuai jadwal; pemenang membayar sebelum tenggat. Jika lewat, penjual dapat membatalkan event atau memilih penawar lain dan menetapkan tenggat baru.
- Kalender per peran merangkum jadwal lelang, hasil/tenggat pemenang, pendaftaran, pemesanan, pembelian, pengiriman, dan pengambilan. Stok paket dikembalikan bila lelang selesai tanpa penawar atau dibatalkan.
- Pembayaran biaya lelang saat ini dicatat melalui simulasi gateway aplikasi. Penjual dan pemenang tetap mengatur penyerahan paket setelah event ditutup; pembayaran harga paket belum terhubung ke booking/payment gateway produk tunggal.

### Akun, Pendaftaran & Login
- Pendaftaran hanya meminta **email, nama pengguna, dan kata sandi**; pengguna baru memulai dalam mode Pembeli dan dapat login menggunakan email atau nama pengguna.
- Satu akun dapat memiliki mode **Penjual** dan **Pembeli**. Mode Penjual diaktifkan dari Pengaturan Pengguna setelah nama lengkap/usaha, nomor telepon, alamat, kota, provinsi, koordinat GPS, tipe penjual, dan NPWP/NIB untuk badan/organisasi dilengkapi.
- Tipe badan usaha disimpan terpisah untuk masing-masing mode agar pilihan Penjual dan Pembeli tetap sesuai.
- Migrasi `0004_multi_role_accounts.sql` dan `0005_registration_profile_activation.sql` menyiapkan mode multi-peran, mode aktif per sesi, dan nama pengguna unik. Migrasi memberi akun lama dukungan mode yang sudah ada; pendaftaran baru hanya memberi peran Pembeli sampai aktivasi penjual selesai.
- Migrasi `0006_product_chat.sql` menyiapkan percakapan per produk dan fungsi database terautentikasi; tabel pesan tidak dapat dibaca langsung oleh klien publik.
- **Tipe Penjual**: Perorangan / Kelompok-Paguyuban / Koperasi / Perusahaan — tipe organisasi menampilkan kolom NPWP & NIB.
- **Tipe Pembeli**: Perorangan / Yayasan / Koperasi / Perusahaan — tipe organisasi menampilkan kolom NPWP & NIB.
- **Keanggotaan Koperasi**: pengguna dapat menautkan satu atau lebih koperasi dari direktori tersinkron; nomor anggota dan nama dicocokkan dengan roster resmi, sedangkan data yang belum cocok masuk verifikasi admin.
- Alamat lengkap + **koordinat GPS** (tombol deteksi lokasi).
- **Floating window Syarat & Ketentuan** wajib disetujui sebelum masuk halaman pendaftaran/login.
- Profil penjual menampilkan **rating kepuasan** dan dapat ditandai **favorit** oleh pembeli.

### Alur Transaksi (End-to-End)
1. **Penawaran harga (bidding)** — pembeli mengajukan harga pada produk penjual.
2. Penjual **menerima/menolak** penawaran dari dashboardnya.
3. **Booking dengan DP sebagai pengikat** — besar DP mengikuti **persen DP** pengaturan admin; pembeli memilih metode DP sesuai konfigurasi penjual (**Tunai / Transfer Bank / Scan QRIS**).
4. **Pembayaran via Payment Gateway** (QRIS / VA / e-wallet / transfer bank) dengan nomor referensi.
5. **Pelunasan DP (sistem angsuran)** — pembeli menekan tombol *Selesaikan Pembayaran*, **upload bukti transfer**, status menjadi `menunggu_approval`, lalu **disetujui/ditolak penjual** dari tab khusus → transaksi menjadi *lunas*.
6. **Jadwal pengiriman** + pilih ekspedisi + tracking number → status *delivered* → *completed*.
7. **Verifikasi & Ketelusuran (eviden)** — timeline tiap tahap (panen, sortasi, pengemasan, pengiriman, penerimaan) dengan keterangan, **foto bukti**, **koordinat GPS** + link peta.

### Penilaian Kepuasan Dua Arah ⭐
- Setelah transaksi selesai, **penjual ⇄ pembeli saling memberi skor 1–5 bintang**.
- Aspek penilaian: pembeli→penjual (*Kualitas Produk, Pengemasan & Eviden, Komunikasi, Ketepatan Jadwal*); penjual→pembeli (*Ketepatan Pembayaran, Komunikasi & Kerjasama, Kejelasan Pesanan*).
- Rata-rata rating tampil sebagai badge ★ di profil/halaman produk & dashboard; ada prompt transaksi belum dinilai di dashboard.

### Dashboard Penjual
- Statistik omzet, produk aktif, penawaran masuk.
- Kelola produk (tambah/edit/hapus), terima/tolak penawaran, approval pelunasan.
- **Laporan transaksi penjualan** (+ rekap sesuai pengaturan tampilan laporan admin).
- **Pengaturan pembayaran**: aktif/nonaktifkan metode DP (Tunai / Transfer Bank / QRIS) + detail rekening/QRIS.

### Dashboard Pembeli
- Penawaran aktif, booking & bayar DP, status pelunasan.
- **Tombol penyelesaian pembayaran** untuk sistem DP + upload bukti transfer.
- **Laporan transaksi pembelian**.
- **Favorit**: menyimpan penjual dan/atau produk favorit (toggle ❤️), dikelola di dashboard.
- **Manajemen Kebutuhan**: susun rencana belanja dari semua kategori, isi jumlah, satuan, dan perkiraan harga per satuan; total estimasi dihitung otomatis dan daftar tersimpan per akun pembeli.

### Dashboard Admin
- **Laporan transaksi keuangan**: GMV, pendapatan platform (biaya penanganan), rekap per metode pembayaran, export CSV.
- **Input API Payment Gateway** (Midtrans/Xendit/Duitku dkk): base URL, API key, secret, webhook, channel.
- **Input API Jasa Ekspedisi**: nama, URL, API key, tarif/kg.
- **Pengaturan biaya**: persen **DP Booking**, **biaya penanganan**, biaya tambahan flat, biaya verifikasi, + **biaya custom** (tambah/edit/hapus).
- **Pengaturan laporan**: toggle menampilkan laporan penjualan/pembelian, rekap keuangan, tabel detail, rekap metode, jumlah baris per tabel.
- **Pengaturan footer landing page**: tentang, kontak, alamat, email, telepon/WA, jam operasional, sosial media, copyright, tautan cepat.

### AI Chat Agent 🤖
- Widget floating di semua halaman + halaman penuh `/chat`.
- Memandu **wizard pengisian informasi produk**, autocomplete/cari produk dari database, menjelaskan DP booking, ekspedisi, dan alur transaksi.
- Rule-based (mudah diganti ke LLM API); riwayat tersimpan di `chat_messages`.

---

## 🗄️ Struktur Database

Flask membuat database SQLite lokal `agrid/agrid.db`. Deployment statis menggunakan schema PostgreSQL Supabase dari `supabase/migrations/` dan `htdocs/supabase-schema.sql`.

| Tabel | Isi |
|---|---|
| `users` | Akun, username unik, daftar mode (`roles`), mode dasar, tipe Penjual dan Pembeli terpisah, NPWP/NIB, alamat, GPS, dan pengaturan metode DP penjual |
| `koperasi`, `koperasi_anggota`, `keanggotaan_koperasi` | Direktori koperasi, roster anggota resmi yang disinkronkan, dan tautan anggota ke akun marketplace |
| `sessions` | Token sesi gateway dan mode akun aktif (`active_role`) |
| `produk_master` | Master nama produk & jenis; auto-tambah saat penjual mengetik nama baru |
| `products` | Listing produk penjual (harga, stok, foto, GPS kebun/kolam/kandang, label non-halal) |
| `offers` | Penawaran harga pembeli + status (pending/accepted/rejected) |
| `bookings` | Booking pengikat DP (% DP, metode, status) |
| `pelunasan` | Pengajuan pelunasan DP + upload bukti transfer + approval penjual |
| `transaksi` | Transaksi penjualan & pembelian (status: dp → lunas → dikirim → selesai) |
| `eviden` | Timeline ketelusuran: foto bukti + koordinat GPS per tahap |
| `favorites` | Penyimpanan penjual/produk favorit oleh pembeli |
| `kebutuhan_pembeli` | Rencana belanja pembeli per kategori, jumlah, satuan, harga estimasi, dan total yang dihitung otomatis |
| `lelang_events` | Event lelang terbuka, waktu, lokasi GPS, foto, harga pembukaan, dan status |
| `lelang_items` | Snapshot produk dan stok yang digabung menjadi paket lelang |
| `lelang_participants` | Konfirmasi keikutsertaan pembeli di event |
| `lelang_bids` | Riwayat tawaran peserta dan nominal paket |
| `ratings` | Skor kepuasan dua arah + aspek (JSON) + komentar |
| `payment_gateway_api` | Konfigurasi API payment gateway dari admin |
| `ekspedisi` | Konfigurasi API & tarif jasa ekspedisi |
| `pengaturan` | Semua pengaturan platform (DP%, biaya, footer, tampilan laporan, dll.) |
| `chat_messages` | Riwayat percakapan AI agent |

Skema SQLite lokal dibuat (`db.create_all()`) dan diisi seed demo saat pertama kali dijalankan. Migrasi database produksi dikelola sebagai file SQL dan diterapkan oleh workflow GitHub Actions ke Supabase.

Sistem koperasi menyinkronkan direktori dan roster ke `POST /api/v1/cooperatives/sync` menggunakan token API berperan `koperasi` yang dibuat di Dashboard Admin. Kontrak payload dan aturan sinkronisasi tersedia di [KOPERASI_MARKETPLACE_INTEGRATION.md](KOPERASI_MARKETPLACE_INTEGRATION.md).

---

## 🧱 Struktur Proyek

```
agrid/
├── app.py               # Aplikasi Flask inti: model DB, routes, logika transaksi, AI agent, seed
├── masterdata.py        # Master kategori/sub kategori + ±240 produk & jenisnya
├── requirements.txt     # Flask>=3.0, Flask-SQLAlchemy>=3.1, Werkzeug>=3.0
├── start-website.bat    # Skrip peluncuran otomatis untuk Windows (lokal)
├── agrid.db             # Database SQLite (auto-created + seed)
├── static/
│   └── shadcn.css       # Design system shadcn/ui v3 (tokens, komponen, dark mode)
└── templates/           # 17 halaman Jinja2 (base, home, marketplace, product, register,
                         # login, dashboard penjual/pembeli/admin, form produk, booking,
                         # payment, pelunasan, eviden, rate, chat, dsb.)
```

---

## 🚀 Cara Menjalankan

### Opsi 1 — Windows (double-click)
Jalankan **`start-website.bat`** — skrip otomatis mendeteksi Python, membuat virtual environment (`.venv`), menginstal dependency dari `requirements.txt`, membuka browser, lalu menjalankan server di **http://localhost:5000**. Port bisa diubah pada variabel `PORT` di awal file.

### Opsi 2 — Manual (semua OS)
```bash
cd agrid
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python3 app.py            # atau: PORT=8080 python3 app.py
```
Buka **http://127.0.0.1:5000**. Server bind ke `0.0.0.0` sehingga juga bisa diakses dari perangkat lain dalam jaringan.

> Tidak diperlukan `index.html` statis — halaman beranda dirender dinamis oleh route `/` (template `home.html`).

### Opsi 3 — Deploy produksi (Supabase + InfinityFree)

1. Siapkan Supabase project dan jalankan migrasi database melalui workflow **Push Database ke Supabase**. Perubahan SQL di `supabase/migrations/` otomatis memicu workflow tersebut saat didorong ke `main`.
2. Tambahkan GitHub **Repository Secrets** di **Settings → Secrets and variables → Actions**:
   - `SUPABASE_PROJECT_REF` dan `SUPABASE_MANAGEMENT_TOKEN` untuk migrasi database.
   - `SUPABASE_ANON_KEY`, `AGR_ID_SESSION_SECRET`, `FTP_SERVER`, `FTP_USERNAME`, dan `FTP_PASSWORD` untuk deploy website.
   - `AGR_ID_SESSION_SECRET` harus berupa string acak minimal 64 karakter. Jangan commit nilai secret ke repo.
3. Untuk mengaktifkan Cloudinary, tambahkan GitHub Repository Secrets `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, dan `CLOUDINARY_API_SECRET` dari Cloudinary Dashboard → **Settings → Access Keys**. Workflow membuat `htdocs/config.php` dari secrets saat deploy; jangan commit file konfigurasi atau API Secret ke repository. `AGR_ID_API_URL` hanya diperlukan untuk layanan backend Flask opsional.
4. Push perubahan pada `htdocs/` ke branch `main` untuk menjalankan **Deploy to InfinityFree**. Workflow memvalidasi sintaks PHP, membuat `htdocs/config.php` dari secrets, lalu mengirim file melalui FTP. File konfigurasi tidak disimpan di Git.
5. Untuk konfigurasi lengkap dan langkah pemulihan, lihat [DEPLOY-INFINITYFREE.md](DEPLOY-INFINITYFREE.md).

### Upload media Cloudinary

- Saat penjual mengunggah foto produk, frontend meminta signature sementara melalui `api.php?action=media-signature`. API memvalidasi sesi mode Penjual dan membuat signature memakai kredensial server.
- Browser mengunggah foto langsung ke endpoint Cloudinary `image/upload`. API Secret tidak pernah dikirim ke browser. Foto publik dibatasi ke JPG/JPEG, PNG, atau WebP dengan ukuran maksimal 8 MB dan disimpan pada folder produk AGR.ID.
- Dokumen KYC menggunakan jalur privat dan tidak ditampilkan sebagai foto publik. Aksesnya menggunakan URL bertanda tangan dengan masa berlaku terbatas.
- Untuk mengecek konfigurasi setelah deploy, buka `https://<domain-anda>/api.php?action=health`. Nilai `cloudinary: true` menandakan Cloud Name, API Key, dan API Secret terbaca oleh server. Agar workflow juga menjalankan health check otomatis, atur GitHub Actions Variable `SITE_DOMAIN` ke hostname situs Anda.

---



---

## 🔌 Integrasi (Siap Disambungkan)

- **Payment Gateway**: konfigurasi lewat dashboard admin (`/admin/pg-api`) — simulator pembayaran berjalan internal; ganti dengan panggilan HTTP nyata ke Midtrans/Xendit/Duitku menggunakan kredensial tersimpan.
- **Jasa Ekspedisi**: daftar kurir + tarif per kg via `/admin/ekspedisi`; endpoint cek ongkir tinggal di-wire pada form booking.
- **LLM/AI**: `POST /api/chat` rule-based — mudah diganti endpoint OpenAI/Claude/Gemini untuk agent yang lebih pintar.

## 📄 Lisensi
Dibuat untuk petani, nelayan & peternak Indonesia 🇮🇩 — silakan kembangkan sesuai kebutuhan.

