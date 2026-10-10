# 🌾 AGR.ID — Marketplace Pertanian, Perkebunan, Perikanan & Peternakan

**AGR.ID** adalah webapp marketplace B2B/B2C yang mempertemukan **penjual** (petani, nelayan, peternak, koperasi, kelompok tani/paguyuban) langsung dengan **pembeli** (perorangan maupun corporate) — dilengkapi **AI Chat Agent**, alur **penawaran harga → booking dengan DP → payment gateway → jadwal pengiriman → verifikasi eviden (foto + GPS)**, serta **laporan transaksi** untuk penjual, pembeli, dan admin.

Dibangun dengan **Python Flask + SQLAlchemy (SQLite)** dan UI component system **shadcn/ui v3** (light & dark mode).

---

## ✨ Fitur Utama

### Marketplace & Katalog
- **4 kategori utama**: Pertanian, Perkebunan, Perikanan, Peternakan.
- **Sub kategori**:
  - Pertanian → *Sayuran*, *Buah-buahan*
  - Perikanan → *Air Tawar*, *Air Laut*
  - Perkebunan → *Tanaman Tahunan, Tanaman Industri, Rempah-rempah, Serat*
  - Peternakan → *Sapi & Kerbau, Kambing & Domba, Unggas, Babi, Susu & Hasil Hewan Lainnya, Lainnya*
- **±240 nama produk + jenis/varietas** per sub kategori (master data di `masterdata.py`).
- **Label ⚠️ NON HALAL** otomatis pada sub kategori **Babi** (badge di listing, detail produk, form posting) + toggle filter "sembunyikan Non Halal" di marketplace.
- **Ticker harga market** berjalan (animated marquee) berisi ±75 komoditas dengan harga & persentase naik/turun harian.
- **Database Produk auto-update**: saat penjual mengetik nama produk baru di form, autocomplete memanggil `/api/produk-master`; nama yang belum ada **otomatis disimpan ke tabel `produk_master`** (flag `auto_added`).

### Akun, Pendaftaran & Login
- Tombol **Login** dan **Daftar** di navbar; halaman pendaftaran terpisah peran.
- **Tipe Penjual**: Perorangan / Koperasi / Kelompok Tani (Paguyuban) — badan usaha mengisi NPWP & NIB.
- **Tipe Pembeli**: Perorangan / Corporate — input NPWP/NIB muncul otomatis untuk Corporate.
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

## 🗄️ Struktur Database (SQLite — `agrid.db`)

| Tabel | Isi |
|---|---|
| `users` | Penjual / pembeli / admin (peran, tipe akun, NPWP/NIB, alamat, GPS, pengaturan metode DP penjual) |
| `produk_master` | Master nama produk & jenis; auto-tambah saat penjual mengetik nama baru |
| `products` | Listing produk penjual (harga, stok, foto, GPS kebun/kolam/kandang, label non-halal) |
| `offers` | Penawaran harga pembeli + status (pending/accepted/rejected) |
| `bookings` | Booking pengikat DP (% DP, metode, status) |
| `pelunasan` | Pengajuan pelunasan DP + upload bukti transfer + approval penjual |
| `transaksi` | Transaksi penjualan & pembelian (status: dp → lunas → dikirim → selesai) |
| `eviden` | Timeline ketelusuran: foto bukti + koordinat GPS per tahap |
| `favorites` | Penyimpanan penjual/produk favorit oleh pembeli |
| `ratings` | Skor kepuasan dua arah + aspek (JSON) + komentar |
| `payment_gateway_api` | Konfigurasi API payment gateway dari admin |
| `ekspedisi` | Konfigurasi API & tarif jasa ekspedisi |
| `pengaturan` | Semua pengaturan platform (DP%, biaya, footer, tampilan laporan, dll.) |
| `chat_messages` | Riwayat percakapan AI agent |

Skema dibuat & dimigrasi otomatis (`db.create_all()`) + seed data demo saat pertama kali dijalankan.

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

---

## 🔑 Akun Demo

| Peran | Email | Password |
|---|---|---|
| Penjual (Perorangan) | `penjual@agr.id` | `penjual123` |
| Penjual (Koperasi) | `koperasi@agr.id` | `penjual123` |
| Pembeli (Perorangan) | `pembeli@agr.id` | `pembeli123` |
| Pembeli (Corporate) | `corporate@agr.id` | `corporate123` |
| Admin | `admin@agr.id` | `admin123` |

---

## 🔌 Integrasi (Siap Disambungkan)

- **Payment Gateway**: konfigurasi lewat dashboard admin (`/admin/pg-api`) — simulator pembayaran berjalan internal; ganti dengan panggilan HTTP nyata ke Midtrans/Xendit/Duitku menggunakan kredensial tersimpan.
- **Jasa Ekspedisi**: daftar kurir + tarif per kg via `/admin/ekspedisi`; endpoint cek ongkir tinggal di-wire pada form booking.
- **LLM/AI**: `POST /api/chat` rule-based — mudah diganti endpoint OpenAI/Claude/Gemini untuk agent yang lebih pintar.

## 📄 Lisensi
Dibuat untuk petani, nelayan & peternak Indonesia 🇮🇩 — silakan kembangkan sesuai kebutuhan.
