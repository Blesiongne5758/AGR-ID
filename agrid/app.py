# -*- coding: utf-8 -*-
"""
AGR.ID - Marketplace Pertanian, Perkebunan, Perikanan & Peternakan
Dukungan AI Chat Agent, penawaran harga, booking DP, payment gateway,
ekspedisi, verifikasi & ketelusuran (traceability) dengan bukti eviden.
"""
import os
import json
import random
from datetime import datetime, timedelta, date, timezone
from functools import wraps
from zoneinfo import ZoneInfo

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"),
            static_folder=os.path.join(BASE_DIR, "static"))

# ---- Keamanan sistem: secret key & cookie hardening (lihat security.py) ----
import security
security.session_config(app)

# ---- Dukungan Supabase Postgres (hosting frontend statis di InfinityFree) ----
# Bila SUPABASE_DB_URL / DB_HOST diset, aplikasi otomatis memakai Postgres
# Supabase; tanpa itu tetap SQLite lokal (dev).
def _database_uri():
    url = os.environ.get("AGR_DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")
    if url:
        if url.startswith("postgres://"):            # format lama Supabase
            url = url.replace("postgres://", "postgresql://", 1)
        return url
    if os.environ.get("DB_HOST"):                    # variabel terpisah heroku-style
        return ("postgresql://{u}:{p}@{h}:{port}/{d}?sslmode=require".format(
            u=os.environ.get("DB_USER", "postgres"),
            p=os.environ.get("DB_PASSWORD", ""),
            h=os.environ["DB_HOST"],
            port=os.environ.get("DB_PORT", "5432"),
            d=os.environ.get("DB_NAME", "postgres")))
    return "sqlite:///" + os.path.join(BASE_DIR, "agrid.db")


app.config["SQLALCHEMY_DATABASE_URI"] = _database_uri()
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}   # koneksi SupabasePutus -> auto reconnect
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JSON_SORT_KEYS"] = False
db = SQLAlchemy(app)

import utils
import storage                                   # Storage & Media Architecture (S3 presigned, lihat storage.py)
import cloud_media                               # Cloudinary.com utk multimedia (lihat cloud_media.py)
from masterdata import KATEGORI, TIPE_PENJUAL, TIPE_PEMBELI, MASTER_PRODUK, NON_HALAL_LABEL, flatten_products
import models_api
models_api.init_models(db)          # tabel audit_logs, api_tokens, login_attempts
security.init_security(app)         # CSRF global, header keamanan, context csrf_token

# ----------------------------------------------------------------------------
# MODEL DATABASE
# ----------------------------------------------------------------------------

class User(db.Model):
    """Database user penjual & pembeli."""
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    nama = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    phone = db.Column(db.String(30))
    role = db.Column(db.String(20), nullable=False)          # penjual / pembeli / admin
    tipe = db.Column(db.String(40))                          # Tipe akun sesuai peran penjual atau pembeli
    roles = db.Column(db.JSON, nullable=False, default=list) # Peran yang dapat dipakai akun ini
    tipe_penjual = db.Column(db.String(40))
    tipe_pembeli = db.Column(db.String(40))
    alamat = db.Column(db.Text)
    kota = db.Column(db.String(80))
    provinsi = db.Column(db.String(80))
    lat = db.Column(db.Float)                                # koordinat GPS
    lng = db.Column(db.Float)
    npwp = db.Column(db.String(30))                          # untuk tipe badan/organisasi
    nib = db.Column(db.String(40))                           # nomor induk berusaha
    verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # keamanan: lockout akun setelah gagal login berulang
    failed_logins = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime)
    # blockchain: alamat dompet AGR Coin (privat key TIDAK disimpan di DB)
    crypto_address = db.Column(db.String(64))

    products = db.relationship("Product", backref="seller", lazy=True)

    @property
    def role_list(self):
        roles = self.roles or []
        if isinstance(roles, str):
            try:
                roles = json.loads(roles)
            except (TypeError, ValueError):
                roles = []
        if self.role == "admin":
            return ["admin"]
        return [role for role in roles if role in ("penjual", "pembeli")] or [self.role]

    @property
    def active_role(self):
        selected = session.get("active_role") if session.get("uid") == self.id else None
        return selected if selected in self.role_list else self.role

    @property
    def active_tipe(self):
        if self.active_role == "penjual":
            return self.tipe_penjual or self.tipe or TIPE_PENJUAL[0]
        if self.active_role == "pembeli":
            return self.tipe_pembeli or self.tipe or TIPE_PEMBELI[0]
        return self.tipe or "Admin"


class ProdukMaster(db.Model):
    """Database produk master - auto update saat penjual mengisi nama produk baru."""
    __tablename__ = "produk_master"
    id = db.Column(db.Integer, primary_key=True)
    nama = db.Column(db.String(120), unique=True, nullable=False)
    kategori = db.Column(db.String(40))
    subkategori = db.Column(db.String(60))
    jenis = db.Column(db.Text)                               # daftar jenis, dipisah koma
    non_halal = db.Column(db.Boolean, default=False)
    auto_added = db.Column(db.Boolean, default=False)        # True jika ditambahkan otomatis oleh penjual
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Product(db.Model):
    """Listing barang dagangan penjual di marketplace."""
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    nama_produk = db.Column(db.String(120), nullable=False)
    jenis = db.Column(db.String(120))
    kategori = db.Column(db.String(40))
    subkategori = db.Column(db.String(60))
    deskripsi = db.Column(db.Text)
    harga = db.Column(db.Float, nullable=False)              # per satuan
    satuan = db.Column(db.String(20), default="kg")
    stok = db.Column(db.Float, default=0)
    foto = db.Column(db.String(255))                         # foto produk (url/data)
    alamat_lahan = db.Column(db.Text)                        # lokasi produksi
    lat = db.Column(db.Float)                                # koordinat GPS lahan
    lng = db.Column(db.Float)
    non_halal = db.Column(db.Boolean, default=False)
    sertifikasi = db.Column(db.String(120))                  # misal: organik, SMK3, halal
    status = db.Column(db.String(20), default="aktif")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    offers = db.relationship("Offer", backref="product", lazy=True)


class Offer(db.Model):
    """Penawaran harga dari pembeli ke penjual (bidding)."""
    __tablename__ = "offers"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    qty = db.Column(db.Float, nullable=False)
    harga_penawaran = db.Column(db.Float, nullable=False)    # harga per satuan yang ditawarkan
    total = db.Column(db.Float, nullable=False)
    pesan = db.Column(db.Text)
    harga_terkini = db.Column(db.Float)                        # harga terakhir dalam negosiasi
    harga_disepakati = db.Column(db.Float)                     # snapshot harga saat kedua pihak sepakat
    batas_pembayaran = db.Column(db.DateTime)                  # batas waktu pembayaran DP, disimpan UTC
    status = db.Column(db.String(30), default="menunggu")    # menunggu/balasan_pembeli/balasan_penjual/menunggu_konfirmasi/diterima/ditolak/kedaluwarsa/booking
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    buyer = db.relationship("User", foreign_keys=[buyer_id])


class Booking(db.Model):
    """Booking penawaran menggunakan DP sebagai pengikat."""
    __tablename__ = "bookings"
    id = db.Column(db.Integer, primary_key=True)
    offer_id = db.Column(db.Integer, db.ForeignKey("offers.id"), nullable=False)
    dp_persen = db.Column(db.Float, default=20)              # snapshot persen DP saat booking
    dp_amount = db.Column(db.Float, nullable=False)
    sisa_bayar = db.Column(db.Float, nullable=False)
    biaya_penanganan = db.Column(db.Float, default=0)
    metode_dp = db.Column(db.String(30))                     # Tunai / Transfer Bank / QRIS (metode penjual)
    jadwal_kirim = db.Column(db.Date)
    ekspedisi_id = db.Column(db.Integer, db.ForeignKey("ekspedisi.id"))
    tracking_code = db.Column(db.String(60))
    status = db.Column(db.String(25), default="dp_pending")  # dp_pending/dp_lunas/menunggu_pelunasan/pelunasan_ditolak/dikirim/diterima/selesai/batal
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    offer = db.relationship("Offer", backref="bookings")
    ekspedisi = db.relationship("Ekspedisi")


class Pelunasan(db.Model):
    """Pengajuan pelunasan oleh pembeli (upload bukti transfer) -> approval penjual."""
    __tablename__ = "pelunasan"
    id = db.Column(db.Integer, primary_key=True)
    transaksi_id = db.Column(db.Integer, db.ForeignKey("transaksi.id"), nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    jumlah = db.Column(db.Float, nullable=False)             # nominal pelunasan (sisa + ongkir)
    metode = db.Column(db.String(40))                        # Transfer Bank / Tunai / QRIS
    rekening_tujuan = db.Column(db.String(120))              # info rekening/tujuan dari penjual
    bukti = db.Column(db.Text)                               # data URI foto bukti transfer
    catatan = db.Column(db.Text)
    status = db.Column(db.String(20), default="menunggu")    # menunggu/disetujui/ditolak
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime)
    review_catatan = db.Column(db.String(255))

    transaksi = db.relationship("Transaksi", backref="pelunasans")
    buyer = db.relationship("User", foreign_keys=[buyer_id])


class Transaksi(db.Model):
    """Database penjualan & pembelian (laporan transaksi)."""
    __tablename__ = "transaksi"
    id = db.Column(db.Integer, primary_key=True)
    offer_id = db.Column(db.Integer, db.ForeignKey("offers.id"), nullable=False)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"))
    seller_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    product_name = db.Column(db.String(120))
    qty = db.Column(db.Float)
    nilai = db.Column(db.Float, nullable=False)              # total transaksi
    dp_dibayar = db.Column(db.Float, default=0)
    pelunasan = db.Column(db.Float, default=0)
    biaya_penanganan = db.Column(db.Float, default=0)        # handling fee platform
    ongkir = db.Column(db.Float, default=0)
    metode_bayar = db.Column(db.String(40))                  # payment gateway channel
    ref_payment = db.Column(db.String(80))                   # referensi dari payment gateway
    status = db.Column(db.String(20), default="processing")  # processing/paid/shipped/delivered/completed/cancelled/refunded
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    seller = db.relationship("User", foreign_keys=[seller_id])
    buyer = db.relationship("User", foreign_keys=[buyer_id])
    offer = db.relationship("Offer")


class Eviden(db.Model):
    """Verifikasi & ketelusuran (traceability) dengan bukti eviden."""
    __tablename__ = "eviden"
    id = db.Column(db.Integer, primary_key=True)
    transaksi_id = db.Column(db.Integer, db.ForeignKey("transaksi.id"), nullable=False)
    tahap = db.Column(db.String(40))       # panen/pengemasan/pengiriman/penerimaan/sertifikasi
    keterangan = db.Column(db.Text)
    foto = db.Column(db.Text)              # data URI foto bukti
    lat = db.Column(db.Float)              # koordinat GPS eviden
    lng = db.Column(db.Float)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    transaksi = db.relationship("Transaksi", backref="evidens")


class PaymentGatewayAPI(db.Model):
    """Input API payment gateway pada dashboard admin."""
    __tablename__ = "pg_api"
    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(60))    # Midtrans / Xendit / Duitku / iPaymu
    base_url = db.Column(db.String(255))
    api_key = db.Column(db.String(255))
    server_key = db.Column(db.String(255))
    client_key = db.Column(db.String(255))
    webhook_secret = db.Column(db.String(255))
    enabled = db.Column(db.Boolean, default=False)
    channels = db.Column(db.String(255), default="qris,virtual_account,ewallet,bank_transfer,credit_card")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Ekspedisi(db.Model):
    """Input API jasa ekspedisi pada dashboard admin."""
    __tablename__ = "ekspedisi"
    id = db.Column(db.Integer, primary_key=True)
    nama = db.Column(db.String(60))        # JNE / SiCepat / Agam Express / Kargo Laut dll
    base_url = db.Column(db.String(255))
    api_key = db.Column(db.String(255))
    account_id = db.Column(db.String(80))
    service_types = db.Column(db.String(255), default="reguler,kargo,same day")
    tarif_per_kg = db.Column(db.Float, default=0)
    enabled = db.Column(db.Boolean, default=True)


class Pengaturan(db.Model):
    """Pengaturan biaya tambahan platform (dashboard admin & penjual)."""
    __tablename__ = "pengaturan"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(60), unique=True)
    value = db.Column(db.Text)
    label = db.Column(db.String(255))


class Favorite(db.Model):
    """Penyimpanan penjual / produk favorit oleh pembeli."""
    __tablename__ = "favorites"
    id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)   # penjual favorit
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))               # produk favorit (opsional)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    buyer = db.relationship("User", foreign_keys=[buyer_id])
    seller = db.relationship("User", foreign_keys=[seller_id])
    product = db.relationship("Product")


class KebutuhanPembeli(db.Model):
    """Rencana belanja pembeli untuk beberapa kategori marketplace."""
    __tablename__ = "kebutuhan_pembeli"
    id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True)
    kategori = db.Column(db.String(40), nullable=False)
    nama_produk = db.Column(db.String(120), nullable=False)
    jumlah = db.Column(db.Float, nullable=False)
    satuan = db.Column(db.String(20), nullable=False, default="kg")
    estimasi_harga = db.Column(db.Float, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    product = db.relationship("Product")

    @property
    def estimasi_total(self):
        return self.jumlah * self.estimasi_harga


class LelangEvent(db.Model):
    """Event lelang terbuka untuk satu paket produk/stok milik penjual."""
    __tablename__ = "lelang_events"
    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    judul = db.Column(db.String(160), nullable=False)
    deskripsi = db.Column(db.Text, nullable=False)
    syarat_ketentuan = db.Column(db.Text, nullable=False, default="")
    foto = db.Column(db.String(500), nullable=False)
    alamat_lokasi = db.Column(db.String(255), nullable=False)
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)
    mulai = db.Column(db.DateTime, nullable=False)
    selesai = db.Column(db.DateTime, nullable=False)
    batas_bayar_pemenang = db.Column(db.DateTime)
    jadwal_pengambilan = db.Column(db.DateTime)
    harga_awal = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(32), nullable=False, default="diajukan")
    catatan_admin = db.Column(db.Text)
    biaya_peserta = db.Column(db.Float, nullable=False, default=0)
    biaya_penjual = db.Column(db.Float, nullable=False, default=0)
    biaya_penjual_lunas = db.Column(db.Boolean, nullable=False, default=False)
    ref_biaya_penjual = db.Column(db.String(80))
    disetujui_pada = db.Column(db.DateTime)
    pemenang_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    harga_pemenang = db.Column(db.Float)
    pemenang_bayar_lunas = db.Column(db.Boolean, nullable=False, default=False)
    ref_bayar_pemenang = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    seller = db.relationship("User", foreign_keys=[seller_id])
    pemenang = db.relationship("User", foreign_keys=[pemenang_id])
    items = db.relationship("LelangItem", back_populates="event", cascade="all, delete-orphan", order_by="LelangItem.id")
    participants = db.relationship("LelangParticipant", back_populates="event", cascade="all, delete-orphan")
    bids = db.relationship("LelangBid", back_populates="event", cascade="all, delete-orphan")
    awards = db.relationship("LelangAward", back_populates="event", cascade="all, delete-orphan", order_by="LelangAward.id")

    @property
    def tawaran_tertinggi(self):
        return max(self.bids, key=lambda b: (b.nominal, -b.id)) if self.bids else None

    @property
    def peringkat_tawaran(self):
        """Tawaran terbaik tiap peserta, peringkat nominal turun dan tie lebih awal."""
        terbaik = {}
        for bid in self.bids:
            if bid.buyer_id not in terbaik or (bid.nominal, -bid.id) > (
                    terbaik[bid.buyer_id].nominal, -terbaik[bid.buyer_id].id):
                terbaik[bid.buyer_id] = bid
        return sorted(terbaik.values(), key=lambda bid: (-bid.nominal, bid.id))

    @property
    def penetapan_aktif(self):
        return self.awards[-1] if self.awards else None


class LelangAward(db.Model):
    """Riwayat penetapan pemenang dan tenggat pembayaran pada satu event."""
    __tablename__ = "lelang_awards"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("lelang_events.id", ondelete="CASCADE"), nullable=False, index=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    nominal = db.Column(db.Float, nullable=False)
    batas_bayar = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="menunggu")  # menunggu/lunas/kedaluwarsa/dibatalkan
    ref_pembayaran = db.Column(db.String(80))
    ditetapkan_pada = db.Column(db.DateTime, default=datetime.utcnow)
    dibayar_pada = db.Column(db.DateTime)

    event = db.relationship("LelangEvent", back_populates="awards")
    buyer = db.relationship("User", foreign_keys=[buyer_id])


