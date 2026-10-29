# ⚡ AGR.ID Realtime Auction Service (Golang)

Modul backend microservice lelang berkecepatan tinggi berbasis **Golang + WebSocket (`gorilla/websocket`)**.

## 🌟 Fitur Utama
1. **Ultra Low-Latency (Sub-Millisecond)**: Menggunakan koneksi WebSocket persisten dua arah.
2. **Goroutine FIFO Auction Room**: Setiap ruang lelang (*auction room*) memiliki antrian penawaran berbasis Go channel dan Mutex lock, memastikan **100% bebas dari race condition** (dua penawar di milidetik yang sama diproses tertib satu per satu).
3. **Instant Live Broadcast**: Begitu penawaran valid diterima, nominal terbaru langsung disiarkan ke seluruh peserta dan penonton secara instan tanpa perlu reload halaman.
4. **Graceful HTTP Polling Fallback**: Halaman frontend lelang tetap dapat berfungsi normal via HTTP polling jika service WebSocket sedang tidak aktif.
5. **Single Binary Executable**: Tidak membutuhkan Node runtime atau folder `node_modules` ratusan MB. Hasil build hanya satu file `.exe` (~10 MB).

---

## 🚀 Cara Menjalankan

### Opsi 1: Menjalankan Binary Langsung (Windows)
```powershell
.\services\auction-realtime\auction-server.exe
```

### Opsi 2: Menjalankan dari Source Code Go
```powershell
cd services\auction-realtime
go run .\cmd\server\main.go
```

Port default yang digunakan adalah `:8081`.

---

## 📡 Endpoint & Arsitektur

* `GET /health`: Healthcheck status server.
* `GET /ws/auction/{event_id}?buyer_id=...&buyer_name=...`: Koneksi WebSocket untuk live bidding room.
* `POST /api/auction/{event_id}/bid`: HTTP Bridge endpoint untuk menerima notifikasi penawaran baru dari form Flask atau sistem luar untuk langsung di-broadcast ke room lelang.
