# -*- coding: utf-8 -*-
"""
AGR.ID - Marketplace Pertanian, Perkebunan, Perikanan & Peternakan
Dukungan AI Chat Agent, penawaran harga, booking DP, payment gateway,
ekspedisi, verifikasi & ketelusuran (traceability) dengan bukti eviden.
"""
import os
import json
import random
from datetime import datetime, timedelta, date
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"),
            static_folder=os.path.join(BASE_DIR, "static"))
app.secret_key = "agrid-secret-key-2026"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "agrid.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

from masterdata import KATEGORI, TIPE_PENJUAL, TIPE_PEMBELI, MASTER_PRODUK, NON_HALAL_LABEL, flatten_products

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
    tipe = db.Column(db.String(40))                          # Perorangan/Koperasi/Paguyuban atau Perorangan/Corporate
    alamat = db.Column(db.Text)
    kota = db.Column(db.String(80))
    provinsi = db.Column(db.String(80))
    lat = db.Column(db.Float)                                # koordinat GPS
    lng = db.Column(db.Float)
    npwp = db.Column(db.String(30))                          # untuk corporate
    nib = db.Column(db.String(40))                           # nomor induk berusaha (corporate/koperasi)
    verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    products = db.relationship("Product", backref="seller", lazy=True)


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
    status = db.Column(db.String(20), default="menunggu")    # menunggu/diterima/ditolak/booking/lunas/selesai/batal
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
    jadwal_kirim = db.Column(db.Date)
    ekspedisi_id = db.Column(db.Integer, db.ForeignKey("ekspedisi.id"))
    tracking_code = db.Column(db.String(60))
    status = db.Column(db.String(20), default="dp_pending")  # dp_pending/dp_lunas/dikirim/diterima/selesai/batal
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    offer = db.relationship("Offer", backref="bookings")
    ekspedisi = db.relationship("Ekspedisi")


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
    """Pengaturan biaya tambahan platform (dashboard admin)."""
    __tablename__ = "pengaturan"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(60), unique=True)
    value = db.Column(db.String(120))
    label = db.Column(db.String(120))


class ChatMessage(db.Model):
    """Riwayat chat AI agent (bantuan input produk & pencarian produk)."""
    __tablename__ = "chat_messages"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    sender = db.Column(db.String(10))      # user / ai
    text = db.Column(db.Text)
    payload = db.Column(db.Text)           # JSON opsional (hasil pencarian/form wizard)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


def get_setting(key, default=None):
    p = Pengaturan.query.filter_by(key=key).first()
    return p.value if p else default


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
    return ("Saya 🤖 AGR Assistant. Contoh perintah:\n"
            "- \"cara jual cabai\" → pandu wizard input produk\n"
            "- \"cari ikan gurame\" → cari listing pembeli-ready\n"
            "- \"sistem DP booking\" → penjelasan transaksi\n"
            "- \"daftar ekspedisi\" → mitra kirim aktif")

# ----------------------------------------------------------------------------
# AUTH HELPERS
# ----------------------------------------------------------------------------

def current_user():
    uid = session.get("uid")
    return User.query.get(uid) if uid else None


def login_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            u = current_user()
            if not u:
                flash("Silakan login terlebih dahulu.", "warning")
                return redirect(url_for("login"))
            if roles and u.role not in roles:
                flash("Akses ditolak untuk role Anda.", "danger")
                return redirect(url_for("login"))
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
                           ticker=ticker_data(), user=current_user())


@app.route("/marketplace")
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
    return render_template("marketplace.html", products=prods, categories=KATEGORI,
                           subs=subs, q=q, kat=kat, sub=sub, hide_nonhalal=hide_nonhalal,
                           ticker=ticker_data(), user=current_user())


@app.route("/produk/<int:pid>")
def product_detail(pid):
    p = Product.query.get_or_404(pid)
    evidences = Eviden.query.join(Transaksi).filter(Transaksi.offer_id.in_(
        [o.id for o in p.offers])).limit(6).all()
    return render_template("product.html", p=p, evidences=evidences, user=current_user(),
                           ticker=ticker_data())