class LelangItem(db.Model):
    """Snapshot produk dan stok yang dilelang sebagai satu paket."""
    __tablename__ = "lelang_items"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("lelang_events.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="SET NULL"))
    nama_produk = db.Column(db.String(120), nullable=False)
    kategori = db.Column(db.String(40), nullable=False)
    subkategori = db.Column(db.String(60))
    jumlah = db.Column(db.Float, nullable=False)
    satuan = db.Column(db.String(20), nullable=False)
    harga_listing = db.Column(db.Float, nullable=False)

    event = db.relationship("LelangEvent", back_populates="items")
    product = db.relationship("Product")


class LelangParticipant(db.Model):
    """Konfirmasi keikutsertaan pembeli pada event lelang terbuka."""
    __tablename__ = "lelang_participants"
    __table_args__ = (db.UniqueConstraint("event_id", "buyer_id", name="uq_lelang_participant"),)
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("lelang_events.id"), nullable=False, index=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    biaya_administrasi = db.Column(db.Float, nullable=False, default=0)
    biaya_lunas = db.Column(db.Boolean, nullable=False, default=False)
    ref_pembayaran = db.Column(db.String(80))
    dibayar_pada = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    event = db.relationship("LelangEvent", back_populates="participants")
    buyer = db.relationship("User", foreign_keys=[buyer_id])


class LelangBid(db.Model):
    """Penawaran pembeli yang sudah terdaftar sebagai peserta."""
    __tablename__ = "lelang_bids"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("lelang_events.id"), nullable=False, index=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    nominal = db.Column(db.Float, nullable=False)
    catatan = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    event = db.relationship("LelangEvent", back_populates="bids")
    buyer = db.relationship("User", foreign_keys=[buyer_id])


class Rating(db.Model):
    """Score penilaian tingkat kepuasan dua arah antara penjual & pembeli.

    Arah 'ke_penjual' : diberikan pembeli kepada penjual atas suatu transaksi selesai.
    Arah 'ke_pembeli' : diberikan penjual kepada pembeli atas transaksi selesai.
    """
    __tablename__ = "ratings"
    id = db.Column(db.Integer, primary_key=True)
    transaksi_id = db.Column(db.Integer, db.ForeignKey("transaksi.id"), nullable=False)
    from_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    to_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    arah = db.Column(db.String(20), default="ke_penjual")   # ke_penjual / ke_pembeli
    score = db.Column(db.Integer, nullable=False)           # 1..5 bintang
    aspek = db.Column(db.Text)                              # JSON: {"kualitas":4,"ketepatan_jadwal":5,...}
    komentar = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    transaksi = db.relationship("Transaksi", backref="ratings")
    from_user = db.relationship("User", foreign_keys=[from_user_id])
    to_user = db.relationship("User", foreign_keys=[to_user_id])


ASPEK_KEPUASAN = {
    "ke_penjual": [("kualitas", "Kualitas Produk"), ("pengemasan", "Pengemasan & Eviden"),
                   ("komunikasi", "Komunikasi & Respons"), ("jadwal", "Ketepatan Jadwal Kirim")],
    "ke_pembeli": [("ketepatan_bayar", "Ketepatan Pembayaran"), ("komunikasi", "Komunikasi & Kerjasama"),
                   ("kejelasan", "Kejelasan Pesanan & Spesifikasi")],
}


def rating_stats(user_id):
    """Rekap rata-rata skor & jumlah penilaian yang diterima seorang user."""
    rows = Rating.query.filter_by(to_user_id=user_id).all()
    if not rows:
        return {"avg": None, "count": 0, "star": "☆"}
    avg = sum(r.score for r in rows) / len(rows)
    full = int(round(avg))
    return {"avg": round(avg, 2), "count": len(rows),
            "star": "★" * full + "☆" * (5 - full)}


def my_rating_for(tx_id, uid):
    return Rating.query.filter_by(transaksi_id=tx_id, from_user_id=uid).first()


def pending_ratings(uid):
    """Transaksi completed yang belum dinilai oleh user tsb (untuk prompt di dashboard)."""
    done = Transaksi.query.filter(Transaksi.status == "completed").all()
    out = []
    for t in done:
        if t.seller_id == uid or t.buyer_id == uid:
            if not my_rating_for(t.id, uid):
                out.append(t)
    return out


class ChatMessage(db.Model):
    """Riwayat chat AI agent (bantuan input produk & pencarian produk)."""
    __tablename__ = "chat_messages"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    sender = db.Column(db.String(10))      # user / ai
    text = db.Column(db.Text)
    payload = db.Column(db.Text)           # JSON opsional (hasil pencarian/form wizard)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


def seller_rating_cache(products):
    """Rekap rating penjual utk sekumpulan produk (dipakai kartu produk)."""
    cache = {}
    for pr in products:
        sid = pr.seller_id
        if sid not in cache:
            cache[sid] = rating_stats(sid)
    return cache


def get_setting(key, default=None):
    p = Pengaturan.query.filter_by(key=key).first()
    return p.value if p else default


@app.context_processor
def inject_footer_info():
    """Info footer landing page (pengaturan dashboard admin) tersedia di semua template."""
    try:
        keys = ("footer_tentang", "footer_kontak", "footer_alamat", "footer_email",
                "footer_telepon", "footer_jam_operasional", "footer_sosial",
                "footer_copyright", "footer_tautan")
        vals = {p.key: p.value for p in Pengaturan.query.filter(Pengaturan.key.in_(keys)).all()}
        footer = {k: vals.get(k, "") for k in keys}
    except Exception:
        footer = {}
    return {"footer": footer}


def set_setting(key, value, label=None):
    p = Pengaturan.query.filter_by(key=key).first()
    if not p:
        p = Pengaturan(key=key, value=str(value), label=label or key)
        db.session.add(p)
    else:
        p.value = str(value)
    db.session.commit()
    return p


# ----------------------------------------------------------------------------
# KONFIGURASI ADMIN — REGISTER FITUR (aktif/nonaktif semua fitur terpusat)
# ----------------------------------------------------------------------------
FEATURE_KEYS = {
    "fitur_marketplace":      ("Marketplace & Listing Produk", "Katalog publik, pencarian & filter produk"),
    "fitur_penawaran":        ("Penawaran Harga (Bidding)", "Pembeli mengajukan harga; penjual terima/tolak"),
    "fitur_booking_dp":       ("Booking DP Pengikat", "Penguncian transaksi dengan uang muka (DP)"),
    "fitur_payment_gateway":  ("Payment Gateway", "Pembayaran QRIS/VA/e-wallet via gateway"),
    "fitur_ekspedisi":        ("Jasa Ekspedisi & Jadwal Kirim", "Perhitungan ongkir & tracking pengiriman"),
    "fitur_eviden":           ("Verifikasi & Ketelusuran Eviden", "Timeline bukti foto + GPS tiap tahap"),
    "fitur_chat_agent":       ("AI Chat Agent", "Asisten wizard produk & pencari produk"),
    "fitur_ticker_harga":     ("Ticker Harga Market", "Marquee harga komoditas harian di header"),
    "fitur_favorit":          ("Favorit Pembeli", "Simpan penjual/produk favorit (❤)"),
    "fitur_rating":           ("Penilaian Kepuasan 2 Arah", "Skor bintang pembeli ⇄ penjual"),
    "fitur_blockchain":       ("Blockchain & Dompet Crypto", "AGR Coin: dompet, transfer & ledger on-chain"),
    "fitur_pelunasan_manual": ("Pelunasan Manual + Approval", "Upload bukti transfer, approval oleh penjual"),
    "fitur_storage_cloud":    ("Cloud Object Storage & Media", "Direct upload pre-signed URL ke S3/MinIO/Spaces; bucket public/private; validasi magic bytes; CDN/thumbnail Cloudinary/ImageKit"),
}

# default saat kunci belum ada di DB
FEATURE_DEFAULTS = {k: "1" for k in FEATURE_KEYS}
FEATURE_DEFAULTS.update({
    "crypto_auto_settle": "1",      # pembayaran DP/pelunasan otomatis tercatat on-chain
    "crypto_fee_persen": "0.5",     # biaya jaringan per transfer (%)
    "crypto_rate_idr": "1",         # 1 AGR Coin = Rp N
})


def fitur_on(key):
    """Cek status aktif sebuah fitur dari konfigurasi admin."""
    return get_setting(key, FEATURE_DEFAULTS.get(key, "1")) == "1"


import blockchain as _bc
bchain = _bc.BlockchainService(db, User, Pengaturan, get_setting, set_setting,
                               app.config.get("SECRET_KEY") or os.environ.get("AGR_SECRET", "agr-dev-secret"))
app.bchain = bchain


@app.context_processor
def inject_features():
    """Semua template bisa membaca status fitur → navigasi/kartu disembunyikan saat nonaktif."""
    try:
        feats = {k: fitur_on(k) for k in FEATURE_KEYS}
    except Exception:
        feats = {k: True for k in FEATURE_KEYS}
    return {"feat": feats, "feat_meta": FEATURE_KEYS,
            "blockchain_enabled": feats.get("fitur_blockchain", True)}


BIAYA_LABEL = {
    "dp_persen": "Persen DP Booking (%)",
    "biaya_penanganan_persen": "Biaya Penanganan Platform (%)",
    "biaya_tambahan_flat": "Biaya Tambahan Flat per Transaksi (Rp)",
    "biaya_verifikasi": "Biaya Verifikasi Eviden (Rp)",
    "biaya_iklan_produk": "Biaya Iklan/Promosi Produk (Rp/produk)",
    "ongkir_persen_asuransi": "Asuransi Pengiriman (% dari nilai barang)",
    "min_transaksi": "Minimum Nilai Transaksi (Rp)",
    "lelang_biaya_peserta": "Biaya Administrasi Peserta Lelang (Rp/peserta/event)",
    "lelang_biaya_penjual": "Biaya Lelang Penjual (Rp/event)",
}


def get_biaya_settings():
    """Kumpulan pengaturan biaya/DP untuk dashboard admin & penjual."""
    return {k: get_setting(k, d) for k, d in {
        "dp_persen": "20", "biaya_penanganan_persen": "2", "biaya_tambahan_flat": "0",
        "biaya_verifikasi": "5000", "biaya_iklan_produk": "0",
        "ongkir_persen_asuransi": "1", "min_transaksi": "50000",
        "lelang_biaya_peserta": "0", "lelang_biaya_penjual": "0"}.items()}


def fav_state(buyer, seller_id=None, product_id=None):
    """Status favorit pembeli utk penjual/produk tertentu (untuk tombol ♥)."""
    if not buyer or "pembeli" not in buyer.role_list:
        return {"seller": False, "product": False}
    q = Favorite.query.filter_by(buyer_id=buyer.id)
    s = q.filter(Favorite.product_id.is_(None), Favorite.seller_id == seller_id).first() if seller_id else None
    p = q.filter(Favorite.product_id == product_id).first() if product_id else None
    return {"seller": bool(s), "product": bool(p)}


def is_fav_seller(buyer, seller_id):
    return fav_state(buyer, seller_id=seller_id)["seller"]


def is_fav_product(buyer, product_id):
    return fav_state(buyer, product_id=product_id)["product"]


def seller_payment_cfg(u):
    """Konfigurasi metode pembayaran pelunasan DP milik penjual (per-akun)."""
    import json
    raw = get_setting(f"pembayaran_penjual_{u.id}")
    cfg = {"metode_dp": ["Transfer Bank", "QRIS"], "rekening": "", "tujuan_tunai": u.alamat or ""}
    if raw:
        try:
            cfg.update(json.loads(raw))
        except Exception:
            pass
    return cfg


def seller_auction_cfg(u):
    """Preferensi lelang default milik penjual; tarif tetap diatur admin."""
    import json
    cfg = {"syarat_ketentuan": "", "durasi_pembayaran_jam": 24, "jadwal_pengambilan_jam": 0}
    raw = get_setting(f"pengaturan_lelang_penjual_{u.id}")
    if raw:
        try:
            cfg.update(json.loads(raw))
        except (TypeError, ValueError):
            pass
    try:
        cfg["durasi_pembayaran_jam"] = max(1, min(720, int(cfg.get("durasi_pembayaran_jam", 24))))
        cfg["jadwal_pengambilan_jam"] = max(0, min(720, int(cfg.get("jadwal_pengambilan_jam", 0))))
    except (TypeError, ValueError):
        cfg["durasi_pembayaran_jam"], cfg["jadwal_pengambilan_jam"] = 24, 0
    cfg["syarat_ketentuan"] = str(cfg.get("syarat_ketentuan", ""))[:5000]
    return cfg

# ----------------------------------------------------------------------------
# HARGA PASAR (TICKER)
# ----------------------------------------------------------------------------

MARKET_BASE = [
    ("Cabai Merah", "Rp/kg", 42000), ("Bawang Merah", "Rp/kg", 33500), ("Bawang Putih", "Rp/kg", 41000),
    ("Kentang", "Rp/kg", 15500), ("Wortel", "Rp/kg", 18000), ("Tomat", "Rp/kg", 13500),
    ("Kangkung", "Rp/ikat", 5000), ("Bayam", "Rp/ikat", 5000), ("Kol", "Rp/kg", 12000),
    ("Brokoli", "Rp/kg", 28000), ("Terong", "Rp/kg", 11000), ("Timun", "Rp/kg", 9500),
    ("Jagung Manis", "Rp/tongkol", 7500), ("Pisang Ambon", "Rp/kg", 16000), ("Mangga Arummanis", "Rp/kg", 24000),
    ("Jeruk Medan", "Rp/kg", 21000), ("Semangka", "Rp/kg", 8000), ("Nanas Madu", "Rp/butir", 15000),
    ("Pepaya California", "Rp/kg", 12500), ("Buah Naga", "Rp/kg", 19000), ("Alpukat Mentega", "Rp/kg", 32000),
    ("Durian Musang King", "Rp/kg", 95000), ("Manggis", "Rp/kg", 38000), ("Lengkeng", "Rp/kg", 45000),
    ("Kopi Arabika Gayo", "Rp/kg", 95000), ("Kopi Robusta", "Rp/kg", 52000), ("Kakao Biji Kering", "Rp/kg", 48000),
    ("Karet RSS2", "Rp/kg", 18500), ("Sawit TBS", "Rp/kg", 2450), ("Kelapa Butiran", "Rp/butir", 8000),
    ("Gula Kristal", "Rp/kg", 17500), ("Vanili Kering", "Rp/kg", 4500000), ("Lada Putih", "Rp/kg", 120000),
    ("Cengkeh Kering", "Rp/kg", 115000), ("Pala Biji", "Rp/kg", 90000), ("Kayu Manis", "Rp/kg", 55000),
    ("Lele", "Rp/kg", 19500), ("Nila", "Rp/kg", 28000), ("Mas", "Rp/kg", 24000), ("Patin", "Rp/kg", 22000),
    ("Gurame", "Rp/kg", 48000), ("Bandeng", "Rp/kg", 32000), ("Udang Vaname", "Rp/kg", 78000),
    ("Udang Windu", "Rp/kg", 120000), ("Cumi-cumi", "Rp/kg", 65000), ("Kepiting Bakau", "Rp/kg", 85000),
    ("Lobster", "Rp/kg", 240000), ("Kerapu Macan", "Rp/kg", 92000), ("Tuna Sirip Kuning", "Rp/kg", 75000),
    ("Kakap Merah", "Rp/kg", 68000), ("Tenggiri", "Rp/kg", 58000), ("Teri Medan", "Rp/kg", 45000),
    ("Kembung", "Rp/kg", 28000), ("Rumput Laut Cottonii", "Rp/kg kering", 22000),
    ("Sapi Hidup", "Rp/kg HID", 55000), ("Sapi Potong Karkas", "Rp/kg", 120000), ("Kerbau Hidup", "Rp/kg HID", 42000),
    ("Kambing PE", "Rp/ekor", 3200000), ("Kambing Etawa", "Rp/ekor", 4500000), ("Domba Garut", "Rp/ekor", 2800000),
    ("Ayam Broiler Hidup", "Rp/kg", 22000), ("Ayam Kampung", "Rp/ekor", 65000), ("Ayam Karkas", "Rp/kg", 38000),
    ("Telur Ayam Negeri", "Rp/kg", 29000), ("Telur Ayam Kampung", "Rp/butir", 3200), ("Telur Bebek", "Rp/butir", 2800),
    ("Bebek Hidup", "Rp/ekor", 55000), ("Puyuh Pedaging", "Rp/ekor", 12000), ("Madu Hutan", "Rp/ml", 350),
    ("Kelinci Pedaging", "Rp/kg", 45000), ("Susu Sapi Segar", "Rp/liter", 18500), ("Susu Etawa", "Rp/liter", 65000),
]


def ticker_data():
    rows = []
    rnd = random.Random(date.today().toordinal())
    for nama, unit, base in MARKET_BASE:
        drift = rnd.uniform(-0.06, 0.06)
        price = round(base * (1 + drift), -2)
        change = round(drift * 100, 2)
        rows.append({"nama": nama, "unit": unit, "harga": int(price),
                     "perubahan": change, "naik": change >= 0})
    return rows

# ----------------------------------------------------------------------------
# AI CHAT AGENT (rule-based assistant, pluggable ke LLM API eksternal)
# ----------------------------------------------------------------------------

def ai_reply(text, user=None):
    """AI Agent: membantu pengisian informasi produk & pencarian produk."""
    t = (text or "").lower()
    # ---- Intent: input produk ----
    if any(k in t for k in ["jual", "posting produk", "tambah produk", "input produk", "daftar produk"]):
        steps = [
            "🌱 **Wizard Input Produk AGR.ID** — saya bantu langkah demi langkah:",
            "1️⃣ Pilih **kategori**: Pertanian / Perkebunan / Perikanan / Peternakan",
            "2️⃣ Pilih **sub kategori** (mis. Sayuran, Buah-buahan, Air Tawar, Air Laut…)",
            "3️⃣ Ketik **nama produk** — bila belum ada di database, akan otomatis tersimpan ke Database Produk.",
            "4️⃣ Tentukan **jenis/varietas**, **harga per satuan**, dan **stok**.",
            "5️⃣ Unggah **foto produk** + **koordinat GPS** lokasi lahan/kolam/kandang untuk ketelusuran.",
            "6️⃣ Isi **alamat asal**, **deskripsi**, dan **sertifikasi** (organik/halal/SNI).",
            "Silakan buka menu 📦 **Posting Produk** di dashboard penjual, atau balas contoh: "
            "*\"Jual Cabai Merah Keriting Rp45.000/kg stok 200kg dari Brebes\"*",
        ]
        return "\n".join(steps)
    if any(k in t for k in ["cabai", "tomat", "kangkung", "bawang"]):
        return ('✅ Saya kenali ini kategori **Pertanian → Sayuran**. Saran isian formulir:\n'
                '- Kategori: Pertanian | Sub: Sayuran\n- Jenis: pilih varietas (Biasa/Keriting/Rawit)\n'
                '- Harga pasar hari ini: cabai ± Rp42.000/kg — Anda bisa pasang sedikit di bawah pasar agar cepat dapat penawaran.\n'
                '- Jangan lupa lampirkan foto hasil panen + titik GPS lahan untuk badge ✅ Terlacak.')
    if any(k in t for k in ["ikan", "lele", "nila", "gurame", "udang", "bandeng"]):
        return ('🐟 Untuk produk **perikanan**, isi:\n- Kategori: Perikanan → **Air Tawar** (lele/nila/gurame/bandeng) '
                'atau **Air Laut** (udang laut/kerapu/tuna).\n- Satuan umum: kg hidup / kg segar / ekor.\n'
                '- Untuk ikan hidup, tambahkan info media pengiriman (oksigen/puffer) di deskripsi.\n'
                '- Lampirkan foto kolam & koordinat GPS tambak untuk traceability.')
    if any(k in t for k in ["sapi", "kambing", "ayam", "ternak", "domba", "bebek", "unggas"]):
        return ('🐄 Produk **peternakan**: tentukan sub kategori (Sapi & Kerbau / Kambing & Domba / Unggas / Lainnya),\n'
                '- Jenis: ras/strain (Limousin, PE 76, Broiler, KUB…)\n- Kondisi: hidup / karkas / olahan.\n'
                '- Lengkapi sertifikat kesehatan hewan (SKKH) & foto kandang + GPS.\n'
                '- Catatan: produk **Babi** otomatis diberi label ⚠️ Non Halal.')
    if any(k in t for k in ["cari", "beli", "butuh", "harga", "stock", "stok", "termurah"]):
        # intent pencarian produk -> ambil dari DB listing
        q = None
        for kw in ["cari ", "beli ", "butuh "]:
            if kw in t:
                q = text.lower().split(kw)[-1].strip("?.!, ")
                break
        query = Product.query.filter(Product.status == "aktif")
        if q:
            like = f"%{q}%"
            query = query.filter(db.or_(Product.nama_produk.ilike(like),
                                        Product.kategori.ilike(like),
                                        Product.subkategori.ilike(like)))
        results = query.limit(5).all()
        if results:
            lines = [f"🔎 Menemukan {len(results)} produk terkait:", ""]
            for p in results:
                halal = " ⚠️Non Halal" if p.non_halal else ""
                lines.append(f"• **{p.nama_produk}** {p.jenis or ''}{halal} — Rp{int(p.harga):,}/{p.satuan} "
                             f"(stok {p.stok:g} {p.satuan}) oleh {p.seller.nama} | {p.kategori}>{p.subkategori}")
            lines.append("")
            lines.append("Klik kartu produk di halaman 🏪 Marketplace untuk mengajukan **penawaran harga** lalu **booking dengan DP**.")
            return "\n".join(lines)
        return "😕 Produk tersebut belum ditemukan di marketplace. Coba kata kunci lain, atau minta penjual langganan Anda mem-postingnya."
    if "dp" in t or "booking" in t:
        pct = get_setting("dp_persen", "20")
        fee = get_setting("biaya_penanganan_persen", "2")
        return (f"💳 Mekanisme booking AGR.ID:\n- Penawaran Anda diterima penjual → lakukan **booking dengan DP {pct}%** "
                f"sebagai pengikat via payment gateway (QRIS/VA/e-wallet).\n- Sisanya dibayar saat barang dikirim/diterima.\n"
                f"- Biaya penanganan platform {fee}% termasuk dalam rincian pembayaran.\n- Jadwal pengiriman & tracking ekspedisi "
                f"dapat dipantau di dashboard, dengan bukti eviden foto + GPS tiap tahap.")
    if "halal" in t:
        return "☪️ Filter ketelusuran: hanya produk **Peternakan → Babi** yang ditandai ⚠️ **Non Halal**. Semua kategori lain tersedia tanpa label tersebut dan dapat difilter di halaman Marketplace."
    if "ekspedisi" in t or "kirim" in t or "ongkir" in t:
        eks = Ekspedisi.query.filter_by(enabled=True).all()
        names = ", ".join(e.nama for e in eks) or "belum ada mitra aktif"
        return f"🚚 Mitra ekspedisi aktif di AGR.ID: {names}. Ongkir dihitung otomatis per kg/kubikasi saat checkout booking."
    if any(k in t for k in ["halo", "hai", "assalamualaikum", "selamat"]):
        return ("👋 Halo! Saya **AGR Assistant** 🌾 — asisten AI marketplace AGR.ID. Saya bisa:\n"
                "1. Membantu Anda **mengisi informasi produk** untuk dijual (ketik: *cara jual produk*)\n"
                "2. **Mencari produk** yang Anda butuhkan (ketik: *cari lele* / *beli kopi gayo*)\n"
                "3. Menjelaskan **sistem penawaran, DP booking & pengiriman** (ketik: *cara booking*)")
    if any(k in t for k in ["crypto", "blockchain", "agr coin", "dompet", "wallet", "on-chain", "onchain"]):
        st = bchain.stats()
        return (f"⛓️ **Blockchain AGR Coin** — status jaringan: {'AKTIF' if st['enabled'] else 'NONAKTIF'}\n"
                f"- Blok terakhir: #{st['last_index']} · total {st['tx_total']} transaksi on-chain\n"
                f"- Integritas rantai: {'✔ terverifikasi' if st['verified'] else '✖ perlu audit'}\n"
                f"- Kurs settlement: 1 AGR = Rp{int(st['rate']):,} · biaya jaringan {get_setting('crypto_fee_persen','0.5')}%\n"
                "Setiap pembayaran DP/pelunasan otomatis didistribusikan antar **dompet crypto** penjual-pembeli "
                "dan tercatat permanen di ledger (bukti ketelusuran anti-sengketa).\n"
                "Buka menu 🪙 **Dompet Crypto** di dashboard Anda untuk melihat alamat AGR1…, saldo, riwayat & transfer manual.")
    return ("Saya 🤖 AGR Assistant. Contoh perintah:\n"
            "- \"cara jual cabai\" → pandu wizard input produk\n"
            "- \"cari ikan gurame\" → cari listing pembeli-ready\n"
            "- \"sistem DP booking\" → penjelasan transaksi\n"
            "- \"dompet crypto\" → status blockchain & AGR Coin\n"
            "- \"daftar ekspedisi\" → mitra kirim aktif")

# ----------------------------------------------------------------------------
# AUTH HELPERS
# ----------------------------------------------------------------------------

def current_user():
    uid = session.get("uid")
    return User.query.get(uid) if uid else None


WIB = ZoneInfo("Asia/Jakarta")


def parse_wib_deadline(value):
    """Parse input datetime-local dari seller (WIB) ke UTC naive untuk DB."""
    if not value:
        return None
    try:
        local_dt = datetime.strptime(value, "%Y-%m-%dT%H:%M").replace(tzinfo=WIB)
        return local_dt.astimezone(timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


@app.template_filter("wib")
def wibfmt(value):
    if not value:
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(WIB).strftime("%d %b %Y %H:%M WIB")


@app.before_request
def expire_unpaid_agreements():
    """Tutup kesepakatan DP yang tenggatnya lewat pada request berikutnya."""
    now = datetime.utcnow()
    due = Offer.query.filter(
        Offer.status.in_(("diterima", "booking")),
        Offer.batas_pembayaran.isnot(None),
        Offer.batas_pembayaran <= now,
    ).all()
    changed = False
    for offer in due:
        if offer.status == "booking":
            pending_bookings = Booking.query.filter_by(offer_id=offer.id, status="dp_pending").all()
            if not pending_bookings:
                continue
            for booking in pending_bookings:
                booking.status = "batal"
        offer.status = "kedaluwarsa"
        changed = True
    if changed:
        db.session.commit()


@app.before_request
def refresh_auction_event_statuses():
    """Sinkronkan akhir lelang dan tenggat pembayaran pemenang dengan UTC."""
    now = datetime.utcnow()
    events = LelangEvent.query.filter(LelangEvent.status.in_(
        ("terjadwal", "berlangsung", "menunggu_pembayaran_pemenang"))).all()
    changed = False
    for event in events:
        if event.status == "menunggu_pembayaran_pemenang":
            if event.batas_bayar_pemenang and event.batas_bayar_pemenang <= now:
                event.status = "tenggat_pemenang_lewat"
                if event.penetapan_aktif and event.penetapan_aktif.status == "menunggu":
                    event.penetapan_aktif.status = "kedaluwarsa"
                changed = True
            continue
        target = "berlangsung" if event.mulai <= now else "terjadwal"
        if event.selesai <= now:
            if event.peringkat_tawaran:
                winning_bid = event.peringkat_tawaran[0]
                event.pemenang_id = winning_bid.buyer_id
                event.harga_pemenang = winning_bid.nominal
                event.pemenang_bayar_lunas = False
                if not event.batas_bayar_pemenang:
                    event.batas_bayar_pemenang = now + timedelta(hours=24)
                if not event.penetapan_aktif:
                    event.awards.append(LelangAward(
                        buyer_id=winning_bid.buyer_id, nominal=winning_bid.nominal,
                        batas_bayar=event.batas_bayar_pemenang, status="menunggu"))
                target = "tenggat_pemenang_lewat" if (
                    event.batas_bayar_pemenang and event.batas_bayar_pemenang <= now
                ) else "menunggu_pembayaran_pemenang"
                if target == "tenggat_pemenang_lewat" and event.penetapan_aktif:
                    event.penetapan_aktif.status = "kedaluwarsa"
            else:
                target = "selesai"
        if event.status != target:
            event.status = target
            changed = True
            if target == "selesai" and not event.peringkat_tawaran:
                for item in event.items:
                    if item.product and item.product.status == "lelang":
                        item.product.status = "aktif"
    if changed:
        db.session.commit()


def login_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            u = current_user()
            if not u:
                flash("Silakan login terlebih dahulu.", "warning")
                return redirect(url_for("login"))
            if roles and u.active_role not in roles:
                flash("Akses ditolak untuk role Anda.", "danger")
                return redirect(url_for("login"))
            return fn(*a, **kw)
        return wrapper
    return deco

def feature_required(key):
    """Guard: tolak akses route bila fitur terkait dinonaktifkan di konfigurasi admin."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not fitur_on(key):
                flash(f"Fitur \u201c{FEATURE_KEYS[key][0]}\u201d sedang dinonaktifkan pada konfigurasi admin.", "warning")
                return redirect(url_for("home"))
            return fn(*a, **kw)
        return wrapper
    return deco


# ----------------------------------------------------------------------------
# ROUTES: PUBLIC
# ----------------------------------------------------------------------------

@app.route("/")
def home():
    prods = Product.query.filter_by(status="aktif").order_by(Product.created_at.desc()).limit(8).all()
    return render_template("home.html", categories=KATEGORI, products=prods,
                           ticker=ticker_data(), user=current_user(),
                           seller_rating_cache=seller_rating_cache(prods))


@app.route("/marketplace")
@feature_required("fitur_marketplace")
def marketplace():
    q = request.args.get("q", "").strip()
    kat = request.args.get("kategori", "")
    sub = request.args.get("subkategori", "")
    hide_nonhalal = request.args.get("hide_nonhalal") == "1"
    query = Product.query.filter_by(status="aktif")
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Product.nama_produk.ilike(like), Product.jenis.ilike(like),
                                    Product.deskripsi.ilike(like)))
    if kat:
        query = query.filter(Product.kategori == kat)
    if sub:
        query = query.filter(Product.subkategori == sub)
    if hide_nonhalal:
        query = query.filter(Product.non_halal.is_(False))
    prods = query.order_by(Product.created_at.desc()).all()
    subs = MASTER_PRODUK.get(kat, {}).get("subkategori", []) if kat else []
    cu = current_user()
    fav_seller_ids = set()
    fav_prod_ids = set()
    if cu and cu.active_role == "pembeli":
        for f in Favorite.query.filter_by(buyer_id=cu.id).all():
            if f.product_id is None:
                fav_seller_ids.add(f.seller_id)
            else:
                fav_prod_ids.add(f.product_id)
    return render_template("marketplace.html", products=prods, categories=KATEGORI,
                           subs=subs, q=q, kat=kat, sub=sub, hide_nonhalal=hide_nonhalal,
                           ticker=ticker_data(), user=cu,
                           fav_sellers=fav_seller_ids, fav_products=fav_prod_ids,
                           seller_rating_cache=seller_rating_cache(prods))


@app.route("/lelang")
def auction_list():
    events = LelangEvent.query.filter(LelangEvent.status.in_(
        ("terjadwal", "berlangsung", "menunggu_pembayaran_pemenang", "tenggat_pemenang_lewat", "selesai"))).order_by(
        LelangEvent.mulai.desc(), LelangEvent.created_at.desc()).all()
    cu = current_user()
    joined_ids = set()
    if cu and cu.active_role == "pembeli":
        joined_ids = {r.event_id for r in LelangParticipant.query.filter_by(buyer_id=cu.id).all()}
    return render_template("auction_list.html", events=events, joined_ids=joined_ids,
                           user=cu, ticker=ticker_data())


@app.route("/lelang/buat", methods=["GET", "POST"])
@login_required("penjual")
def create_auction_event():
    u = current_user()
    auction_cfg = seller_auction_cfg(u)
    seller_products = Product.query.filter_by(seller_id=u.id, status="aktif").filter(Product.stok > 0).order_by(Product.kategori, Product.nama_produk).all()
    if request.method == "POST":
        judul = request.form.get("judul", "").strip()
        deskripsi = request.form.get("deskripsi", "").strip()
        syarat_ketentuan = request.form.get("syarat_ketentuan", "").strip()
        foto = request.form.get("foto", "").strip()
        alamat = request.form.get("alamat_lokasi", "").strip()
        mulai = parse_wib_deadline(request.form.get("mulai"))
        selesai = parse_wib_deadline(request.form.get("selesai"))
        batas_bayar_pemenang = parse_wib_deadline(request.form.get("batas_bayar_pemenang"))
        jadwal_pengambilan_raw = request.form.get("jadwal_pengambilan", "").strip()
        jadwal_pengambilan = parse_wib_deadline(jadwal_pengambilan_raw) if jadwal_pengambilan_raw else None
        try:
            lat = float(request.form.get("lat", ""))
            lng = float(request.form.get("lng", ""))
            ids = list(dict.fromkeys(int(v) for v in request.form.getlist("product_ids")))
        except (TypeError, ValueError):
            lat, lng, ids = None, None, []
        harga_awal = _positive_price(request.form.get("harga_awal"))
        now = datetime.utcnow()
        if (not judul or len(judul) > 160 or not deskripsi or not syarat_ketentuan
                or len(syarat_ketentuan) > 5000 or not alamat or len(alamat) > 255):
            flash("Judul, deskripsi, syarat lelang, dan alamat lokasi wajib diisi.", "danger")
        elif not foto or not foto.startswith(("object://", "cloud://", "https://")):
            flash("Unggah foto pendukung event lelang terlebih dahulu.", "danger")
        elif lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
            flash("Koordinat GPS harus valid (latitude -90…90, longitude -180…180).", "danger")
        elif (not mulai or not selesai or not batas_bayar_pemenang or mulai < now
              or selesai <= mulai or batas_bayar_pemenang <= selesai):
            flash("Jadwal lelang tidak valid. Tetapkan waktu mulai, waktu selesai, dan tenggat pembayaran pemenang setelah lelang berakhir.", "danger")
        elif jadwal_pengambilan and jadwal_pengambilan <= selesai:
            flash("Jadwal pengambilan harus sesudah lelang berakhir.", "danger")
        elif not ids or len(ids) > 100:
            flash("Pilih minimal satu dan maksimal 100 produk untuk paket lelang.", "danger")
        else:
            selected = Product.query.filter(Product.seller_id == u.id, Product.status == "aktif",
                                            Product.stok > 0, Product.id.in_(ids)).all()
            if len(selected) != len(ids):
                flash("Daftar produk lelang tidak valid. Pilih produk aktif milik Anda dengan stok tersedia.", "danger")
            elif not harga_awal:
                flash("Harga pembukaan lelang harus lebih dari nol.", "danger")
            else:
                event = LelangEvent(seller_id=u.id, judul=judul, deskripsi=deskripsi,
                                    syarat_ketentuan=syarat_ketentuan, foto=foto,
                                    alamat_lokasi=alamat, lat=lat, lng=lng, mulai=mulai, selesai=selesai,
                                    batas_bayar_pemenang=batas_bayar_pemenang,
                                    jadwal_pengambilan=jadwal_pengambilan,
                                    harga_awal=harga_awal, status="diajukan")
                for p in selected:
                    event.items.append(LelangItem(product_id=p.id, nama_produk=p.nama_produk,
                                                  kategori=p.kategori, subkategori=p.subkategori,
                                                  jumlah=p.stok, satuan=p.satuan or "unit",
                                                  harga_listing=p.harga or 0))
                    p.status = "lelang"  # stok paket tidak dijual ulang lewat marketplace selama/selepas lelang berpemenang
                db.session.add(event)
                db.session.commit()
                audit_current("event_lelang_dibuat", "lelang_events", event.id,
                              f"{len(selected)} produk; mulai {mulai.isoformat()} UTC")
                flash("Pengajuan event lelang terkirim dan menunggu persetujuan admin.", "success")
                return redirect(url_for("auction_detail", event_id=event.id))
    return render_template("auction_form.html", products=seller_products, user=u, ticker=ticker_data(),
                           minimum_start=(datetime.now(WIB) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M"),
                           default_payment_deadline=(datetime.now(WIB) + timedelta(hours=auction_cfg["durasi_pembayaran_jam"])).strftime("%Y-%m-%dT%H:%M"),
                           auction_cfg=auction_cfg)


@app.route("/admin/lelang/<int:event_id>/setujui", methods=["POST"])
@login_required("admin")
def approve_auction_event(event_id):
    event = LelangEvent.query.get_or_404(event_id)
    if event.status != "diajukan":
        flash("Hanya pengajuan event yang menunggu tinjauan yang dapat disetujui.", "warning")
    elif event.selesai <= datetime.utcnow():
        flash("Jadwal lelang sudah lewat. Minta penjual mengajukan event dengan jadwal baru.", "danger")
    else:
        biaya_peserta = _nonnegative_amount(get_setting("lelang_biaya_peserta", "0"))
        biaya_penjual = _nonnegative_amount(get_setting("lelang_biaya_penjual", "0"))
        if biaya_peserta is None or biaya_penjual is None or biaya_peserta <= 0 or biaya_penjual <= 0:
            flash("Atur biaya administrasi peserta dan biaya penjual di pengaturan admin dengan nilai lebih dari nol sebelum menyetujui event.", "danger")
        else:
            event.biaya_peserta = biaya_peserta
            event.biaya_penjual = biaya_penjual
            event.disetujui_pada = datetime.utcnow()
            event.catatan_admin = request.form.get("catatan_admin", "").strip()[:1000] or None
            event.status = "menunggu_biaya_penjual" if biaya_penjual > 0 else "terjadwal"
            event.biaya_penjual_lunas = biaya_penjual <= 0
            db.session.commit()
            audit_current("event_lelang_disetujui", "lelang_events", event.id,
                          f"biaya peserta Rp{biaya_peserta:g}; biaya penjual Rp{biaya_penjual:g}")
            flash("Pengajuan disetujui. Penjual harus melunasi biaya event sebelum event ditayangkan." if biaya_penjual > 0
                  else "Pengajuan disetujui dan event ditayangkan.", "success")
    return redirect(url_for("dashboard_admin") + "#tAuctionAdmin")


@app.route("/admin/lelang/<int:event_id>/tolak", methods=["POST"])
@login_required("admin")
def reject_auction_event(event_id):
    event = LelangEvent.query.get_or_404(event_id)
    if event.status != "diajukan":
        flash("Hanya pengajuan event yang menunggu tinjauan yang dapat ditolak.", "warning")
    else:
        event.status = "ditolak"
        event.catatan_admin = request.form.get("catatan_admin", "").strip()[:1000] or "Pengajuan ditolak admin."
        for item in event.items:
            if item.product and item.product.status == "lelang":
                item.product.status = "aktif"
        db.session.commit()
        audit_current("event_lelang_ditolak", "lelang_events", event.id, event.catatan_admin)
        flash("Pengajuan event ditolak dan stok produk dikembalikan ke marketplace.", "info")
    return redirect(url_for("dashboard_admin") + "#tAuctionAdmin")


@app.route("/lelang/<int:event_id>")
def auction_detail(event_id):
    event = LelangEvent.query.get_or_404(event_id)
    cu = current_user()
    if event.status in ("diajukan", "ditolak", "menunggu_biaya_penjual") and not (
        cu and (cu.id == event.seller_id or cu.active_role == "admin")
    ):
        abort(404)
    participant = LelangParticipant.query.filter_by(event_id=event.id, buyer_id=cu.id).first() if cu and cu.active_role == "pembeli" else None
    seller_view = bool(cu and cu.active_role == "penjual" and cu.id == event.seller_id)
    highest = event.tawaran_tertinggi
    winner = event.pemenang or (highest.buyer if highest and event.status == "selesai" else None)
    is_winner = bool(winner and cu and cu.active_role == "pembeli" and winner.id == cu.id and
                     event.status in ("menunggu_pembayaran_pemenang", "tenggat_pemenang_lewat", "selesai"))
    winner_price = event.harga_pemenang or (highest.nominal if highest else 0)
    next_bidder_candidates = [bid for bid in event.peringkat_tawaran if bid.buyer_id != event.pemenang_id]
    return render_template("auction_detail.html", event=event, user=cu, participant=participant,
                           highest=highest, winner=winner, seller_view=seller_view, is_winner=is_winner,
                           admin_view=bool(cu and cu.active_role == "admin"),
                           next_bidder_candidates=next_bidder_candidates,
                           default_next_payment_deadline=(datetime.now(WIB) + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M"),
                           winner_price=winner_price,
                           minimum_bid=int(highest.nominal if highest else event.harga_awal) + 1,
                           bid_history=sorted(event.bids, key=lambda b: (b.nominal, -b.id), reverse=True),
                           ticker=ticker_data())


@app.route("/lelang/<int:event_id>/hasil")
def auction_results(event_id):
    event = LelangEvent.query.get_or_404(event_id)
    cu = current_user()
    if event.status in ("diajukan", "ditolak", "menunggu_biaya_penjual") and not (
        cu and (cu.id == event.seller_id or cu.active_role == "admin")
    ):
        abort(404)
    bids = sorted(event.bids, key=lambda bid: (bid.nominal, -bid.id), reverse=True)
    highest = event.tawaran_tertinggi
    return jsonify({
        "status": event.status,
        "bids": [{"id": bid.id, "buyer": bid.buyer.nama, "nominal": bid.nominal,
                  "catatan": bid.catatan or "", "created_at": wibfmt(bid.created_at)} for bid in bids],
        "highest": {"nominal": highest.nominal, "buyer": highest.buyer.nama} if highest else None,
        "minimum_bid": int(highest.nominal if highest else event.harga_awal) + 1,
    })


@app.route("/lelang/<int:event_id>/ikut", methods=["POST"])
@login_required("pembeli")
def join_auction(event_id):
    event = LelangEvent.query.get_or_404(event_id)
    now = datetime.utcnow()
    if event.status not in ("terjadwal", "berlangsung") or event.selesai <= now:
        flash("Pendaftaran peserta untuk event ini sudah ditutup.", "warning")
    elif not request.form.get("setuju_syarat"):
        flash("Anda harus menyetujui syarat dan ketentuan event sebelum mendaftar.", "warning")
    elif not LelangParticipant.query.filter_by(event_id=event.id, buyer_id=current_user().id).first():
        fee = max(0, event.biaya_peserta or 0)
        db.session.add(LelangParticipant(event_id=event.id, buyer_id=current_user().id,
                                         biaya_administrasi=fee, biaya_lunas=fee == 0,
                                         dibayar_pada=now if fee == 0 else None))
        db.session.commit()
        audit_current("pembeli_mendaftar_lelang", "lelang_events", event.id,
                      f"setuju syarat; biaya administrasi Rp{fee:g}")
        flash("Pendaftaran tercatat. Lunasi biaya administrasi sebelum mengajukan tawaran." if fee else
              "Pendaftaran dan persetujuan syarat berhasil. Anda dapat menawar saat lelang berlangsung.",
              "warning" if fee else "success")
    else:
        flash("Anda sudah terdaftar sebagai peserta event ini.", "info")
    return redirect(url_for("auction_detail", event_id=event.id))


@app.route("/lelang/<int:event_id>/biaya-penjual", methods=["POST"])
@login_required("penjual")
def pay_auction_seller_fee(event_id):
    event = LelangEvent.query.get_or_404(event_id)
    if event.seller_id != current_user().id or event.status != "menunggu_biaya_penjual":
        flash("Pembayaran biaya event ini tidak tersedia.", "warning")
    elif event.selesai <= datetime.utcnow():
        flash("Jadwal event sudah lewat. Hubungi admin untuk mengajukan jadwal baru.", "danger")
    else:
        method = request.form.get("metode", "qris").strip().lower()
        if method not in {"qris", "virtual_account", "ewallet", "bank_transfer"}:
            method = "qris"
        ref = "AUC-SELLER-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + str(random.randint(1000, 9999))
        event.biaya_penjual_lunas = True
        event.ref_biaya_penjual = f"{ref}:{method}"
        now = datetime.utcnow()
        event.status = "berlangsung" if event.mulai <= now else "terjadwal"
        db.session.commit()
        audit_current("biaya_lelang_penjual_dibayar", "lelang_events", event.id, f"Rp{event.biaya_penjual:g}; ref {ref}")
        flash(f"Biaya event dicatat lunas (simulasi payment gateway), ref {ref}. Event kini tayang.", "success")
    return redirect(url_for("auction_detail", event_id=event.id))


@app.route("/lelang/<int:event_id>/biaya-peserta", methods=["POST"])
@login_required("pembeli")
def pay_auction_participant_fee(event_id):
    event = LelangEvent.query.get_or_404(event_id)
    participant = LelangParticipant.query.filter_by(event_id=event.id, buyer_id=current_user().id).first()
    if not participant:
        flash("Daftar sebagai peserta dan setujui syarat event terlebih dahulu.", "warning")
    elif participant.biaya_lunas:
        flash("Biaya administrasi event sudah lunas.", "info")
    elif event.status not in ("terjadwal", "berlangsung") or event.selesai <= datetime.utcnow():
        flash("Pembayaran peserta untuk event ini sudah ditutup.", "warning")
    else:
        method = request.form.get("metode", "qris").strip().lower()
        if method not in {"qris", "virtual_account", "ewallet", "bank_transfer"}:
            method = "qris"
        ref = "AUC-BUYER-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + str(random.randint(1000, 9999))
        participant.biaya_lunas = True
        participant.ref_pembayaran = f"{ref}:{method}"
        participant.dibayar_pada = datetime.utcnow()
        db.session.commit()
        audit_current("biaya_administrasi_lelang_dibayar", "lelang_events", event.id,
                      f"pembeli #{current_user().id}; Rp{participant.biaya_administrasi:g}; ref {ref}")
        flash(f"Biaya administrasi dicatat lunas (simulasi payment gateway), ref {ref}.", "success")
    return redirect(url_for("auction_detail", event_id=event.id))


@app.route("/kalender")
@login_required()
def calendar_page():
    u = current_user()
    entries = []
    dashboard_endpoint = {"penjual": "dashboard_seller", "pembeli": "dashboard_buyer"}.get(u.active_role, "dashboard_admin")
    dashboard_url = url_for(dashboard_endpoint)

    def add_entry(when, kind, title, description="", location="", event_url=None):
        if when:
            entries.append({"when": when, "kind": kind, "title": title,
                            "description": description, "location": location, "url": event_url})

    participant_rows = LelangParticipant.query.filter_by(buyer_id=u.id).all() if u.active_role == "pembeli" else []
    joined_event_ids = {row.event_id for row in participant_rows}
    if u.active_role == "penjual":
        auctions = LelangEvent.query.filter_by(seller_id=u.id).all()
    elif u.active_role == "pembeli":
        auctions = LelangEvent.query.filter(LelangEvent.id.in_(joined_event_ids or [-1])).all()
    else:
        auctions = LelangEvent.query.all()

    for event in auctions:
        event_url = url_for("auction_detail", event_id=event.id)
        add_entry(event.mulai, "Lelang", f"Mulai lelang: {event.judul}",
                  f"Status: {event.status.replace('_', ' ')}", event.alamat_lokasi, event_url)
        add_entry(event.selesai, "Lelang", f"Penawaran ditutup: {event.judul}",
                  f"Status: {event.status.replace('_', ' ')}", event.alamat_lokasi, event_url)
        if event.jadwal_pengambilan:
            add_entry(event.jadwal_pengambilan, "Pengambilan", f"Pengambilan paket lelang: {event.judul}",
                      "Jadwal pengambilan yang ditetapkan penjual", event.alamat_lokasi, event_url)
        for award in event.awards:
            if u.active_role == "admin" or u.id in (event.seller_id, award.buyer_id):
                add_entry(award.ditetapkan_pada, "Hasil lelang", f"Pemenang ditetapkan: {event.judul}",
                          f"{award.buyer.nama} · Rp{award.nominal:,.0f}", event.alamat_lokasi, event_url)
                add_entry(award.batas_bayar, "Tenggat pembayaran", f"Batas pembayaran pemenang: {event.judul}",
                          f"{award.buyer.nama} · status {award.status}", event.alamat_lokasi, event_url)
                if award.dibayar_pada:
                    add_entry(award.dibayar_pada, "Pembelian lelang", f"Pembayaran pemenang: {event.judul}",
                              f"{award.buyer.nama} · Rp{award.nominal:,.0f} · lunas", event.alamat_lokasi, event_url)
        for registration in event.participants:
            if u.active_role == "admin" or u.id == event.seller_id or registration.buyer_id == u.id:
                add_entry(registration.created_at, "Pendaftaran lelang", f"Pendaftaran peserta: {event.judul}",
                          f"{registration.buyer.nama} · biaya administrasi {'lunas' if registration.biaya_lunas else 'menunggu pembayaran'}",
                          event.alamat_lokasi, event_url)
        for bid in event.bids:
            if u.active_role == "admin" or u.id == event.seller_id or bid.buyer_id == u.id:
                who = "Anda" if bid.buyer_id == u.id else bid.buyer.nama
                add_entry(bid.created_at, "Penawaran", f"Penawaran lelang: {event.judul}",
                          f"{who} · Rp{bid.nominal:,.0f}", event.alamat_lokasi, event_url)

    bookings_query = Booking.query.join(Offer, Booking.offer_id == Offer.id)
    if u.active_role == "pembeli":
        bookings_query = bookings_query.filter(Offer.buyer_id == u.id)
    elif u.active_role == "penjual":
        bookings_query = bookings_query.join(Product, Offer.product_id == Product.id).filter(Product.seller_id == u.id)
    for booking in bookings_query.all():
        offer = booking.offer
        seller = offer.product.seller
        description = f"{offer.product.nama_produk} · pembeli {offer.buyer.nama} · status {booking.status.replace('_', ' ')}"
        add_entry(booking.created_at, "Pemesanan", f"Pemesanan #{booking.id}: {offer.product.nama_produk}",
                  description, seller.alamat if not booking.ekspedisi_id else "", dashboard_url)
        if booking.jadwal_kirim:
            shipment_date = datetime.combine(booking.jadwal_kirim, datetime.min.time()).replace(tzinfo=WIB)
            activity = "Pengiriman" if booking.ekspedisi_id else "Pengambilan"
            add_entry(shipment_date, activity, f"Jadwal {activity.lower()}: {offer.product.nama_produk}",
                      f"Pemesanan #{booking.id} · {'ekspedisi ' + booking.ekspedisi.nama if booking.ekspedisi else 'pengambilan langsung'}",
                      seller.alamat, dashboard_url)

    transactions_query = Transaksi.query
    if u.active_role == "pembeli":
        transactions_query = transactions_query.filter_by(buyer_id=u.id)
    elif u.active_role == "penjual":
        transactions_query = transactions_query.filter_by(seller_id=u.id)
    for transaction in transactions_query.all():
        other_party = transaction.seller.nama if u.active_role == "pembeli" else transaction.buyer.nama
        add_entry(transaction.created_at, "Pembelian", f"Pembelian #{transaction.id}: {transaction.product_name}",
                  f"{(transaction.qty or 0):g} unit · Rp{transaction.nilai:,.0f} · {transaction.status} · {'pihak terkait: ' + other_party if u.active_role != 'admin' else ''}",
                  "", dashboard_url)

    entries.sort(key=lambda row: row["when"])
    return render_template("calendar.html", user=u, entries=entries, ticker=ticker_data())


@app.route("/lelang/<int:event_id>/bayar-pemenang", methods=["POST"])
@login_required("pembeli")
def pay_auction_winning_bid(event_id):
    event = LelangEvent.query.get_or_404(event_id)
    now = datetime.utcnow()
    if (event.pemenang_id != current_user().id or event.status != "menunggu_pembayaran_pemenang"
            or event.pemenang_bayar_lunas):
        flash("Pembayaran ini hanya tersedia untuk pemenang aktif event.", "warning")
    elif not event.batas_bayar_pemenang or event.batas_bayar_pemenang <= now:
        event.status = "tenggat_pemenang_lewat"
        if event.penetapan_aktif and event.penetapan_aktif.status == "menunggu":
            event.penetapan_aktif.status = "kedaluwarsa"
        db.session.commit()
        flash("Batas pembayaran sudah lewat. Penjual akan memilih penawar berikutnya atau membatalkan lelang.", "danger")
    else:
        method = request.form.get("metode", "qris").strip().lower()
        if method not in {"qris", "virtual_account", "ewallet", "bank_transfer"}:
            method = "qris"
        ref = "AUC-WINNER-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + str(random.randint(1000, 9999))
        event.pemenang_bayar_lunas = True
        event.ref_bayar_pemenang = f"{ref}:{method}"
        event.status = "selesai"
        if event.penetapan_aktif:
            event.penetapan_aktif.status = "lunas"
            event.penetapan_aktif.ref_pembayaran = event.ref_bayar_pemenang
            event.penetapan_aktif.dibayar_pada = now
        db.session.commit()
        audit_current("pemenang_lelang_membayar", "lelang_events", event.id,
                      f"Rp{event.harga_pemenang:g}; ref {ref}")
        flash(f"Pembayaran pemenang dicatat lunas (simulasi payment gateway), ref {ref}.", "success")
    return redirect(url_for("auction_detail", event_id=event.id))


@app.route("/lelang/<int:event_id>/pilih-penawar-berikutnya", methods=["POST"])
@login_required("penjual")
def select_next_auction_bidder(event_id):
    event = LelangEvent.query.get_or_404(event_id)
    if event.seller_id != current_user().id or event.status != "tenggat_pemenang_lewat":
        flash("Pemilihan penawar berikutnya hanya tersedia untuk event milik Anda yang tenggat pembayarannya terlewat.", "warning")
    else:
        try:
            requested_buyer_id = int(request.form.get("buyer_id", ""))
        except (TypeError, ValueError):
            requested_buyer_id = None
        next_bid = next((bid for bid in event.peringkat_tawaran
                         if bid.buyer_id == requested_buyer_id and bid.buyer_id != event.pemenang_id), None)
        new_deadline = parse_wib_deadline(request.form.get("batas_bayar_pemenang"))
        if not next_bid:
            flash("Pilih peserta lain yang sudah menawar untuk menetapkan pemenang pengganti.", "warning")
        elif not new_deadline or new_deadline <= datetime.utcnow():
            flash("Tentukan batas pembayaran baru di masa depan untuk penawar berikutnya.", "danger")
        else:
            event.pemenang_id = next_bid.buyer_id
            event.harga_pemenang = next_bid.nominal
            event.batas_bayar_pemenang = new_deadline
            event.pemenang_bayar_lunas = False
            event.ref_bayar_pemenang = None
            event.status = "menunggu_pembayaran_pemenang"
            event.awards.append(LelangAward(buyer_id=next_bid.buyer_id, nominal=next_bid.nominal,
                                            batas_bayar=new_deadline, status="menunggu"))
            db.session.commit()
            audit_current("penawar_lelang_berikutnya_dipilih", "lelang_events", event.id,
                          f"pembeli #{next_bid.buyer_id}; Rp{next_bid.nominal:g}; tenggat {new_deadline.isoformat()} UTC")
            flash(f"Penawar berikutnya, {next_bid.buyer.nama}, dipilih sebagai pemenang baru.", "success")
    return redirect(url_for("auction_detail", event_id=event.id))


@app.route("/lelang/<int:event_id>/batalkan-setelah-tenggat", methods=["POST"])
@login_required("penjual")
def cancel_timed_out_auction(event_id):
    event = LelangEvent.query.get_or_404(event_id)
    if event.seller_id != current_user().id or event.status != "tenggat_pemenang_lewat":
        flash("Lelang hanya dapat dibatalkan dari alur tindak lanjut tenggat pemenang milik Anda.", "warning")
    else:
        event.status = "dibatalkan"
        if event.penetapan_aktif and event.penetapan_aktif.status == "kedaluwarsa":
            event.penetapan_aktif.status = "dibatalkan"
        for item in event.items:
            if item.product and item.product.status == "lelang":
                item.product.status = "aktif"
        db.session.commit()
        audit_current("event_lelang_dibatalkan_tenggat_pemenang", "lelang_events", event.id,
                      "pemenang tidak membayar sebelum tenggat; stok dikembalikan")
        flash("Lelang dibatalkan dan stok paket dikembalikan ke marketplace.", "info")
    return redirect(url_for("auction_detail", event_id=event.id))


@app.route("/lelang/<int:event_id>/batal", methods=["POST"])
@login_required("penjual")
def cancel_auction_event(event_id):
    event = LelangEvent.query.get_or_404(event_id)
    if event.seller_id != current_user().id:
        flash("Tidak berwenang.", "danger")
    elif event.status not in ("diajukan", "menunggu_biaya_penjual", "terjadwal") or event.bids:
        flash("Event hanya dapat dibatalkan sebelum mulai dan sebelum ada tawaran.", "warning")
    else:
        event.status = "dibatalkan"
        for item in event.items:
            if item.product and item.product.status == "lelang":
                item.product.status = "aktif"
        db.session.commit()
        audit_current("event_lelang_dibatalkan", "lelang_events", event.id, "stok paket dikembalikan ke marketplace")
        flash("Event dibatalkan dan stok produk dikembalikan ke marketplace.", "info")
    return redirect(url_for("auction_detail", event_id=event.id))


@app.route("/lelang/<int:event_id>/tawar", methods=["POST"])
@login_required("pembeli")
def bid_auction(event_id):
    event = LelangEvent.query.get_or_404(event_id)
    now = datetime.utcnow()
    participant = LelangParticipant.query.filter_by(event_id=event.id, buyer_id=current_user().id).first()
    if not participant:
        flash("Daftar sebagai peserta dan setujui syarat lelang sebelum menawar.", "warning")
    elif not participant.biaya_lunas:
        flash("Lunasi biaya administrasi peserta sebelum menawar.", "warning")
    elif event.status != "berlangsung" or not (event.mulai <= now < event.selesai):
        flash("Penawaran hanya dapat dikirim selama event berlangsung.", "warning")
    else:
        amount = _positive_price(request.form.get("nominal"))
        highest = event.tawaran_tertinggi
        minimum = highest.nominal if highest else event.harga_awal
        if amount is None or amount <= minimum:
            flash(f"Tawaran harus lebih tinggi dari Rp{int(minimum):,}.".replace(",", "."), "danger")
        else:
            db.session.add(LelangBid(event_id=event.id, buyer_id=current_user().id,
                                     nominal=amount, catatan=request.form.get("catatan", "").strip()[:255]))
            db.session.commit()
            audit_current("pembeli_menawar_lelang", "lelang_events", event.id, f"tawaran Rp{amount:g}")
            flash("Tawaran lelang berhasil dikirim.", "success")
    return redirect(url_for("auction_detail", event_id=event.id))


@app.route("/produk/<int:pid>")
def product_detail(pid):
    p = Product.query.get_or_404(pid)
    evidences = Eviden.query.join(Transaksi).filter(Transaksi.offer_id.in_(
        [o.id for o in p.offers])).limit(6).all()
    cu = current_user()
    lelang_item = LelangItem.query.join(LelangEvent).filter(
        LelangItem.product_id == p.id, LelangEvent.status != "dibatalkan").order_by(LelangEvent.id.desc()).first()
    fav_count = Favorite.query.filter_by(seller_id=p.seller_id).count()
    return render_template("product.html", p=p, evidences=evidences, user=cu,
                           lelang_event=lelang_item.event if lelang_item else None,
                           ticker=ticker_data(), fav=fav_state(cu, p.seller_id, p.id),
                           fav_count=fav_count, seller_rating=rating_stats(p.seller_id))


@app.route("/register", methods=["GET", "POST"])
def register():
    role = request.args.get("role", request.form.get("role", "pembeli"))
    if request.method == "POST":
        role = request.form.get("role", "pembeli")
        email = request.form.get("email", "").strip().lower()
        if User.query.filter_by(email=email).first():
            flash("Email sudah terdaftar.", "danger")
            return redirect(url_for("register", role=role))
        if role not in ("penjual", "pembeli"):
            flash("Peran akun tidak valid.", "danger")
            return redirect(url_for("register"))
        tipe_list = TIPE_PENJUAL if role == "penjual" else TIPE_PEMBELI
        tipe = request.form.get("tipe", tipe_list[0])
        if tipe not in tipe_list:
            flash("Tipe akun tidak valid untuk peran yang dipilih.", "danger")
            return redirect(url_for("register", role=role))
        errs = security.check_password_strength(request.form.get("password", ""))
        if errs:
            flash(" | ".join(errs), "danger")
            return redirect(url_for("register", role=role))
        u = User(
            nama=request.form.get("nama", "").strip(),
            email=email,
            password=generate_password_hash(request.form.get("password", "")),
            phone=request.form.get("phone", ""),
            role=role,
            tipe=tipe,
            roles=["penjual", "pembeli"],
            tipe_penjual=tipe if role == "penjual" else TIPE_PENJUAL[0],
            tipe_pembeli=tipe if role == "pembeli" else TIPE_PEMBELI[0],
            alamat=request.form.get("alamat", ""),
            kota=request.form.get("kota", ""),
            provinsi=request.form.get("provinsi", ""),
            lat=float(request.form.get("lat") or 0) or None,
            lng=float(request.form.get("lng") or 0) or None,
            npwp=request.form.get("npwp", ""),
            nib=request.form.get("nib", ""),
        )
        db.session.add(u)
        db.session.commit()
        models_api.AuditLog.record("user_terdaftar", actor=email, role=role, user_id=u.id,
                                   ip=security.client_ip())
        db.session.commit()
        # ---- blockchain: dompet AGR Coin otomatis untuk setiap user baru ----
        if fitur_on("fitur_blockchain"):
            try:
                bchain.ensure_wallet(u.id)
            except Exception as e:
                print("wallet:", e)
        session.clear(); session.permanent = True
        session["uid"] = u.id
        session["active_role"] = role
        flash(f"Pendaftaran berhasil sebagai {role.title()}! Selamat datang di AGR.ID 🌾", "success")
        return redirect(url_for("dashboard"))
    return render_template("register.html", role=role, tipe_penjual=TIPE_PENJUAL,
                           tipe_pembeli=TIPE_PEMBELI, user=current_user())


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        ip = security.client_ip()
        # rate limit percobaan login per IP
        if not security.login_limiter.allow(ip):
            flash("Terlalu banyak percobaan login. Tunggu 1 menit.", "danger")
            models_api.LoginAttempt(email=email, success=False, ip=ip, ua=request.user_agent.string[:200])
            db.session.commit()
            return render_template("login.html", user=current_user())
        u = User.query.filter_by(email=email).first()
        if u and security.is_locked(u):
            flash(f"Akun dikunci sementara karena terlalu sering gagal login. "
                  f"Coba lagi dalam {security.lock_remaining_min(u)} menit.", "danger")
            return render_template("login.html", user=current_user())
        if u and check_password_hash(u.password, request.form.get("password", "")):
            security.clear_failed_login(u)
            models_api.LoginAttempt(email=email, success=True, ip=ip, ua=request.user_agent.string[:200])
            models_api.AuditLog.record("login_sukses", actor=email, role=u.active_role, user_id=u.id, ip=ip)
            db.session.commit()
            session.clear()
            session.permanent = True
            session["uid"] = u.id
            session["active_role"] = u.active_role
            return redirect(url_for("dashboard"))
        if u:
            security.register_failed_login(u)
            models_api.LoginAttempt(email=email, success=False, ip=ip, ua=request.user_agent.string[:200])
            models_api.AuditLog.record("login_gagal", actor=email, user_id=u.id, ip=ip)
        db.session.commit()
        flash("Email / password salah.", "danger")
    return render_template("login.html", user=current_user())


@app.route("/akun/mode", methods=["POST"])
@login_required()
def switch_account_mode():
    u = current_user()
    target = request.form.get("role", "").strip()
    if target not in ("penjual", "pembeli") or target not in u.role_list:
        flash("Mode akun yang dipilih tidak tersedia.", "warning")
        return redirect(url_for("dashboard"))
    session["active_role"] = target
    session.permanent = True
    audit_current("mode_akun_diubah", "users", u.id, f"mode aktif: {target}")
    flash(f"Mode akun beralih ke {target.title()}.", "success")
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    u = current_user()
    if u:
        models_api.AuditLog.record("logout", actor=u.email, role=u.active_role, user_id=u.id,
                                   ip=security.client_ip())
        db.session.commit()
    session.clear()
    return redirect(url_for("home"))

# ----------------------------------------------------------------------------
# ROUTES: DASHBOARD (penjual / pembeli / admin)
# ----------------------------------------------------------------------------

@app.route("/dashboard")
@login_required("penjual", "pembeli", "admin")
def dashboard():
    u = current_user()
    if u.active_role == "penjual":
        return redirect(url_for("dashboard_seller"))
    if u.active_role == "admin":
        return redirect(url_for("dashboard_admin"))
    return redirect(url_for("dashboard_buyer"))



def wallet_ctx(u):
    """Konteks dompet crypto utk template dashboard (aman bila fitur nonaktif)."""
    try:
        if not fitur_on("fitur_blockchain"):
            return {"on": False}
        addr = bchain.ensure_wallet(u.id)
        bal = bchain.balance_of(addr)
        return {"on": True, "address": addr, "balance": bal,
                "idr": bchain.to_rupiah(bal), "rate": bchain.rate,
                "history": bchain.history_of(addr, 10), "stats": bchain.stats()}
    except Exception as e:
        print("wallet_ctx:", e)
        return {"on": False}


@app.route("/dashboard/penjual")
@login_required("penjual")
def dashboard_seller():
    u = current_user()
    my_prods = Product.query.filter_by(seller_id=u.id).order_by(Product.created_at.desc()).all()
    auction_cfg = seller_auction_cfg(u)
    my_auctions = LelangEvent.query.filter_by(seller_id=u.id).order_by(LelangEvent.created_at.desc()).all()
    my_offers = Offer.query.filter(Offer.product_id.in_([p.id for p in my_prods] or [-1])).order_by(Offer.created_at.desc()).all()
    jualan = Transaksi.query.filter_by(seller_id=u.id).order_by(Transaksi.created_at.desc()).all()
    omzet = sum(t.nilai for t in jualan if t.status in ("paid", "shipped", "delivered", "completed"))
    pid = [t.id for t in jualan] or [-1]
    pending_pelunasan = Pelunasan.query.filter(Pelunasan.transaksi_id.in_(pid),
                                               Pelunasan.status == "menunggu").order_by(Pelunasan.created_at.desc()).all()
    ratings_received = Rating.query.filter_by(to_user_id=u.id).order_by(Rating.created_at.desc()).all()
    return render_template("seller_dashboard.html", u=u, products=my_prods, offers=my_offers,
           penjualan=jualan, omzet=omzet, user=u, ticker=ticker_data(),
           lelang_events=my_auctions,
           auction_cfg=auction_cfg,
           default_deadline=(datetime.now(WIB) + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M"),
           minimum_deadline=(datetime.now(WIB) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M"),
           categories=MASTER_PRODUK, biaya=get_biaya_settings(),
           paycfg=seller_payment_cfg(u), pending_pelunasan=pending_pelunasan,
           rstats=rating_stats(u.id), rat_in=ratings_received,
           rat_out=[my_rating_for(t.id, u.id) for t in jualan if my_rating_for(t.id, u.id)],
           rat_pending=pending_ratings(u.id), wallet=wallet_ctx(u))


@app.route("/dashboard/pembeli")
@login_required("pembeli")
def dashboard_buyer():
    u = current_user()
    my_offers = Offer.query.filter_by(buyer_id=u.id).order_by(Offer.created_at.desc()).all()
    pembelian = Transaksi.query.filter_by(buyer_id=u.id).order_by(Transaksi.created_at.desc()).all()
    total_belanja = sum(t.nilai for t in pembelian if t.status in ("paid", "shipped", "delivered", "completed"))
    bookings = {b.id: b for b in Booking.query.filter(Booking.id.in_([t.booking_id for t in pembelian if t.booking_id] or [-1])).all()}
    pelunasans = {}
    for t in pembelian:
        pl = Pelunasan.query.filter_by(transaksi_id=t.id).order_by(Pelunasan.created_at.desc()).first()
        if pl:
            pelunasans[t.id] = pl
    favs = Favorite.query.filter_by(buyer_id=u.id).order_by(Favorite.created_at.desc()).all()
    kebutuhan = KebutuhanPembeli.query.filter_by(buyer_id=u.id).order_by(KebutuhanPembeli.created_at.desc()).all()
    lelang_diikuti = [r.event for r in LelangParticipant.query.filter_by(buyer_id=u.id).order_by(LelangParticipant.created_at.desc()).all()]
    ratings_received = Rating.query.filter_by(to_user_id=u.id).order_by(Rating.created_at.desc()).all()
    return render_template("buyer_dashboard.html", u=u, offers=my_offers, pembelian=pembelian,
                           total=total_belanja, user=u, ticker=ticker_data(),
                           bookings=bookings, pelunasans=pelunasans, favs=favs, kebutuhan=kebutuhan,
                           lelang_diikuti=lelang_diikuti,
                           kategori_list=KATEGORI,
                           rstats=rating_stats(u.id), rat_in=ratings_received,
                           rat_out=[my_rating_for(t.id, u.id) for t in pembelian if my_rating_for(t.id, u.id)],
                           rat_pending=pending_ratings(u.id), wallet=wallet_ctx(u))


@app.route("/dashboard/pembeli/kebutuhan", methods=["POST"])
@login_required("pembeli")
def tambah_kebutuhan():
    u = current_user()
    kategori = request.form.get("kategori", "").strip()
    nama = request.form.get("nama_produk", "").strip()
    satuan = request.form.get("satuan", "").strip()
    try:
        jumlah = float(request.form.get("jumlah", "0"))
        harga = float(request.form.get("estimasi_harga", "0"))
    except (TypeError, ValueError):
        flash("Jumlah dan estimasi harga harus berupa angka.", "danger")
        return redirect(url_for("dashboard_buyer") + "#tNeeds")
    if kategori not in KATEGORI or not nama or len(nama) > 120 or not satuan or len(satuan) > 20 or jumlah <= 0 or harga < 0:
        flash("Periksa kategori, nama produk, satuan, jumlah, dan estimasi harga.", "danger")
        return redirect(url_for("dashboard_buyer") + "#tNeeds")
    db.session.add(KebutuhanPembeli(buyer_id=u.id, kategori=kategori, nama_produk=nama,
                                    satuan=satuan, jumlah=jumlah, estimasi_harga=harga))
    db.session.commit()
    flash("Kebutuhan belanja ditambahkan.", "success")
    return redirect(url_for("dashboard_buyer") + "#tNeeds")


@app.route("/dashboard/pembeli/kebutuhan/<int:kid>/hapus", methods=["POST"])
@login_required("pembeli")
def hapus_kebutuhan(kid):
    item = KebutuhanPembeli.query.filter_by(id=kid, buyer_id=current_user().id).first_or_404()
    db.session.delete(item)
    db.session.commit()
    flash("Kebutuhan dihapus dari rencana belanja.", "success")
    return redirect(url_for("dashboard_buyer") + "#tNeeds")


@app.route("/produk/<int:pid>/kebutuhan", methods=["POST"])
@login_required("pembeli")
def tambah_produk_ke_kebutuhan(pid):
    p = Product.query.filter_by(id=pid, status="aktif").first_or_404()
    try:
        jumlah = float(request.form.get("jumlah", "1"))
    except (TypeError, ValueError):
        jumlah = 0
    if jumlah <= 0:
        flash("Jumlah kebutuhan harus lebih dari nol.", "danger")
        return redirect(url_for("product_detail", pid=pid))
    item = KebutuhanPembeli.query.filter_by(buyer_id=current_user().id, product_id=p.id).first()
    if item:
        item.jumlah += jumlah
        item.estimasi_harga = p.harga or 0
    else:
        db.session.add(KebutuhanPembeli(buyer_id=current_user().id, product_id=p.id, kategori=p.kategori,
                                    nama_produk=p.nama_produk, jumlah=jumlah,
                                    satuan=p.satuan or "unit", estimasi_harga=p.harga or 0))
    db.session.commit()
    flash(f"{p.nama_produk} ditambahkan ke Manajemen Kebutuhan dengan harga listing sebagai estimasi." if not item else
          f"Jumlah rencana {p.nama_produk} diperbarui dan harga estimasinya disegarkan dari listing.", "success")
    return redirect(url_for("dashboard_buyer") + "#tNeeds")


@app.route("/favorit/<int:fqid>/kebutuhan", methods=["POST"])
@login_required("pembeli")
def tambah_favorit_ke_kebutuhan(fqid):
    favorite = Favorite.query.filter_by(id=fqid, buyer_id=current_user().id).first_or_404()
    product = Product.query.filter_by(id=favorite.product_id, status="aktif").first() if favorite.product_id else None
    if not product:
        flash("Listing favorit ini sudah tidak tersedia untuk ditambahkan ke rencana belanja.", "warning")
        return redirect(url_for("dashboard_buyer") + "#tFav")
    try:
        jumlah = float(request.form.get("jumlah", "1"))
    except (TypeError, ValueError):
        jumlah = 0
    if not (0 < jumlah < float("inf")):
        flash("Jumlah rencana harus lebih dari nol.", "danger")
        return redirect(url_for("dashboard_buyer") + "#tFav")
    item = KebutuhanPembeli.query.filter_by(buyer_id=current_user().id, product_id=product.id).first()
    if item:
        item.jumlah += jumlah
        item.estimasi_harga = product.harga or 0
    else:
        db.session.add(KebutuhanPembeli(buyer_id=current_user().id, product_id=product.id,
                                        kategori=product.kategori or KATEGORI[0],
                                        nama_produk=product.nama_produk, jumlah=jumlah,
                                        satuan=product.satuan or "unit", estimasi_harga=product.harga or 0))
    db.session.commit()
    audit_current("produk_favorit_ditambahkan_ke_kebutuhan", "products", product.id,
                  f"jumlah rencana +{jumlah:g} {product.satuan or 'unit'}")
    flash(f"{product.nama_produk} ditambahkan ke Manajemen Kebutuhan menggunakan harga listing terbaru.", "success")
    return redirect(url_for("dashboard_buyer") + "#tNeeds")


@app.route("/dashboard/admin")
@login_required("admin")
def dashboard_admin():
    u = current_user()
    tx = Transaksi.query.order_by(Transaksi.created_at.desc()).all()
    revenue = sum((t.biaya_penanganan or 0) for t in tx)
    pg = PaymentGatewayAPI.query.all()
    eks = Ekspedisi.query.all()
    settings = {p.key: p.value for p in Pengaturan.query.all()}
    auction_requests = LelangEvent.query.filter_by(status="diajukan").order_by(LelangEvent.created_at.asc()).all()

    # ---- Laporan keuangan (rekap per metode pembayaran & status) ----
    by_method, by_status = {}, {}
    for t in tx:
        m = (t.metode_bayar or "-").lower()
        d = by_method.setdefault(m, {"n": 0, "nilai": 0.0, "dp": 0.0, "pelunasan": 0.0,
                                     "fee": 0.0, "ongkir": 0.0})
        d["n"] += 1; d["nilai"] += t.nilai or 0; d["dp"] += t.dp_dibayar or 0
        d["pelunasan"] += t.pelunasan or 0; d["fee"] += t.biaya_penanganan or 0; d["ongkir"] += t.ongkir or 0
        s = t.status or "-"
        r = by_status.setdefault(s, {"n": 0, "nilai": 0.0})
        r["n"] += 1; r["nilai"] += t.nilai or 0
    paid_tx = [t for t in tx if t.status in ("paid", "shipped", "delivered", "completed")]
    keuangan = {
        "bruto": sum(t.nilai for t in tx),
        "bersih": sum(t.nilai for t in paid_tx),
        "dp_masuk": sum(t.dp_dibayar or 0 for t in tx),
        "pelunasan_masuk": sum(t.pelunasan or 0 for t in tx),
        "ongkir": sum(t.ongkir or 0 for t in tx),
        "fee": revenue,
        "flat": sum(float(get_setting("biaya_tambahan_flat", "0") or 0) for t in tx),
        "pending": sum(t.nilai for t in tx if t.status not in ("paid", "shipped", "delivered", "completed", "cancelled", "refunded")),
    }

    # ---- Pembagian laporan penjualan vs pembelian ----
    penjualan_rows = sorted(tx, key=lambda t: t.created_at, reverse=True)
    pembelian_rows = penjualan_rows
    total_nilai_penjualan = sum(t.nilai for t in tx)
    total_nilai_pembelian = total_nilai_penjualan

    accounts = User.query.all()
    stats = {
        "users": len(accounts),
        "penjual": sum("penjual" in account.role_list for account in accounts),
        "pembeli": sum("pembeli" in account.role_list for account in accounts),
        "produk": Product.query.count(),
        "master": ProdukMaster.query.count(),
        "transaksi": len(tx),
        "gmv": sum(t.nilai for t in tx),
        "revenue": revenue,
        "favorites": Favorite.query.count(),
        "ratings": Rating.query.count(),
    }
    # ---- Rekap kepuasan dua arah utk monitoring admin ----
    rat_rows = Rating.query.order_by(Rating.created_at.desc()).all()
    ke_penjual = [r for r in rat_rows if r.arah == "ke_penjual"]
    ke_pembeli = [r for r in rat_rows if r.arah == "ke_pembeli"]
    rating_rekap = {
        "total": len(rat_rows),
        "avg_penjual": round(sum(r.score for r in ke_penjual) / len(ke_penjual), 2) if ke_penjual else None,
        "avg_pembeli": round(sum(r.score for r in ke_pembeli) / len(ke_pembeli), 2) if ke_pembeli else None,
        "n_penjual": len(ke_penjual), "n_pembeli": len(ke_pembeli),
        "rendah": [r for r in rat_rows if r.score <= 2],
    }
    return render_template("admin_dashboard.html", u=u, stats=stats, tx=tx, pg=pg, eks=eks,
                           settings=settings, user=u, ticker=ticker_data(),
                           db_backend=("supabase-postgres" if app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgres") else "sqlite"),
                           cloudinary_on=cloud_media.enabled(),
                           cloudinary_secret_set=bool(cloud_media.cfg()["api_secret"]),
                           biaya=get_biaya_settings(), labels=BIAYA_LABEL,
                           keuangan=keuangan, by_method=by_method, by_status=by_status,
                           penjualan_rows=penjualan_rows, pembelian_rows=pembelian_rows,
                           total_penjualan=total_nilai_penjualan, total_pembelian=total_nilai_pembelian,
                           rating_rekap=rating_rekap, rat_rows=rat_rows[:30],
                           auction_requests=auction_requests,
                           wallet=wallet_ctx(u), bstats=bchain.stats(),
                           feat_cfg=FEATURE_KEYS)

# ----------------------------------------------------------------------------
# ROUTES: PRODUK (CRUD + auto-add master)
# ----------------------------------------------------------------------------

@app.route("/produk/baru", methods=["GET", "POST"])
@feature_required("fitur_marketplace")
@login_required("penjual")
def create_product():
    u = current_user()
    if request.method == "POST":
        nama = request.form.get("nama_produk", "").strip()
        kategori = request.form.get("kategori")
        sub = request.form.get("subkategori")
        jenis = request.form.get("jenis", "").strip()
        non_halal = (kategori == "Peternakan" and sub == "Babi")
        # === AUTO UPDATE DATABASE PRODUK: simpan nama produk baru ke DB produk master ===
        pm = ProdukMaster.query.filter(db.func.lower(ProdukMaster.nama) == nama.lower()).first()
        if not pm:
            pm = ProdukMaster(nama=nama, kategori=kategori, subkategori=sub,
                              jenis=jenis, non_halal=non_halal, auto_added=True)
            db.session.add(pm)
            db.session.commit()
            flash(f"Nama produk \"{nama}\" baru pertama kali di AGR.ID → otomatis ditambahkan ke Database Produk ✔", "info")
        p = Product(
            seller_id=u.id, nama_produk=nama, jenis=jenis, kategori=kategori, subkategori=sub,
            deskripsi=request.form.get("deskripsi", ""),
            harga=float(request.form.get("harga") or 0),
            satuan=request.form.get("satuan", "kg"),
            stok=float(request.form.get("stok") or 0),
            foto=request.form.get("foto", ""),
            alamat_lahan=request.form.get("alamat_lahan", ""),
            lat=float(request.form.get("lat") or 0) or None,
            lng=float(request.form.get("lng") or 0) or None,
            non_halal=non_halal,
            sertifikasi=request.form.get("sertifikasi", ""),
        )
        db.session.add(p)
        db.session.commit()
        flash("Produk berhasil diposting ke marketplace 🎉", "success")
        return redirect(url_for("dashboard_seller"))
    return render_template("product_form.html", categories=MASTER_PRODUK, user=u, ticker=ticker_data())


@app.route("/produk/edit/<int:pid>", methods=["GET", "POST"])
@login_required("penjual")
def edit_product(pid):
    p = Product.query.get_or_404(pid)
    u = current_user()
    if p.seller_id != u.id:
        flash("Tidak berwenang.", "danger"); return redirect(url_for("dashboard_seller"))
    if p.status == "lelang":
        flash("Produk sedang dicadangkan untuk event lelang dan tidak dapat diubah sampai proses lelang selesai.", "warning")
        return redirect(url_for("dashboard_seller"))
    if request.method == "POST":
        p.nama_produk = request.form.get("nama_produk", p.nama_produk)
        p.jenis = request.form.get("jenis", p.jenis)
        p.harga = float(request.form.get("harga") or p.harga)
        p.satuan = request.form.get("satuan", p.satuan)
        p.stok = float(request.form.get("stok") or 0)
        p.deskripsi = request.form.get("deskripsi", p.deskripsi)
        p.foto = request.form.get("foto", p.foto)
        p.alamat_lahan = request.form.get("alamat_lahan", p.alamat_lahan)
        p.lat = float(request.form.get("lat") or 0) or p.lat
        p.lng = float(request.form.get("lng") or 0) or p.lng
        p.sertifikasi = request.form.get("sertifikasi", p.sertifikasi)
        p.status = request.form.get("status", p.status)
        db.session.commit()
        flash("Produk diperbarui.", "success")
        return redirect(url_for("dashboard_seller"))
    return render_template("product_form.html", categories=MASTER_PRODUK, user=u, p=p, ticker=ticker_data())


@app.route("/produk/hapus/<int:pid>")
@login_required("penjual")
def delete_product(pid):
    p = Product.query.get_or_404(pid)
    if p.seller_id != current_user().id:
        flash("Tidak berwenang.", "danger")
    elif p.status == "lelang":
        flash("Produk sedang dicadangkan untuk event lelang dan tidak dapat diarsipkan.", "warning")
    else:
        p.status = "arsip"
        db.session.commit()
        flash("Produk diarsipkan.", "info")
    return redirect(url_for("dashboard_seller"))


@app.route("/api/produk-master")
def api_produk_master():
    """Autocomplete nama produk dari database produk (termasuk yang auto-added)."""
    q = request.args.get("q", "").lower()
    kat = request.args.get("kategori", "")
    sub = request.args.get("subkategori", "")
    query = ProdukMaster.query
    if q:
        query = query.filter(ProdukMaster.nama.ilike(f"%{q}%"))
    if kat:
        query = query.filter(ProdukMaster.kategori == kat)
    if sub:
        query = query.filter(ProdukMaster.subkategori == sub)
    rows = query.limit(30).all()
    return jsonify([{
        "id": r.id, "nama": r.nama, "kategori": r.kategori, "subkategori": r.subkategori,
        "jenis": r.jenis.split(", ") if r.jenis else [], "non_halal": r.non_halal,
    } for r in rows])

# ----------------------------------------------------------------------------
# ROUTES: OFFER / BOOKING / TRANSAKSI / EVIFEN
# ----------------------------------------------------------------------------

@app.route("/offer/buat/<int:pid>", methods=["POST"])
@feature_required("fitur_penawaran")
@login_required("pembeli")
def create_offer(pid):
    p = Product.query.get_or_404(pid)
    u = current_user()
    if p.status != "aktif":
        flash("Produk ini tidak tersedia untuk penawaran biasa karena sedang dilelang atau diarsipkan.", "warning")
        return redirect(url_for("auction_list"))
    qty = float(request.form.get("qty") or 0)
    harga = float(request.form.get("harga_penawaran") or 0)
    if qty <= 0 or harga <= 0:
        flash("Jumlah & harga penawaran harus > 0", "danger")
        return redirect(url_for("product_detail", pid=pid))
    o = Offer(product_id=pid, buyer_id=u.id, qty=qty, harga_penawaran=harga,
              harga_terkini=harga, total=qty * harga, pesan=request.form.get("pesan", ""))
    db.session.add(o)
    db.session.commit()
    flash("Penawaran terkirim ke penjual. Tunggu konfirmasi untuk lanjut ke booking DP 💛", "success")
    return redirect(url_for("dashboard_buyer"))


@app.route("/offer/status/<int:oid>", methods=["POST"])
@login_required("penjual")
def respond_offer(oid):
    o = Offer.query.get_or_404(oid)
    u = current_user()
    prod = Product.query.get(o.product_id)
    if prod.seller_id != u.id:
        flash("Tidak berwenang.", "danger"); return redirect(url_for("dashboard_seller"))
    act = request.form.get("act")
    allowed_seller_turn = o.status in ("menunggu", "balasan_penjual")
    if act == "tawar" and allowed_seller_turn:
        harga_baru = _positive_price(request.form.get("harga_baru"))
        if harga_baru is None:
            flash("Harga balasan harus berupa angka lebih dari nol.", "danger")
            return redirect(url_for("dashboard_seller"))
        o.harga_terkini = harga_baru
        o.total = o.qty * harga_baru
        o.status = "balasan_pembeli"
        db.session.commit()
        audit_current("penjual_mengajukan_harga_balik", "offers", oid, f"harga per unit {harga_baru:g}")
        flash("Harga balasan dikirim ke pembeli.", "success")
    elif act == "terima" and allowed_seller_turn:
        due = _validated_payment_deadline(request.form.get("batas_pembayaran"))
        if due is None:
            flash("Tentukan batas waktu pembayaran DP di masa mendatang (WIB).", "danger")
            return redirect(url_for("dashboard_seller"))
        _finalize_offer_agreement(o, due)
        db.session.commit()
        audit_current("penawaran_disepakati", "offers", oid, f"batas pembayaran {due.isoformat()} UTC")
        flash("Harga disepakati. Pembeli harus membayar DP sebelum batas waktu yang ditentukan.", "success")
    elif act == "finalisasi" and o.status == "menunggu_konfirmasi":
        due = _validated_payment_deadline(request.form.get("batas_pembayaran"))
        if due is None:
            flash("Tentukan batas waktu pembayaran DP di masa mendatang (WIB).", "danger")
            return redirect(url_for("dashboard_seller"))
        _finalize_offer_agreement(o, due)
        db.session.commit()
        audit_current("penawaran_disepakati", "offers", oid, f"batas pembayaran {due.isoformat()} UTC")
        flash("Kesepakatan dikonfirmasi. Tenggat pembayaran DP sudah dikirim ke pembeli.", "success")
    elif act == "tolak" and (allowed_seller_turn or o.status == "menunggu_konfirmasi"):
        o.status = "ditolak"
        db.session.commit()
        audit_current("penawaran_ditutup_penjual", "offers", oid, "penjual menolak dan menutup negosiasi")
        flash("Penawaran ditolak dan negosiasi ditutup.", "info")
    else:
        flash("Penawaran ini tidak sedang menunggu tindakan Anda.", "warning")
    return redirect(url_for("dashboard_seller"))


def _positive_price(value):
    try:
        price = float(value)
        return price if price > 0 and price < float("inf") else None
    except (TypeError, ValueError):
        return None


def _nonnegative_amount(value):
    try:
        amount = float(value)
        return amount if 0 <= amount < float("inf") else None
    except (TypeError, ValueError):
        return None


def _validated_payment_deadline(value):
    due = parse_wib_deadline(value)
    return due if due and due > datetime.utcnow() else None


def _finalize_offer_agreement(offer, due):
    price = offer.harga_terkini or offer.harga_penawaran
    offer.harga_terkini = price
    offer.harga_disepakati = price
    offer.total = offer.qty * price
    offer.batas_pembayaran = due
    offer.status = "diterima"


@app.route("/offer/balasan/<int:oid>", methods=["POST"])
@login_required("pembeli")
def buyer_respond_offer(oid):
    offer = Offer.query.get_or_404(oid)
    if offer.buyer_id != current_user().id:
        flash("Tidak berwenang.", "danger")
        return redirect(url_for("dashboard_buyer"))
    if offer.status != "balasan_pembeli":
        flash("Penawaran ini tidak sedang menunggu balasan Anda.", "warning")
        return redirect(url_for("dashboard_buyer"))
    act = request.form.get("act")
    if act == "terima":
        offer.status = "menunggu_konfirmasi"
        offer.harga_terkini = offer.harga_terkini or offer.harga_penawaran
        offer.total = offer.qty * offer.harga_terkini
        flash("Harga balasan disetujui. Penjual akan menetapkan tenggat pembayaran DP.", "success")
    elif act == "tawar":
        price = _positive_price(request.form.get("harga_baru"))
        if price is None:
            flash("Harga balasan harus berupa angka lebih dari nol.", "danger")
            return redirect(url_for("dashboard_buyer"))
        offer.harga_terkini = price
        offer.total = offer.qty * price
        offer.status = "balasan_penjual"
        flash("Tawaran harga Anda dikirim kembali ke penjual.", "success")
    elif act == "tolak":
        offer.status = "ditolak"
        flash("Anda menolak harga balasan dan menutup penawaran ini.", "info")
    else:
        flash("Aksi tidak dikenali.", "danger")
        return redirect(url_for("dashboard_buyer"))
    db.session.commit()
    audit_current("pembeli_membalas_negosiasi", "offers", oid, f"aksi {act}")
    return redirect(url_for("dashboard_buyer"))


@app.route("/booking/<int:oid>", methods=["GET", "POST"])
@feature_required("fitur_booking_dp")
@login_required("pembeli")
def show_booking_form(oid):
    o = Offer.query.get_or_404(oid)
    if o.buyer_id != current_user().id:
        flash("Tidak berwenang.", "danger"); return redirect(url_for("dashboard_buyer"))
    if o.status not in ("diterima", "booking"):
        flash("Penawaran belum disepakati atau sudah ditutup/kedaluwarsa.", "warning")
        return redirect(url_for("dashboard_buyer"))
    if o.status == "booking":
        pending_booking = Booking.query.filter_by(offer_id=o.id, status="dp_pending").order_by(Booking.id.desc()).first()
        if pending_booking:
            return redirect(url_for("pay_booking", bid=pending_booking.id))
        flash("Penawaran ini sudah diproses menjadi booking.", "info")
        return redirect(url_for("dashboard_buyer"))
    dp_persen = float(get_setting("dp_persen", "20"))
    fee_persen = float(get_setting("biaya_penanganan_persen", "2"))
    dp_amount = round(o.total * dp_persen / 100, 0)
    fee = round(o.total * fee_persen / 100, 0)
    sisa = round(o.total - dp_amount, 0)
    eks_list = Ekspedisi.query.filter_by(enabled=True).all()
    seller_cfg = seller_payment_cfg(o.product.seller)
    if request.method == "POST":
        jadwal = request.form.get("jadwal_kirim")
        eks_id = request.form.get("ekspedisi_id") or None
        metode_dp = request.form.get("metode_dp") or (seller_cfg["metode_dp"][0] if seller_cfg["metode_dp"] else "Transfer Bank")
        b = Booking(offer_id=o.id, dp_persen=dp_persen, dp_amount=dp_amount,
                    sisa_bayar=sisa, biaya_penanganan=fee, metode_dp=metode_dp,
                    jadwal_kirim=datetime.strptime(jadwal, "%Y-%m-%d").date() if jadwal else None,
                    ekspedisi_id=eks_id, status="dp_pending")
        db.session.add(b)
        o.status = "booking"
        db.session.commit()
        return redirect(url_for("pay_booking", bid=b.id))
    return render_template("booking_form.html", o=o, dp_persen=dp_persen, fee_persen=fee_persen,
                           dp_amount=dp_amount, fee=fee, sisa=sisa, eks_list=eks_list,
                           metode_dp=seller_cfg["metode_dp"], rekening=seller_cfg["rekening"],
                           tujuan_tunai=seller_cfg["tujuan_tunai"],
                           user=current_user(), ticker=ticker_data())


@app.route("/booking/<int:bid>/bayar", methods=["GET", "POST"])
@feature_required("fitur_payment_gateway")
@login_required("pembeli")
def pay_booking(bid):
    """Simulasi payment gateway: QRIS/VA/E-wallet/Bank Transfer."""
    b = Booking.query.get_or_404(bid)
    o = b.offer
    if o.buyer_id != current_user().id:
        flash("Tidak berwenang.", "danger"); return redirect(url_for("dashboard_buyer"))
    if o.status != "booking" or b.status != "dp_pending":
        flash("Pembayaran DP tidak tersedia. Penawaran mungkin sudah kedaluwarsa atau DP telah dibayar.", "warning")
        return redirect(url_for("dashboard_buyer"))
    if o.batas_pembayaran and o.batas_pembayaran <= datetime.utcnow():
        o.status = "kedaluwarsa"
        b.status = "batal"
        db.session.commit()
        flash("Batas pembayaran telah lewat. Penawaran otomatis ditutup.", "danger")
        return redirect(url_for("dashboard_buyer"))
    pg_active = PaymentGatewayAPI.query.filter_by(enabled=True).first()
    channels = (pg_active.channels.split(",") if pg_active else ["qris", "virtual_account", "ewallet", "bank_transfer"])
    ref = "PGX-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + str(random.randint(1000, 9999))
    if request.method == "POST":
        method = request.form.get("metode")
        b.status = "dp_lunas"
        o.status = "booking"
        eks = Ekspedisi.query.get(b.ekspedisi_id) if b.ekspedisi_id else None
        ongkir = round((eks.tarif_per_kg or 0) * (o.qty if o.qty <= 500 else o.qty), 0) if eks else 0
        t = Transaksi(offer_id=o.id, booking_id=b.id, seller_id=Product.query.get(o.product_id).seller_id,
                      buyer_id=o.buyer_id, product_name=o.product.nama_produk, qty=o.qty,
                      nilai=o.total, dp_dibayar=b.dp_amount, biaya_penanganan=b.biaya_penanganan,
                      ongkir=ongkir, metode_bayar=f"{b.metode_dp} via {method}" if b.metode_dp else method,
                      ref_payment=ref, status="processing")
        db.session.add(t)
        db.session.commit()
        # ---- blockchain: distribusi pembayaran DP on-chain ke dompet penjual ----
        txh = bchain.settle_payment(o.buyer_id, t.seller_id, b.dp_amount,
                                    ref=f"BOOKING-{b.id}", memo=f"DP booking {o.product.nama_produk}")
        if txh:
            t.ref_payment = f"{ref} | AGR-ONCHAIN:{txh[:16]}"
            db.session.commit()
        flash(f"DP {int(b.dp_amount):,} ({b.metode_dp}) berhasil dibayar via payment gateway {method.upper()} 🎉 Ref: {ref}"
              + (" — tercatat on-chain ⛓️" if txh else ""), "success")
        audit_current("dp_dibayar_pg", "bookings", bid, "pembayaran DP via payment gateway"
                      + (f" + transfer crypto {txh[:16]}…" if txh else ""))
        return redirect(url_for("dashboard_buyer"))
    return render_template("payment.html", b=b, o=o, channels=channels, ref=ref,
                           pg=pg_active, user=current_user(), ticker=ticker_data())


@app.route("/transaksi/<int:tid>/pelunasan", methods=["GET", "POST"])
@feature_required("fitur_pelunasan_manual")
@login_required("pembeli")
def submit_pelunasan(tid):
    """Pembeli menyelesaikan pembayaran pelunasan DP: upload bukti transfer -> approval penjual."""
    t = Transaksi.query.get_or_404(tid)
    u = current_user()
    if t.buyer_id != u.id:
        flash("Tidak berwenang.", "danger"); return redirect(url_for("dashboard_buyer"))
    b = Booking.query.get(t.booking_id) if t.booking_id else None
    seller_cfg = seller_payment_cfg(t.seller)
    sisa = round((t.nilai - t.dp_dibayar) + (t.ongkir or 0), 0)
    pl_terbaru = Pelunasan.query.filter_by(transaksi_id=t.id).order_by(Pelunasan.created_at.desc()).first()
    if request.method == "POST":
        metode = request.form.get("metode") or "Transfer Bank"
        bukti = request.form.get("bukti", "")          # ref object://bucket/private (direct upload) atau data URI legacy
        if bukti.startswith("data:"):                  # fallback: migrasikan base64 ke bucket private, DB tidak lagi menyimpan blob
            try:
                bukti = storage.ingest_data_uri(bukti, u.id, "payment") or ""
            except storage.ValidationError as e:
                flash(f"Bukti transfer ditolak: {e}", "danger")
                return redirect(url_for("submit_pelunasan", tid=tid))
        jumlah = float(request.form.get("jumlah") or sisa)
        pl = Pelunasan(transaksi_id=t.id, buyer_id=u.id, jumlah=jumlah, metode=metode,
                       rekening_tujuan=seller_cfg["rekening"] or seller_cfg["tujuan_tunai"],
                       bukti=bukti, catatan=request.form.get("catatan", ""), status="menunggu")
        db.session.add(pl)
        if b:
            b.status = "menunggu_pelunasan"
        t.status = "menunggu_approval"
        db.session.commit()
        flash("Pengajuan pelunasan dikirim — menunggu approval dari penjual ⏳", "success")
        audit_current("pelunasan_diajukan", "transaksi", tid, "upload bukti transfer pelunasan")
        return redirect(url_for("dashboard_buyer"))
    return render_template("pelunasan_form.html", t=t, b=b, sisa=sisa, pl=pl_terbaru,
                           cfg=seller_cfg, user=u, ticker=ticker_data())


@app.route("/pelunasan/<int:pid>/review", methods=["POST"])
@login_required("penjual")
def review_pelunasan(pid):
    """Penjual menyetujui/menolak bukti transfer pelunasan pembeli."""
    pl = Pelunasan.query.get_or_404(pid)
    t = pl.transaksi
    u = current_user()
    if t.seller_id != u.id:
        audit_current("pelunasan_di_review", "pelunasan", pid, "approval/penolakan pelunasan oleh penjual")
        flash("Tidak berwenang.", "danger"); return redirect(url_for("dashboard_seller"))
    aksi = request.form.get("aksi")
    catatan = request.form.get("catatan", "")
    b = Booking.query.get(t.booking_id) if t.booking_id else None
    if aksi == "setuju":
        pl.status = "disetujui"
        t.pelunasan = pl.jumlah
        t.status = "paid"
        if b:
            b.status = "dp_lunas"
        pl.reviewed_at = datetime.utcnow()
        pl.review_catatan = catatan
        db.session.commit()
        # ---- blockchain: distribusi pelunasan on-chain ke dompet penjual ----
        txh = bchain.settle_payment(t.buyer_id, t.seller_id, pl.jumlah,
                                    ref=f"TX-{t.id}", memo=f"Pelunasan {t.product_name}")
        if txh:
            t.ref_payment = (t.ref_payment or "") + f" | AGR-ONCHAIN:{txh[:16]}"
            db.session.commit()
        flash("Pelunasan disetujui ✔ transaksi dinyatakan lunas."
              + (" Dana didistribusikan on-chain ⛓️" if txh else ""), "success")
    elif aksi == "tolak":
        pl.status = "ditolak"
        t.status = "processing"
        if b:
            b.status = "pelunasan_ditolak"
        pl.reviewed_at = datetime.utcnow()
        pl.review_catatan = catatan
        db.session.commit()
        flash("Pelunasan ditolak. Pembeli dapat mengajukan ulang dengan bukti yang benar.", "warning")
    return redirect(url_for("dashboard_seller"))


@app.route("/transaksi/<int:tid>/eviden", methods=["GET", "POST"])
@feature_required("fitur_eviden")
@login_required("penjual", "pembeli")
def add_eviden(tid):
    t = Transaksi.query.get_or_404(tid)
    u = current_user()
    if u.active_role not in ("penjual", "pembeli") or (t.seller_id != u.id and t.buyer_id != u.id):
        flash("Tidak berwenang.", "danger"); audit_current("eviden_ditambah", "transaksi", tid, "bukti ketelusuran baru")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        e = Eviden(transaksi_id=t.id, tahap=request.form.get("tahap"),
                   keterangan=request.form.get("keterangan", ""),
                   foto=request.form.get("foto", ""),
                   lat=float(request.form.get("lat") or 0) or None,
                   lng=float(request.form.get("lng") or 0) or None,
                   uploaded_by=u.id)
        db.session.add(e)
        db.session.commit()
        flash("Eviden tersimpan untuk ketelusuran ✔", "success")
    evif = Eviden.query.filter_by(transaksi_id=t.id).order_by(Eviden.created_at).all()
    return render_template("eviden.html", t=t, evif=evif, user=u, ticker=ticker_data())


@app.route("/transaksi/<int:tid>/status", methods=["POST"])
@login_required("penjual", "pembeli", "admin")
def update_status(tid):
    t = Transaksi.query.get_or_404(tid)
    u = current_user()
    new = request.form.get("status")
    b = Booking.query.get(t.booking_id) if t.booking_id else None
    if u.active_role == "penjual" and t.seller_id != u.id:
        flash("Tidak berwenang.", "danger"); audit_current("status_diubah", "transaksi", tid, "perubahan status transaksi")
        return redirect(url_for("dashboard"))
    if new in ("shipped", "delivered", "completed", "cancelled", "paid"):
        t.status = new
        if new == "completed":
            t.completed_at = datetime.utcnow()
            t.pelunasan = t.nilai - t.dp_dibayar
            if b:
                b.status = "selesai"
            t.offer.status = "selesai"
        if new == "shipped" and b:
            b.status = "dikirim"
            b.tracking_code = request.form.get("tracking_code", b.tracking_code)
        db.session.commit()
        flash("Status transaksi diperbarui → " + new.upper(), "success")
    return redirect(request.referrer or url_for("dashboard"))

# ----------------------------------------------------------------------------
# ROUTES: PENILAIAN TINGKAT KEPUASAN (rating dua arah penjual <-> pembeli)
# ----------------------------------------------------------------------------

@app.route("/transaksi/<int:tid>/nilai", methods=["GET", "POST"])
@feature_required("fitur_rating")
@login_required("penjual", "pembeli")
def rate_transaction(tid):
    """Pemberian score kepuasan oleh salah satu pihak atas transaksi selesai."""
    t = Transaksi.query.get_or_404(tid)
    u = current_user()
    if t.status != "completed":
        flash("Penilaian hanya dapat diberikan setelah transaksi berstatus selesai.", "warning")
        audit_current("penilaian_dibuat", "transaksi", tid, "rating kepuasan")
        return redirect(url_for("dashboard"))
    if u.active_role == "pembeli" and t.buyer_id != u.id:
        flash("Tidak berwenang.", "danger"); return redirect(url_for("dashboard"))
    if u.active_role == "penjual" and t.seller_id != u.id:
        flash("Tidak berwenang.", "danger"); return redirect(url_for("dashboard"))
    if my_rating_for(t.id, u.id):
        flash("Anda sudah menilai transaksi ini. Terima kasih! ⭐", "info")
        return redirect(url_for("dashboard"))
    to_id = t.seller_id if u.active_role == "pembeli" else t.buyer_id
    arah = "ke_penjual" if u.active_role == "pembeli" else "ke_pembeli"
    aspek_list = ASPEK_KEPUASAN[arah]
    if request.method == "POST":
        try:
            overall = int(request.form.get("score") or 0)
        except Exception:
            overall = 0
        if not 1 <= overall <= 5:
            flash("Skor utama harus 1–5 bintang.", "danger")
            return redirect(url_for("rate_transaction", tid=tid))
        aspek = {}
        for key, _lab in aspek_list:
            try:
                v = int(request.form.get(f"aspek_{key}") or overall)
            except Exception:
                v = overall
            aspek[key] = max(1, min(5, v))
        r = Rating(transaksi_id=t.id, from_user_id=u.id, to_user_id=to_id, arah=arah,
                   score=overall, aspek=json.dumps(aspek),
                   komentar=request.form.get("komentar", "").strip())
        db.session.add(r)
        db.session.commit()
        lawang = "penjual" if u.active_role == "pembeli" else "pembeli"
        flash(f"Penilaian {overall}⭐ untuk {lawang} tersimpan — terima kasih atas feedback Anda! 🌾", "success")
        return redirect(url_for("dashboard"))
    return render_template("rate_form.html", t=t, arah=arah, aspek_list=aspek_list,
                           user=u, ticker=ticker_data())


@app.route("/api/rating/<int:uid>")
@feature_required("fitur_rating")
def api_user_rating(uid):
    """Rekap rating publik seorang user + daftar ulasan terbaru ( utk badge & modal )."""
    stats = rating_stats(uid)
    rows = Rating.query.filter_by(to_user_id=uid).order_by(Rating.created_at.desc()).limit(10).all()
    ulas = []
    for r in rows:
        aspek = {}
        try:
            aspek = json.loads(r.aspek or "{}")
        except Exception:
            pass
        ulas.append({"skor": r.score, "bintang": "★" * r.score + "☆" * (5 - r.score),
                    "arah": r.arah, "dari": r.from_user.nama, "produk": r.transaksi.product_name,
                    "komentar": r.komentar, "tgl": r.created_at.strftime("%d %b %Y"), "aspek": aspek})
    usr = User.query.get(uid)
    return jsonify(ok=True, nama=usr.nama if usr else "-", role=usr.active_role if usr else "-",
                   **stats, ulasan=ulas)

# ----------------------------------------------------------------------------
# ROUTES: ADMIN CONFIG (API keys, biaya tambahan, persen DP)
# ----------------------------------------------------------------------------

@app.route("/admin/pg-api", methods=["POST"])
@login_required("admin")
def save_pg_api():
    pid = request.form.get("id", type=int)
    pg = PaymentGatewayAPI.query.get(pid) if pid else PaymentGatewayAPI()
    pg.provider = request.form.get("provider")
    pg.base_url = request.form.get("base_url")
    pg.api_key = request.form.get("api_key")
    pg.server_key = request.form.get("server_key")
    pg.client_key = request.form.get("client_key")
    pg.webhook_secret = request.form.get("webhook_secret")
    pg.channels = request.form.get("channels", pg.channels)
    pg.enabled = bool(request.form.get("enabled"))
    db.session.add(pg); db.session.commit()
    flash("Konfigurasi API Payment Gateway disimpan ✔", "success")
    audit_current("pengaturan_pg_api", "pengaturan", None, "perubahan konfigurasi platform")
    return redirect(url_for("dashboard_admin"))


@app.route("/admin/ekspedisi", methods=["POST"])
@login_required("admin")
def save_ekspedisi():
    eid = request.form.get("id", type=int)
    e = Ekspedisi.query.get(eid) if eid else Ekspedisi()
    e.nama = request.form.get("nama")
    e.base_url = request.form.get("base_url")
    e.api_key = request.form.get("api_key")
    e.account_id = request.form.get("account_id")
    e.service_types = request.form.get("service_types", e.service_types)
    e.tarif_per_kg = float(request.form.get("tarif_per_kg") or 0)
    e.enabled = bool(request.form.get("enabled"))
    db.session.add(e); db.session.commit()
    flash("Data jasa ekspedisi disimpan ✔", "success")
    audit_current("pengaturan_ekspedisi", "pengaturan", None, "perubahan konfigurasi platform")
    return redirect(url_for("dashboard_admin"))


@app.route("/admin/ekspedisi/hapus/<int:eid>")
@login_required("admin")
def delete_ekspedisi(eid):
    e = Ekspedisi.query.get_or_404(eid)
    db.session.delete(e); db.session.commit()
    flash("Ekspedisi dihapus.", "info")
    return redirect(url_for("dashboard_admin"))


@app.route("/admin/pengaturan", methods=["POST"])
@login_required("admin")
def save_pengaturan():
    """Ubah DP, penambahan & pengaturan biaya-biaya (dashboard admin)."""
    set_setting("dp_persen", request.form.get("dp_persen", "20"), BIAYA_LABEL["dp_persen"])
    set_setting("biaya_penanganan_persen", request.form.get("biaya_penanganan_persen", "2"),
                BIAYA_LABEL["biaya_penanganan_persen"])
    set_setting("biaya_tambahan_flat", request.form.get("biaya_tambahan_flat", "0"),
                BIAYA_LABEL["biaya_tambahan_flat"])
    set_setting("biaya_verifikasi", request.form.get("biaya_verifikasi", "5000"),
                BIAYA_LABEL["biaya_verifikasi"])
    set_setting("biaya_iklan_produk", request.form.get("biaya_iklan_produk", "0"),
                BIAYA_LABEL["biaya_iklan_produk"])
    set_setting("ongkir_persen_asuransi", request.form.get("ongkir_persen_asuransi", "1"),
                BIAYA_LABEL["ongkir_persen_asuransi"])
    set_setting("min_transaksi", request.form.get("min_transaksi", "50000"),
                BIAYA_LABEL["min_transaksi"])
    for key in ("lelang_biaya_peserta", "lelang_biaya_penjual"):
        amount = _nonnegative_amount(request.form.get(key))
        if amount is None:
            flash("Biaya lelang harus berupa angka nol atau lebih.", "danger")
            return redirect(url_for("dashboard_admin"))
        set_setting(key, str(amount), BIAYA_LABEL[key])
    # custom biaya tambahan dinamis: biaya_baru_<n> / label_baru_<n>
    n = int(request.form.get("custom_count", "0"))
    for i in range(1, n + 1):
        key = request.form.get(f"key_hapus_{i}")
        if key and request.form.get(f"hapus_{i}"):
            p = Pengaturan.query.filter_by(key=key).first()
            if p:
                db.session.delete(p)
            continue
        lab = request.form.get(f"label_baru_{i}", "").strip()
        val = request.form.get(f"value_baru_{i}", "").strip()
        if lab and val:
            skey = f"biaya_custom_{i}"
            set_setting(skey, val, lab)
    db.session.commit()
    flash("Pengaturan ubah DP & biaya-biaya diperbarui ✔", "success")
    audit_current("pengaturan_biaya", "pengaturan", None, "perubahan konfigurasi platform")
    return redirect(url_for("dashboard_admin"))


@app.route("/penjual/pengaturan-pembayaran", methods=["POST"])
@login_required("penjual")
def save_seller_payment():
    """Penjual mengatur jenis pembayaran pelunasan DP: Tunai / Transfer Bank / Scan QRIS."""
    import json
    u = current_user()
    metode = request.form.getlist("metode_dp") or ["Transfer Bank"]
    cfg = {
        "metode_dp": metode,
        "rekening": request.form.get("rekening", "").strip(),
        "qris": request.form.get("qris", "").strip(),
        "tujuan_tunai": request.form.get("tujuan_tunai", u.alamat or "").strip(),
    }
    set_setting(f"pembayaran_penjual_{u.id}", json.dumps(cfg), f"Pengaturan pembayaran penjual #{u.id}")
    audit_current("pengaturan_metode_dp", "users", u.id, "metode pembayaran DP penjual: " + ",".join(metode))
    flash("Jenis pembayaran pelunasan DP disimpan ✔ (" + ", ".join(metode) + ")", "success")
    return redirect(url_for("dashboard_seller") + "#tSet")


@app.route("/penjual/pengaturan-lelang", methods=["POST"])
@login_required("penjual")
def save_seller_auction_settings():
    import json
    u = current_user()
    terms = request.form.get("syarat_ketentuan", "").strip()
    try:
        payment_hours = int(request.form.get("durasi_pembayaran_jam", "24"))
        pickup_hours = int(request.form.get("jadwal_pengambilan_jam", "0"))
    except (TypeError, ValueError):
        flash("Durasi harus berupa jumlah jam yang valid.", "danger")
        return redirect(url_for("dashboard_seller") + "#tAuctionSettings")
    if len(terms) > 5000 or not 1 <= payment_hours <= 720 or not 0 <= pickup_hours <= 720:
        flash("Syarat maksimal 5.000 karakter; tenggat pembayaran 1–720 jam dan jadwal pengambilan 0–720 jam.", "danger")
        return redirect(url_for("dashboard_seller") + "#tAuctionSettings")
    cfg = {"syarat_ketentuan": terms, "durasi_pembayaran_jam": payment_hours,
           "jadwal_pengambilan_jam": pickup_hours}
    set_setting(f"pengaturan_lelang_penjual_{u.id}", json.dumps(cfg),
                f"Pengaturan lelang penjual #{u.id}")
    audit_current("pengaturan_lelang_penjual", "users", u.id,
                  f"tenggat pembayaran {payment_hours} jam; jadwal pengambilan default {pickup_hours} jam")
    flash("Pengaturan lelang berhasil disimpan dan akan menjadi nilai awal event baru.", "success")
    return redirect(url_for("dashboard_seller") + "#tAuctionSettings")


@app.route("/admin/footer", methods=["POST"])
@login_required("admin")
def save_footer():
    """Pengaturan informasi footer landing page dari dashboard admin."""
    labels = {
        "footer_tentang": "Footer: Tentang AGR.ID",
        "footer_kontak": "Footer: Judul Kontak",
        "footer_alamat": "Footer: Alamat Kantor",
        "footer_email": "Footer: Email",
        "footer_telepon": "Footer: Telepon/WA",
        "footer_jam_operasional": "Footer: Jam Operasional",
        "footer_sosial": "Footer: Sosial Media",
        "footer_copyright": "Footer: Copyright",
        "footer_tautan": "Footer: Tautan Cepat",
    }
    for k, lab in labels.items():
        v = request.form.get(k)
        if v is not None:
            set_setting(k, v.strip(), lab)
    flash("Informasi footer landing page diperbarui ✔", "success")
    audit_current("pengaturan_footer", "pengaturan", None, "perubahan konfigurasi platform")
    return redirect(url_for("dashboard_admin"))


# ----------------------------------------------------------------------------
# ROUTES: KONFIGURASI CLOUD (Cloudinary & Supabase) — ADMIN
# ----------------------------------------------------------------------------

@app.route("/admin/konfigurasi-cloud", methods=["POST"])
@login_required("admin")
def save_konfigurasi_cloud():
    """Simpan kredensial Cloudinary (multimedia) & info koneksi Supabase.
    Nilai secret disimpan di tabel pengaturan (bukan filesystem) dan langsung
    mengaktifkan cloud_media tanpa restart."""
    cn = request.form.get("cloudinary_cloud_name", "").strip()
    ak = request.form.get("cloudinary_api_key", "").strip()
    se = request.form.get("cloudinary_api_secret", "").strip()
    pr = request.form.get("cloudinary_upload_preset", "").strip()
    set_setting("cloudinary_cloud_name", cn, "Cloudinary: Cloud Name")
    set_setting("cloudinary_api_key", ak, "Cloudinary: API Key")
    if se and "*" not in se:                        # jangan timpa mask saat submit ulang
        set_setting("cloudinary_api_secret", se, "Cloudinary: API Secret")
    set_setting("cloudinary_upload_preset", pr, "Cloudinary: Unsigned Upload Preset")
    cloud_media.set_override(cloud_name=cn, api_key=ak,
                             api_secret=(se if se and "*" not in se else None))
    if pr:
        os.environ["CLOUDINARY_UPLOAD_PRESET"] = pr

    # Auto-aktifkan toggle fitur storage cloud saat kredensial lengkap diisi,
    # agar seluruh upload user langsung diarahkan ke Cloudinary tanpa langkah manual.
    if cn and ak:
        set_setting("fitur_storage_cloud", "1")

    sb_url = request.form.get("supabase_db_url", "").strip()
    set_setting("supabase_db_url_masked", ("*"*8 + sb_url[-6:] if sb_url else ""), "Supabase: Connection String (masked)")
    set_setting("supabase_project_ref", request.form.get("supabase_project_ref", "").strip(), "Supabase: Project Ref")
    set_setting("frontend_base_url", request.form.get("frontend_base_url", "").strip(), "URL Frontend (InfinityFree)")
    flash("Konfigurasi cloud tersimpan ✔ (Cloudinary aktif tanpa restart; Supabase dipakai via env SUPABASE_DB_URL)", "success")
    audit_current("konfigurasi_cloud", "pengaturan", None, f"cloudinary={cn or '(kosong)'}, supabase_ref={request.form.get('supabase_project_ref','')}")
    return redirect(url_for("dashboard_admin") + "#tCloud")


@app.route("/api/v1/config")
def public_config():
    """Konfigurasi non-sensitif utk frontend statis (InfinityFree): daftar
    fitur aktif + parameter upload Cloudinary unsigned. TIDAK pernah
    mengembalikan api_secret / connection string."""
    feats = {k: fitur_on(k) for k in FEATURE_KEYS}
    cc = cloud_media.cfg()
    cloud_cfg = {"enabled": cloud_media.enabled(), "cloud_name": cc["cloud_name"],
                 "api_key": cc["api_key"] if cloud_media.enabled() else "",
                 "upload_preset": get_setting("cloudinary_upload_preset", "agr_unsigned"),
                 "endpoint_image": (f"https://api.cloudinary.com/v1_1/{cc['cloud_name']}/image/upload"
                                    if cc["cloud_name"] else "")}
    return jsonify(ok=True, features=feats, cloudinary=cloud_cfg,
                   db_backend=("supabase-postgres" if app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgres")
                               else "sqlite"),
                   dp_persen=get_setting("dp_persen", "20"))



# ----------------------------------------------------------------------------
# ROUTES: LAPORAN & PENGATURAN TAMPILAN LAPORAN (ADMIN) + FAVORIT (PEMBELI)
# ----------------------------------------------------------------------------

@app.route("/admin/pengaturan-laporan", methods=["POST"])
@login_required("admin")
def save_pengaturan_laporan():
    """Pengaturan untuk menampilkan laporan penjualan & pembelian di dashboard admin."""
    flags = {
        "laporan_tampil_penjualan": "Tampilkan Laporan Penjualan (sisi penjual)",
        "laporan_tampil_pembelian": "Tampilkan Laporan Pembelian (sisi pembeli)",
        "laporan_tampil_keuangan": "Tampilkan Rekap Laporan Keuangan",
        "laporan_detail_transaksi": "Tampilkan Tabel Detail Transaksi",
        "laporan_rekap_metode": "Tampilkan Rekap per Metode Pembayaran",
        "laporan_limit": "Jumlah baris laporan per tabel",
    }
    bool_keys = list(flags.keys())[:-1]
    for k in bool_keys:
        set_setting(k, "1" if request.form.get(k) else "0", flags[k])
    limit = request.form.get("laporan_limit", "50")
    try:
        limit = str(max(5, min(500, int(float(limit)))))
    except Exception:
        limit = "50"
    set_setting("laporan_limit", limit, flags["laporan_limit"])
    flash("Pengaturan tampilan laporan diperbarui ✔", "success")
    audit_current("pengaturan_laporan", "pengaturan", None, "perubahan konfigurasi platform")
    return redirect(url_for("dashboard_admin"))


@app.route("/admin/laporan/export")
@login_required("admin")
def export_laporan():
    """Export CSV laporan keuangan / penjualan / pembelian sesuai pengaturan."""
    import csv, io
    settings = {p.key: p.value for p in Pengaturan.query.all()}
    jenis = request.args.get("jenis", "keuangan")
    try:
        limit = int(settings.get("laporan_limit", "50"))
    except Exception:
        limit = 50
    tx = Transaksi.query.order_by(Transaksi.created_at.desc()).limit(limit).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    if jenis == "penjualan":
        if settings.get("laporan_tampil_penjualan", "1") != "1":
            return "Laporan penjualan dinonaktifkan admin.", 403
        w.writerow(["ID", "Tanggal", "Produk", "Qty", "Penjual", "Pembeli", "Nilai", "DP", "Pelunasan", "Fee", "Ongkir", "Status"])
        for t in tx:
            w.writerow([t.id, t.created_at, t.product_name, t.qty, t.seller.nama, t.buyer.nama,
                        int(t.nilai or 0), int(t.dp_dibayar or 0), int(t.pelunasan or 0),
                        int(t.biaya_penanganan or 0), int(t.ongkir or 0), t.status])
    elif jenis == "pembelian":
        if settings.get("laporan_tampil_pembelian", "1") != "1":
            return "Laporan pembelian dinonaktifkan admin.", 403
        w.writerow(["ID", "Tanggal", "Produk", "Qty", "Pembeli", "Penjual", "Nilai", "DP", "Pelunasan", "Metode", "Ref", "Status"])
        for t in tx:
            w.writerow([t.id, t.created_at, t.product_name, t.qty, t.buyer.nama, t.seller.nama,
                        int(t.nilai or 0), int(t.dp_dibayar or 0), int(t.pelunasan or 0),
                        t.metode_bayar, t.ref_payment, t.status])
    else:
        w.writerow(["ID", "Tanggal", "Produk", "Nilai", "DP Masuk", "Pelunasan", "Biaya Penanganan", "Ongkir", "Metode", "Ref Payment", "Status"])
        for t in tx:
            w.writerow([t.id, t.created_at, t.product_name, int(t.nilai or 0), int(t.dp_dibayar or 0),
                        int(t.pelunasan or 0), int(t.biaya_penanganan or 0), int(t.ongkir or 0),
                        t.metode_bayar, t.ref_payment, t.status])
    resp = app.response_class(buf.getvalue(), mimetype="text/csv")
    resp.headers["Content-Disposition"] = f"attachment; filename=laporan_{jenis}_agr_id.csv"
    return resp


@app.route("/favorit/toggle", methods=["POST"])
@feature_required("fitur_favorit")
@login_required("pembeli")
def toggle_favorit():
    """Simpan / hapus penjual atau produk favorit pembeli."""
    u = current_user()
    pid = request.form.get("product_id", type=int)
    sid = request.form.get("seller_id", type=int)
    prod = Product.query.get(pid) if pid else None
    if prod:
        sid = prod.seller_id
    if not sid:
        return jsonify(ok=False, error="seller tidak ditemukan"), 400
    fav = Favorite.query.filter_by(buyer_id=u.id, seller_id=sid,
                                   product_id=(pid if prod else None)).first()
    if fav:
        db.session.delete(fav)
        db.session.commit()
        state = False
    else:
        db.session.add(Favorite(buyer_id=u.id, seller_id=sid, product_id=(prod.id if prod else None)))
        db.session.commit()
        state = True
    if request.headers.get("X-Requested-With") == "fetch" or request.is_json:
        return jsonify(ok=True, favorited=state,
                       target="produk" if prod else "penjual")
    flash(("❤ Ditambahkan ke favorit" if state else "Dihapus dari favorit") +
          (f": {prod.nama_produk}" if prod else f": {User.query.get(sid).nama}"), "info")
    referer = request.form.get("next") or request.referrer
    return redirect(referer or url_for("marketplace"))


@app.route("/favorit/hapus/<int:fqid>")
@login_required("pembeli")
def hapus_favorit(fqid):
    f = Favorite.query.filter_by(id=fqid, buyer_id=current_user().id).first_or_404()
    db.session.delete(f)
    db.session.commit()
    flash("Favorit dihapus", "info")
    return redirect(request.referrer or url_for("dashboard_buyer"))

# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# ROUTES: KONFIGURASI FITUR (aktif/nonaktif terpusat) — ADMIN
# ----------------------------------------------------------------------------

@app.route("/admin/fitur", methods=["POST"])
@login_required("admin")
def save_fitur():
    """Mengaktifkan & menonaktifkan SEMUA fitur aplikasi dari konfigurasi admin."""
    for key, (label, _desc) in FEATURE_KEYS.items():
        set_setting(key, "1" if request.form.get(key) else "0", "Fitur: " + label)
    flash("Konfigurasi fitur diperbarui ✔ perubahan langsung berlaku di seluruh aplikasi.", "success")
    audit_current("pengaturan_fitur", "pengaturan", None, "aktif/nonaktif fitur platform")
    return redirect(url_for("dashboard_admin") + "#tFeat")


@app.route("/admin/crypto", methods=["POST"])
@login_required("admin")
def save_crypto_cfg():
    """Pengaturan blockchain: rasio kurs, fee jaringan, auto-settlement on-chain."""
    rate = request.form.get("crypto_rate_idr", "1")
    try:
        rate = str(max(1, float(rate)))
    except Exception:
        rate = "1"
    set_setting("crypto_rate_idr", rate, "Crypto: Kurs 1 AGR Coin (Rp)")
    fee = request.form.get("crypto_fee_persen", "0.5")
    try:
        fee = str(max(0.0, min(10.0, float(fee))))
    except Exception:
        fee = "0.5"
    set_setting("crypto_fee_persen", fee, "Crypto: Biaya Jaringan (%)")
    set_setting("crypto_auto_settle", "1" if request.form.get("crypto_auto_settle") else "0",
                "Crypto: Catat DP/pelunasan otomatis on-chain")
    flash("Pengaturan blockchain AGR Coin disimpan ✔", "success")
    audit_current("pengaturan_crypto", "pengaturan", None, "konfigurasi blockchain/dompet crypto")
    return redirect(url_for("dashboard_admin") + "#tChain")


# ----------------------------------------------------------------------------
# ROUTES: DOMPET CRYPTO (AGR COIN) — PENJUAL / PEMBELI
# ----------------------------------------------------------------------------

@app.route("/dompet")
@login_required("penjual", "pembeli")
def dompet_page():
    """Halaman dompet crypto user: alamat, saldo, riwayat transaksi on-chain."""
    u = current_user()
    if not fitur_on("fitur_blockchain"):
        flash("Fitur blockchain/crypto dinonaktifkan pada konfigurasi admin.", "warning")
        return redirect(url_for("dashboard"))
    w = wallet_ctx(u)
    peers = [x for x in User.query.filter(User.role != "admin", User.id != u.id).limit(200).all()
             if getattr(x, "crypto_address", None)]
    return render_template("wallet.html", user=u, u=u, wallet=w, peers=peers,
                           ticker=ticker_data())


@app.route("/dompet/transfer", methods=["POST"])
@login_required("penjual", "pembeli")
def dompet_transfer():
    """Transfer manual antar dompet AGR Coin (masuk mempool, ditambang validator)."""
    u = current_user()
    to_addr = request.form.get("ke", "").strip()
    if not to_addr and request.form.get("ke_uid"):
        to_addr = bchain.address_of(int(request.form["ke_uid"]))
    amount = request.form.get("jumlah", "0")
    memo = request.form.get("memo", "transfer antar member")
    ok, res = bchain.submit_transfer(bchain.address_of(u.id), to_addr, amount,
                                     ref=f"USER-{u.id}", memo=memo)
    if ok:
        mine_now = request.form.get("auto_mine")
        if mine_now:
            blk = bchain.mine(validator="node@agr.id")
            res += f" (blok #{blk['index']})"
        flash(f"Transfer {amount} AGR terkirim on-chain ✔ hash: {res[:24]}…", "success")
        audit_current("crypto_transfer", "users", u.id, f"transfer {amount} AGR ke {to_addr[:18]}…")
    else:
        flash("Gagal: " + res, "danger")
    return redirect(url_for("dompet_page"))


@app.route("/dompet/export-key", methods=["POST"])
@login_required("penjual", "pembeli")
def dompet_export_key():
    """Ekspor privat key terenkripsi (file) — konfirmasi password diperlukan."""
    from flask import make_response
    u = current_user()
    if not check_password_hash(u.password, request.form.get("password", "")):
        flash("Password salah — ekspor dibatalkan.", "danger")
        return redirect(url_for("dompet_page"))
    wallets = bchain._wallets()
    data = wallets.get(str(u.id))
    if not data:
        flash("Dompet belum tersedia.", "warning")
        return redirect(url_for("dompet_page"))
    blob = json.dumps({"address": data["address"], "priv_hex": data["priv_hex"],
                       "algo": data["algo"], "exported_at": datetime.utcnow().isoformat()}, indent=2)
    audit_current("crypto_key_export", "users", u.id, "ekspor privat key terenkripsi")
    resp = make_response(blob)
    resp.headers["Content-Type"] = "application/json"
    resp.headers["Content-Disposition"] = f"attachment; filename=agr-wallet-{u.id}.json"
    return resp


# ----------------------------------------------------------------------------
# ROUTES: BLOCKCHAIN EXPLORER & MINING — ADMIN
# ----------------------------------------------------------------------------

@app.route("/admin/blockchain/mine", methods=["POST"])
@login_required("admin")
def admin_mine_block():
    blk = bchain.mine(validator=current_user().email)
    flash(f"Blok #{blk['index']} berhasil ditambang (PoA) — {blk['tx_count']} transaksi, hash {blk['hash'][:16]}…", "success")
    audit_current("block_mined", "blockchain", blk["index"], f"mining blok oleh {current_user().email}")
    return redirect(url_for("dashboard_admin") + "#tChain")


@app.route("/admin/blockchain/verify")
@login_required("admin")
def admin_verify_chain():
    ok, msgs = bchain.verify_chain()
    flash(("✔ Integritas rantai TERVERIFIKASI: " if ok else "✖ RANTAI KORUP: ") + "; ".join(msgs),
          "success" if ok else "danger")
    audit_current("chain_verified", "blockchain", None, "; ".join(msgs))
    return redirect(url_for("dashboard_admin") + "#tChain")


@app.route("/api/v1/chain/blocks")
@login_required("admin")
def api_chain_blocks():
    c = bchain.chain()
    limit = int(request.args.get("limit", "20"))
    return jsonify(ok=True, stats=bchain.stats(),
                   blocks=[b.to_dict() for b in reversed(c.blocks[-limit:])])


@app.route("/api/v1/chain/tx/<hash>")
def api_chain_tx(hash):
    """Explorer publik: cari bukti transaksi on-chain berdasarkan hash (bila fitur aktif)."""
    if not fitur_on("fitur_blockchain") or not fitur_on("fitur_marketplace"):
        return jsonify(ok=False, error="fitur tidak aktif"), 403
    b, t = bchain.chain().find_tx(hash)
    if not t:
        return jsonify(ok=False, error="hash tidak ditemukan"), 404
    return jsonify(ok=True, block=b.index, block_hash=b.hash, tx=t.to_dict())


# ----------------------------------------------------------------------------
# ROUTES: AI CHAT
# ----------------------------------------------------------------------------

@app.route("/chat", methods=["GET"])
@feature_required("fitur_chat_agent")
@login_required("penjual", "pembeli")
def chat_page():
    u = current_user()
    hist = ChatMessage.query.filter_by(user_id=u.id).order_by(ChatMessage.created_at).all()
    return render_template("chat.html", hist=hist, user=u, ticker=ticker_data())


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(force=True) or {}
    text = data.get("message", "")
    u = current_user()
    reply = ai_reply(text, u)
    if u:
        db.session.add(ChatMessage(user_id=u.id, sender="user", text=text))
        db.session.add(ChatMessage(user_id=u.id, sender="ai", text=reply))
        db.session.commit()
    return jsonify({"reply": reply})

# ----------------------------------------------------------------------------
# JSON helpers for templates
# ----------------------------------------------------------------------------

@app.template_filter("rp")
def rp(v):
    try:
        return f"{int(float(v)):,}".replace(",", ".")
    except Exception:
        return v


@app.template_filter("dt")
def dtfmt(d):
    return d.strftime("%d %b %Y %H:%M") if d else "-"

# ----------------------------------------------------------------------------
# SEED DATABASE
# ----------------------------------------------------------------------------

def seed():
    is_sqlite = app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite")
    if is_sqlite and not os.path.exists(app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", "")):
        fresh = True
    else:
        fresh = User.query.first() is None if False else False
    with app.app_context():
        db.create_all()
        # --- migrasi ringan untuk DB lama: tambah kolom/tabel yang hilang ---
        try:
            from sqlalchemy import text
            from sqlalchemy import inspect as sa_inspect
            user_columns = {col["name"] for col in sa_inspect(db.engine).get_columns("users")}
            for column, ddl in [
                ("roles", "TEXT NOT NULL DEFAULT '[]'"),
                ("tipe_penjual", "VARCHAR(40)"),
                ("tipe_pembeli", "VARCHAR(40)"),
            ]:
                if column not in user_columns:
                    db.session.execute(text(f"ALTER TABLE users ADD COLUMN {column} {ddl}"))
            for account in User.query.all():
                account.roles = ["admin"] if account.role == "admin" else ["penjual", "pembeli"]
                if account.role == "penjual":
                    account.tipe_penjual = account.tipe_penjual or (account.tipe if account.tipe in TIPE_PENJUAL else TIPE_PENJUAL[0])
                    account.tipe_pembeli = account.tipe_pembeli or TIPE_PEMBELI[0]
                elif account.role == "pembeli":
                    account.tipe_pembeli = account.tipe_pembeli or (account.tipe if account.tipe in TIPE_PEMBELI else TIPE_PEMBELI[0])
                    account.tipe_penjual = account.tipe_penjual or TIPE_PENJUAL[0]
            if is_sqlite:   # PRAGMA hanya ada di SQLite; Postgres punya skema penuh dr create_all
                insp_cols = {c[1] for c in db.session.execute(text("PRAGMA table_info(bookings)"))}
                if "metode_dp" not in insp_cols:
                    db.session.execute(text("ALTER TABLE bookings ADD COLUMN metode_dp VARCHAR(30)"))
                insp_users = {c[1] for c in db.session.execute(text("PRAGMA table_info(users)"))}
                if "failed_logins" not in insp_users:
                    db.session.execute(text("ALTER TABLE users ADD COLUMN failed_logins INTEGER DEFAULT 0"))
                if "locked_until" not in insp_users:
                    db.session.execute(text("ALTER TABLE users ADD COLUMN locked_until DATETIME"))
                if "crypto_address" not in insp_users:
                    db.session.execute(text("ALTER TABLE users ADD COLUMN crypto_address VARCHAR(80)"))
            # kolom baru era blockchain/storage — cek per tabel (SQLite)
            for tbl, col, ddl in [
                ("users", "crypto_address", "VARCHAR(80)"),
                ("pengaturan", "label", "VARCHAR(120)"),
                ("products", "foto", "TEXT"),
                ("eviden", "foto", "TEXT"),
                ("transaksi", "pelunasan", "FLOAT"),
                ("transaksi", "chain_hash", "VARCHAR(80)"),
                ("bookings", "chain_hash", "VARCHAR(80)"),
            ]:
                try:
                    cols = {c[1] for c in db.session.execute(text(f"PRAGMA table_info({tbl})"))}
                    if cols and col not in cols:
                        db.session.execute(text(f"ALTER TABLE {tbl} ADD COLUMN {col} {ddl}"))
                except Exception as _e:
                    print("migrasi-col:", tbl, col, _e)
            # Perubahan model Offer harus tetap diterapkan pada SQLite maupun Postgres lama.
            from sqlalchemy import inspect as sa_inspect
            offer_columns = {c["name"] for c in sa_inspect(db.engine).get_columns("offers")}
            for col, ddl in [("harga_terkini", "FLOAT"), ("harga_disepakati", "FLOAT"),
                             ("batas_pembayaran", "TIMESTAMP")]:
                if col not in offer_columns:
                    db.session.execute(text(f"ALTER TABLE offers ADD COLUMN {col} {ddl}"))
            auction_schema_columns = {
                "kebutuhan_pembeli": [
                    ("product_id", "INTEGER"),
                ],
                "lelang_events": [
                    ("syarat_ketentuan", "TEXT NOT NULL DEFAULT ''"),
                    ("catatan_admin", "TEXT"), ("biaya_peserta", "FLOAT NOT NULL DEFAULT 0"),
                    ("biaya_penjual", "FLOAT NOT NULL DEFAULT 0"),
                    ("biaya_penjual_lunas", "BOOLEAN NOT NULL DEFAULT FALSE"),
                    ("ref_biaya_penjual", "VARCHAR(80)"), ("disetujui_pada", "TIMESTAMP"),
                    ("batas_bayar_pemenang", "TIMESTAMP"), ("jadwal_pengambilan", "TIMESTAMP"),
                    ("pemenang_id", "INTEGER"), ("harga_pemenang", "FLOAT"),
                    ("pemenang_bayar_lunas", "BOOLEAN NOT NULL DEFAULT FALSE"),
                    ("ref_bayar_pemenang", "VARCHAR(80)"),
                ],
                "lelang_participants": [
                    ("biaya_administrasi", "FLOAT NOT NULL DEFAULT 0"),
                    ("biaya_lunas", "BOOLEAN NOT NULL DEFAULT TRUE"),
                    ("ref_pembayaran", "VARCHAR(80)"), ("dibayar_pada", "TIMESTAMP"),
                ],
            }
            for table, columns in auction_schema_columns.items():
                existing = {col["name"] for col in sa_inspect(db.engine).get_columns(table)}
                for column, ddl in columns:
                    if column not in existing:
                        db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            db.session.commit()
        except Exception as e:
            print("migrasi:", e)
        if Pengaturan.query.count() == 0:
            set_setting("dp_persen", "20", "Persen DP Booking (%)")
            set_setting("biaya_penanganan_persen", "2", "Biaya Penanganan (%)")
            set_setting("biaya_tambahan_flat", "0", "Biaya Tambahan Flat (Rp)")
            set_setting("biaya_verifikasi", "5000", "Biaya Verifikasi Eviden (Rp)")
        # pastikan key biaya baru tersedia (untuk DB lama)
        for k, d in get_biaya_settings().items():
            if not Pengaturan.query.filter_by(key=k).first():
                set_setting(k, d, BIAYA_LABEL.get(k, k))
        # Default informasi footer landing page (dapat diubah di dashboard admin)
        FOOTER_DEFAULTS = {
            "footer_tentang": "Marketplace B2B/B2C pertanian, perkebunan, perikanan & peternakan. "
                              "Mempertemukan penjual & pembeli langsung dengan penawaran harga, booking DP, "
                              "payment gateway, ekspedisi, serta verifikasi & ketelusuran berbasis eviden foto + GPS.",
            "footer_kontak": "Hubungi Kami",
            "footer_alamat": "Jl. Pertanian Nusantara No. 1, Jakarta Selatan, DKI Jakarta 12345",
            "footer_email": "halo@agr.id",
            "footer_telepon": "+62 812-3456-7890 (WhatsApp)",
            "footer_jam_operasional": "Senin–Jumat 08.00–17.00 WIB · CS Toko 24/7",
            "footer_sosial": "Instagram: @agr.idofficial · Facebook: AGR.ID Marketplace · TikTok: @agr.id",
            "footer_copyright": "© 2026 AGR.ID — Dibuat untuk petani, nelayan & peternak Indonesia 🇮🇩",
            "footer_tautan": "Marketplace: /marketplace · Cara Kerja Booking DP: /marketplace · AI Chat Agent: /chat",
        }
        for k, v in FOOTER_DEFAULTS.items():
            if not Pengaturan.query.filter_by(key=k).first():
                set_setting(k, v, "Footer: " + k.replace("footer_", "").replace("_", " ").title())
        # Default pengaturan tampilan laporan (dashboard admin)
        LAPORAN_DEFAULTS = {
            "laporan_tampil_penjualan": ("1", "Tampilkan Laporan Penjualan (sisi penjual)"),
            "laporan_tampil_pembelian": ("1", "Tampilkan Laporan Pembelian (sisi pembeli)"),
            "laporan_tampil_keuangan": ("1", "Tampilkan Rekap Laporan Keuangan"),
            "laporan_detail_transaksi": ("1", "Tampilkan Tabel Detail Transaksi"),
            "laporan_rekap_metode": ("1", "Tampilkan Rekap per Metode Pembayaran"),
            "laporan_limit": ("50", "Jumlah baris laporan per tabel"),
        }
        for k, (v, lab) in LAPORAN_DEFAULTS.items():
            if not Pengaturan.query.filter_by(key=k).first():
                set_setting(k, v, lab)
        if Ekspedisi.query.count() == 0:
            db.session.add_all([
                Ekspedisi(nama="JNE Trucking", base_url="https://jne.co.id/api/v1", api_key="", account_id="", service_types="reguler,kargo", tarif_per_kg=8500),
                Ekspedisi(nama="SiCepat HALO", base_url="https://sicepat.ai/api/v2", api_key="", account_id="", service_types="same day,reguler", tarif_per_kg=12000),
                Ekspedisi(nama="AGRAKATA Kargo Nusantara", base_url="https://agrakata.example/api", api_key="", account_id="", service_types="kargo laut,darat", tarif_per_kg=5500),
            ])
            db.session.commit()
        if PaymentGatewayAPI.query.count() == 0:
            db.session.add(PaymentGatewayAPI(provider="Midtrans Core API",
                base_url="https://app.midtrans.com/snap/v1", api_key="", server_key="",
                client_key="", webhook_secret="", enabled=True))
            db.session.commit()
        # Seed produk master dari masterdata; tambahkan juga kategori baru ke DB lama.
        known_master_names = {r[0].lower() for r in db.session.query(ProdukMaster.nama).all()}
        added_master = False
        for row in flatten_products():
            if row["nama_produk"].lower() in known_master_names:
                continue
            db.session.add(ProdukMaster(nama=row["nama_produk"], kategori=row["kategori"],
                                        subkategori=row["subkategori"], jenis=row["jenis"],
                                        non_halal=row["non_halal"]))
            known_master_names.add(row["nama_produk"].lower())
            added_master = True
        if added_master:
            db.session.commit()
        # Demo accounts
        if User.query.count() == 0:
            admin = User(nama="Admin AGR.ID", email="admin@agr.id",
                         password=generate_password_hash("admin123"), role="admin",
                         tipe="Perorangan", roles=["admin"],
                         tipe_penjual=TIPE_PENJUAL[0], tipe_pembeli=TIPE_PEMBELI[0],
                         verified=True, kota="Jakarta", provinsi="DKI Jakarta")
            seller = User(nama="Pak Budi Tani", email="penjual@agr.id",
                          password=generate_password_hash("penjual123"), role="penjual",
                          tipe="Kelompok/Paguyuban", roles=["penjual", "pembeli"],
                          tipe_penjual="Kelompok/Paguyuban", tipe_pembeli=TIPE_PEMBELI[0],
                          alamat="Desa Cikarang, Kab. Brebes",
                          kota="Brebes", provinsi="Jawa Tengah", lat=-6.866, lng=109.055, verified=True)
            seller2 = User(nama="Koperasi Mina Laut", email="koperasi@agr.id",
                           password=generate_password_hash("penjual123"), role="penjual",
                           tipe="Koperasi", roles=["penjual", "pembeli"],
                           tipe_penjual="Koperasi", tipe_pembeli="Koperasi",
                           alamat="Pelabuhan Pekalongan", kota="Pekalongan",
                           provinsi="Jawa Tengah", lat=-6.889, lng=109.675, verified=True)
            buyer = User(nama="Siti Pembeli", email="pembeli@agr.id",
                         password=generate_password_hash("pembeli123"), role="pembeli",
                         tipe="Perorangan", roles=["penjual", "pembeli"],
                         tipe_penjual=TIPE_PENJUAL[0], tipe_pembeli="Perorangan",
                         alamat="Jl. Merdeka 12, Bandung", kota="Bandung",
                         provinsi="Jawa Barat", lat=-6.914, lng=107.609, verified=True)
            corp = User(nama="PT Segar Food Industry", email="corporate@agr.id",
                        password=generate_password_hash("corporate123"), role="pembeli",
                        tipe="Perusahaan", roles=["penjual", "pembeli"],
                        tipe_penjual="Perusahaan", tipe_pembeli="Perusahaan",
                        alamat="Kawasan Industri GIIC", kota="Tangerang",
                        provinsi="Banten", lat=-6.238, lng=106.62, npwp="01.234.567.8-901.000",
                        nib="1234567890123", verified=True)
            db.session.add_all([admin, seller, seller2, buyer, corp])
            db.session.commit()
            # Demo products
            demo = [
                Product(seller_id=seller.id, nama_produk="Cabai Merah Keriting", jenis="Keriting",
                        kategori="Pertanian", subkategori="Sayuran",
                        deskripsi="Panaman harian, grade A, sortir tangkai. Kemasan karung 20kg / box 10kg.",
                        harga=41000, satuan="kg", stok=850,
                        alamat_lahan="Desa cikimbang, Brebes", lat=-6.866, lng=109.055,
                        sertifikasi="Prima 3 - Pestiside Residue Test"),
                Product(seller_id=seller.id, nama_produk="Bawang Merah", jenis="Lokal",
                        kategori="Pertanian", subkategori="Sayuran",
                        deskripsi="Bawang merah super rendeng, kadar air rendah, tahan simpan.",
                        harga=32500, satuan="kg", stok=1200, lat=-6.87, lng=109.06,
                        alamat_lahan="Brebes - Jawa Tengah"),
                Product(seller_id=seller.id, nama_produk="Durian Musang King", jenis="Musang King",
                        kategori="Pertanian", subkategori="Buah-buahan",
                        deskripsi="Grade A, 3.5-4.5 kg/buah, jatuh matang pohon.",
                        harga=92000, satuan="kg", stok=320, lat=-7.0, lng=110.4,
                        sertifikasi="Organik Nusantara"),
                Product(seller_id=seller2.id, nama_produk="Lele Sangkuriang", jenis="Sangkuriang",
                        kategori="Perikanan", subkategori="Air Tawar",
                        deskripsi="Ukuran 7-9 cm/ekor siap konsumsi, pakan pelet murni, bebas bau tanah.",
                        harga=19000, satuan="kg", stok=2500, lat=-6.889, lng=109.675,
                        alamat_lahan="Kolam TPI Copalang, Pekalongan"),
                Product(seller_id=seller2.id, nama_produk="Udang Vaname", jenis="Beku Size 40",
                        kategori="Perikanan", subkategori="Air Laut",
                        deskripsi="Headless shell-on beku, size 40, glazing 70%, cold chain terjaga.",
                        harga=76000, satuan="kg", stok=1800, lat=-6.89, lng=109.68),
                Product(seller_id=seller.id, nama_produk="Kambing PE 76", jenis="PE 76 Jantan",
                        kategori="Peternakan", subkategori="Kambing & Domba",
                        deskripsi="Kambing kacang peranakan etawa jantan, umur 10-12 bln, bobot 25-30kg. SKKH lengkap.",
                        harga=3100000, satuan="ekor", stok=45, lat=-6.95, lng=109.1,
                        sertifikasi="SKKH & Vaksin PMK"),
                Product(seller_id=seller2.id, nama_produk="Babi Landrace", jenis="Landrace",
                        kategori="Peternakan", subkategori="Babi",
                        deskripsi="Babi bakalan hidup 60-70 kg, asal peternakan legal Bali/Nusra.",
                        harga=2800000, satuan="ekor", stok=18, non_halal=True,
                        alamat_lahan="Peternakan registered, Nusa Tenggara Timur", lat=-10.17, lng=123.60),
                Product(seller_id=seller.id, nama_produk="Kopi Arabika Gayo", jenis="Gayo Fullwash",
                        kategori="Perkebunan", subkategori="Tanaman Tahunan",
                        deskripsi="Green bean grade 1, defect max 3%, lot panen 2026, warehouse Takengon.",
                        harga=94000, satuan="kg", stok=5200, lat=4.6, lng=96.85,
                        sertifikasi="Indikasi Geografis Gayo"),
            ]
            db.session.add_all(demo)
            db.session.commit()
            # Demo offer + transaksi selesai utk laporan
            o = Offer(product_id=demo[0].id, buyer_id=buyer.id, qty=100,
                      harga_penawaran=40000, total=4_000_000, pesan="Butuh rutin mingguan",
                      status="selesai")
            db.session.add(o); db.session.commit()
            b = Booking(offer_id=o.id, dp_persen=20, dp_amount=800000, sisa_bayar=3200000,
                        biaya_penanganan=80000, jadwal_kirim=date.today() + timedelta(days=3),
                        ekspedisi_id=1, status="selesai")
            db.session.add(b); db.session.commit()
            t = Transaksi(offer_id=o.id, booking_id=b.id, seller_id=seller.id, buyer_id=buyer.id,
                          product_name="Cabai Merah Keriting", qty=100, nilai=4_000_000,
                          dp_dibayar=800000, pelunasan=3200000, biaya_penanganan=80000,
                          ongkir=850000, metode_bayar="qris", ref_payment="PGX-DEMO-0001",
                          status="completed", created_at=datetime.utcnow() - timedelta(days=2),
                          completed_at=datetime.utcnow())
            db.session.add(t); db.session.commit()
            db.session.add_all([
                Eviden(transaksi_id=t.id, tahap="panen", keterangan="Panen blok C-4, sortasi awal",
                       lat=-6.866, lng=109.055, uploaded_by=seller.id),
                Eviden(transaksi_id=t.id, tahap="pengemasan", keterangan="Box ventilasi 20kg x5",
                       lat=-6.866, lng=109.055, uploaded_by=seller.id),
                Eviden(transaksi_id=t.id, tahap="penerimaan", keterangan="Diterima gudang Bandung, quality OK",
                       lat=-6.914, lng=107.609, uploaded_by=buyer.id),
            ])
            db.session.commit()
            # Demo penilaian kepuasan dua arah (pembeli->penjual & penjual->pembeli)
            db.session.add_all([
                Rating(transaksi_id=t.id, from_user_id=buyer.id, to_user_id=seller.id,
                       arah="ke_penjual", score=5,
                       aspek=json.dumps({"kualitas": 5, "pengemasan": 4, "komunikasi": 5, "jadwal": 5}),
                       komentar="Cabai segar sesuai grade A, eviden panen & GPS lengkap, kirim tepat jadwal."),
                Rating(transaksi_id=t.id, from_user_id=seller.id, to_user_id=buyer.id,
                       arah="ke_pembeli", score=4,
                       aspek=json.dumps({"ketepatan_bayar": 5, "komunikasi": 4, "kejelasan": 4}),
                       komentar="Pembayaran DP & pelunasan lancar, spesifikasi pesanan jelas."),
            ])
            db.session.commit()


# ----------------------------------------------------------------------------
# BLUEPRINT: REST API v1 + manajemen token API (keamanan & performa di security.py)
# ----------------------------------------------------------------------------
import api_v1
app.register_blueprint(api_v1.api_bp)
api_v1.register_admin_token_routes(app)

# BLUEPRINT: Cloud Object Storage (pre-signed direct upload, bucket public/private)
import storage_api
app.register_blueprint(storage_api.storage_bp)


def audit_current(action, entity=None, entity_id=None, detail=""):
    """Helper: catat aksi penting ke log audit dengan konteks user/IP saat ini."""
    u = current_user()
    try:
        models_api.AuditLog.record(action, actor=(u.email if u else "anonim"),
                                   role=(u.active_role if u else "-"), user_id=(u.id if u else None),
                                   entity=entity, entity_id=entity_id, detail=detail,
                                   ip=security.client_ip())
    except Exception as e:
        print("audit:", e)


if __name__ == "__main__":
    seed()
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("AGR_DEBUG", "").lower() in ("1", "true")
    threaded = True                      # dukung request bersamaan
    print(f"AGR.ID berjalan pada http://0.0.0.0:{port} "
          f"[env={os.environ.get('AGR_ENV', 'development')}, debug={debug}]")
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=threaded)