@app.route("/register", methods=["GET", "POST"])
def register():
    role = request.args.get("role", request.form.get("role", "pembeli"))
    if request.method == "POST":
        role = request.form.get("role", "pembeli")
        email = request.form.get("email", "").strip().lower()
        if User.query.filter_by(email=email).first():
            flash("Email sudah terdaftar.", "danger")
            return redirect(url_for("register", role=role))
        tipe_list = TIPE_PENJUAL if role == "penjual" else TIPE_PEMBELI
        u = User(
            nama=request.form.get("nama", "").strip(),
            email=email,
            password=generate_password_hash(request.form.get("password", "")),
            phone=request.form.get("phone", ""),
            role=role,
            tipe=request.form.get("tipe", tipe_list[0]),
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
        session["uid"] = u.id
        flash(f"Pendaftaran berhasil sebagai {role.title()}! Selamat datang di AGR.ID 🌾", "success")
        return redirect(url_for("dashboard"))
    return render_template("register.html", role=role, tipe_penjual=TIPE_PENJUAL,
                           tipe_pembeli=TIPE_PEMBELI, user=current_user())


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = User.query.filter_by(email=request.form.get("email", "").strip().lower()).first()
        if u and check_password_hash(u.password, request.form.get("password", "")):
            session["uid"] = u.id
            return redirect(url_for("dashboard"))
        flash("Email / password salah.", "danger")
    return render_template("login.html", user=current_user())


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

# ----------------------------------------------------------------------------
# ROUTES: DASHBOARD (penjual / pembeli / admin)
# ----------------------------------------------------------------------------

@app.route("/dashboard")
@login_required("penjual", "pembeli", "admin")
def dashboard():
    u = current_user()
    if u.role == "penjual":
        return redirect(url_for("dashboard_seller"))
    if u.role == "admin":
        return redirect(url_for("dashboard_admin"))
    return redirect(url_for("dashboard_buyer"))


@app.route("/dashboard/penjual")
@login_required("penjual")
def dashboard_seller():
    u = current_user()
    my_prods = Product.query.filter_by(seller_id=u.id).order_by(Product.created_at.desc()).all()
    my_offers = Offer.query.filter(Offer.product_id.in_([p.id for p in my_prods] or [-1])).order_by(Offer.created_at.desc()).all()
    jualan = Transaksi.query.filter_by(seller_id=u.id).order_by(Transaksi.created_at.desc()).all()
    omzet = sum(t.nilai for t in jualan if t.status in ("paid", "shipped", "delivered", "completed"))
    return render_template("seller_dashboard.html", u=u, products=my_prods, offers=my_offers,
           penjualan=jualan, omzet=omzet, user=u, ticker=ticker_data(),
           categories=MASTER_PRODUK)


@app.route("/dashboard/pembeli")
@login_required("pembeli")
def dashboard_buyer():
    u = current_user()
    my_offers = Offer.query.filter_by(buyer_id=u.id).order_by(Offer.created_at.desc()).all()
    pembelian = Transaksi.query.filter_by(buyer_id=u.id).order_by(Transaksi.created_at.desc()).all()
    total_belanja = sum(t.nilai for t in pembelian if t.status in ("paid", "shipped", "delivered", "completed"))
    return render_template("buyer_dashboard.html", u=u, offers=my_offers, pembelian=pembelian,
                           total=total_belanja, user=u, ticker=ticker_data())


@app.route("/dashboard/admin")
@login_required("admin")
def dashboard_admin():
    u = current_user()
    tx = Transaksi.query.order_by(Transaksi.created_at.desc()).all()
    revenue = sum((t.biaya_penanganan or 0) for t in tx)
    pg = PaymentGatewayAPI.query.all()
    eks = Ekspedisi.query.all()
    settings = {p.key: p.value for p in Pengaturan.query.all()}
    stats = {
        "users": User.query.count(),
        "penjual": User.query.filter_by(role="penjual").count(),
        "pembeli": User.query.filter_by(role="pembeli").count(),
        "produk": Product.query.count(),
        "master": ProdukMaster.query.count(),
        "transaksi": len(tx),
        "gmv": sum(t.nilai for t in tx),
        "revenue": revenue,
    }
    return render_template("admin_dashboard.html", u=u, stats=stats, tx=tx, pg=pg, eks=eks,
                           settings=settings, user=u, ticker=ticker_data())

# ----------------------------------------------------------------------------
# ROUTES: PRODUK (CRUD + auto-add master)
# ----------------------------------------------------------------------------

@app.route("/produk/baru", methods=["GET", "POST"])
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
@login_required("pembeli")
def create_offer(pid):
    p = Product.query.get_or_404(pid)
    u = current_user()
    qty = float(request.form.get("qty") or 0)
    harga = float(request.form.get("harga_penawaran") or 0)
    if qty <= 0 or harga <= 0:
        flash("Jumlah & harga penawaran harus > 0", "danger")
        return redirect(url_for("product_detail", pid=pid))
    o = Offer(product_id=pid, buyer_id=u.id, qty=qty, harga_penawaran=harga,
              total=qty * harga, pesan=request.form.get("pesan", ""))
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
    if act == "terima":
        o.status = "diterima"
        db.session.commit()
        return redirect(url_for("show_booking_form", oid=o.id))
    if act == "tolak":
        o.status = "ditolak"
        db.session.commit()
        flash("Penawaran ditolak.", "info")
    return redirect(url_for("dashboard_seller"))


@app.route("/booking/<int:oid>", methods=["GET", "POST"])
@login_required("pembeli")
def show_booking_form(oid):
    o = Offer.query.get_or_404(oid)
    if o.buyer_id != current_user().id:
        flash("Tidak berwenang.", "danger"); return redirect(url_for("dashboard_buyer"))
    if o.status not in ("diterima", "booking"):
        flash("Penawaran belum diterima penjual.", "warning")
        return redirect(url_for("dashboard_buyer"))
    dp_persen = float(get_setting("dp_persen", "20"))
    fee_persen = float(get_setting("biaya_penanganan_persen", "2"))
    dp_amount = round(o.total * dp_persen / 100, 0)
    fee = round(o.total * fee_persen / 100, 0)
    sisa = round(o.total - dp_amount, 0)
    eks_list = Ekspedisi.query.filter_by(enabled=True).all()
    if request.method == "POST":
        jadwal = request.form.get("jadwal_kirim")
        eks_id = request.form.get("ekspedisi_id") or None
        b = Booking(offer_id=o.id, dp_persen=dp_persen, dp_amount=dp_amount,
                    sisa_bayar=sisa, biaya_penanganan=fee,
                    jadwal_kirim=datetime.strptime(jadwal, "%Y-%m-%d").date() if jadwal else None,
                    ekspedisi_id=eks_id, status="dp_pending")
        db.session.add(b)
        o.status = "booking"
        db.session.commit()
        return redirect(url_for("pay_booking", bid=b.id))
    return render_template("booking_form.html", o=o, dp_persen=dp_persen, fee_persen=fee_persen,
                           dp_amount=dp_amount, fee=fee, sisa=sisa, eks_list=eks_list,
                           user=current_user(), ticker=ticker_data())


@app.route("/booking/<int:bid>/bayar", methods=["GET", "POST"])
@login_required("pembeli")
def pay_booking(bid):
    """Simulasi payment gateway: QRIS/VA/E-wallet/Bank Transfer."""
    b = Booking.query.get_or_404(bid)
    o = b.offer
    if o.buyer_id != current_user().id:
        flash("Tidak berwenang.", "danger"); return redirect(url_for("dashboard_buyer"))
    pg_active = PaymentGatewayAPI.query.filter_by(enabled=True).first()
    channels = (pg_active.channels.split(",") if pg_active else ["qris", "virtual_account", "ewallet", "bank_transfer"])
    ref = "PGX-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + str(random.randint(1000, 9999))
    if request.method == "POST":
        method = request.form.get("metode")
        b.status = "dp_lunas"
        o.status = "booking"
        t = Transaksi(offer_id=o.id, booking_id=b.id, seller_id=Product.query.get(o.product_id).seller_id,
                      buyer_id=o.buyer_id, product_name=o.product.nama_produk, qty=o.qty,
                      nilai=o.total, dp_dibayar=b.dp_amount, biaya_penanganan=b.biaya_penanganan,
                      metode_bayar=method, ref_payment=ref, status="processing")
        db.session.add(t)
        db.session.commit()
        flash(f"DP {int(b.dp_amount):,} berhasil dibayar via {method.upper()} 🎉 Ref: {ref}", "success")
        return redirect(url_for("dashboard_buyer"))
    return render_template("payment.html", b=b, o=o, channels=channels, ref=ref,
                           pg=pg_active, user=current_user(), ticker=ticker_data())


@app.route("/transaksi/<int:tid>/eviden", methods=["GET", "POST"])
@login_required("penjual", "pembeli")
def add_eviden(tid):
    t = Transaksi.query.get_or_404(tid)
    u = current_user()
    if u.role not in ("penjual", "pembeli") or (t.seller_id != u.id and t.buyer_id != u.id):
        flash("Tidak berwenang.", "danger"); return redirect(url_for("dashboard"))
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
    if u.role == "penjual" and t.seller_id != u.id:
        flash("Tidak berwenang.", "danger"); return redirect(url_for("dashboard"))
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
    set_setting("dp_persen", request.form.get("dp_persen", "20"), "Persen DP Booking (%)")
    set_setting("biaya_penanganan_persen", request.form.get("biaya_penanganan_persen", "2"), "Biaya Penanganan (%)")
    set_setting("biaya_tambahan_flat", request.form.get("biaya_tambahan_flat", "0"), "Biaya Tambahan Flat (Rp)")
    set_setting("biaya_verifikasi", request.form.get("biaya_verifikasi", "5000"), "Biaya Verifikasi Eviden (Rp)")
    flash("Pengaturan biaya & DP diperbarui ✔", "success")
    return redirect(url_for("dashboard_admin"))

# ----------------------------------------------------------------------------
# ROUTES: AI CHAT
# ----------------------------------------------------------------------------

@app.route("/chat", methods=["GET"])
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
    if not os.path.exists(app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", "")):
        fresh = True
    else:
        fresh = User.query.first() is None if False else False
    with app.app_context():
        db.create_all()
        if Pengaturan.query.count() == 0:
            set_setting("dp_persen", "20", "Persen DP Booking (%)")
            set_setting("biaya_penanganan_persen", "2", "Biaya Penanganan (%)")
            set_setting("biaya_tambahan_flat", "0", "Biaya Tambahan Flat (Rp)")
            set_setting("biaya_verifikasi", "5000", "Biaya Verifikasi Eviden (Rp)")
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
        # Seed produk master dari masterdata
        if ProdukMaster.query.count() == 0:
            for row in flatten_products():
                db.session.add(ProdukMaster(nama=row["nama_produk"], kategori=row["kategori"],
                                            subkategori=row["subkategori"], jenis=row["jenis"],
                                            non_halal=row["non_halal"]))
            db.session.commit()
        # Demo accounts
        if User.query.count() == 0:
            admin = User(nama="Admin AGR.ID", email="admin@agr.id",
                         password=generate_password_hash("admin123"), role="admin",
                         tipe="Perorangan", verified=True, kota="Jakarta", provinsi="DKI Jakarta")
            seller = User(nama="Pak Budi Tani", email="penjual@agr.id",
                          password=generate_password_hash("penjual123"), role="penjual",
                          tipe="Kelompok Tani (Paguyuban)", alamat="Desa Cikarang, Kab. Brebes",
                          kota="Brebes", provinsi="Jawa Tengah", lat=-6.866, lng=109.055, verified=True)
            seller2 = User(nama="Koperasi Mina Laut", email="koperasi@agr.id",
                           password=generate_password_hash("penjual123"), role="penjual",
                           tipe="Koperasi", alamat="Pelabuhan Pekalongan", kota="Pekalongan",
                           provinsi="Jawa Tengah", lat=-6.889, lng=109.675, verified=True)
            buyer = User(nama="Siti Pembeli", email="pembeli@agr.id",
                         password=generate_password_hash("pembeli123"), role="pembeli",
                         tipe="Perorangan", alamat="Jl. Merdeka 12, Bandung", kota="Bandung",
                         provinsi="Jawa Barat", lat=-6.914, lng=107.609, verified=True)
            corp = User(nama="PT Segar Food Industry", email="corporate@agr.id",
                        password=generate_password_hash("corporate123"), role="pembeli",
                        tipe="Corporate", alamat="Kawasan Industri GIIC", kota="Tangerang",
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


if __name__ == "__main__":
    seed()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
