# -*- coding: utf-8 -*-
"""AGR.ID - REST API v1 (penyediaan API untuk integrasi eksternal).

Autentikasi: header  Authorization: Bearer <token>  (token dibuat admin di dashboard,
lihat tabel api_tokens; token disimpan sebagai hash SHA-256).

Endpoint publik tanpa token (untuk widget/landing):
  GET /api/v1/health        : status sistem & metrik performa
  GET /api/v1/kategori      : daftar kategori & sub kategori
  GET /api/v1/produk-master : master nama produk (cari ?q=)
  GET /api/v1/ticker        : harga pasar komoditas
  GET /api/v1/chat          : - (POST saja, rate limited)

Endpoint ber-token:
  GET  /api/v1/products                 : listing produk (?kategori=&q=&page=)
  GET  /api/v1/products/<id>            : detail produk + penjual (disamarkan)
  POST /api/v1/products                 : [penjual/admin] buat produk
  GET  /api/v1/offers?product_id=       : [read/penjual/admin] penawaran utk produk
  POST /api/v1/offers                   : [pembeli via sesi ATAU read/admin token] buat penawaran
  GET  /api/v1/bookings                 : [admin/penjual/pembeli] daftar booking
  GET  /api/v1/transaksi                : [admin] laporan transaksi + ringkasan keuangan
  GET  /api/v1/audit                    : [admin] log audit (?action=&limit=)
  POST /api/v1/webhook/payment          : callback payment gateway (verifikasi HMAC secret)
  POST /api/v1/chat                     : AI chat agent (rate limited per IP)

Manajemen token (sesi admin + CSRF, bukan bagian API publik):
  POST /admin/api-token   {nama, role, expiry_days}
  POST /admin/api-token/revoke/<id>
"""
import json
import os
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, request, session

import models_api
import security
from security import api_token_required, client_ip, hash_token

api_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")


def _ok(**kw):
    body = {"ok": True}
    body.update(kw)
    return jsonify(body)


def _err(msg, code=400):
    return jsonify(ok=False, error=msg), code


def _db():
    from app import db
    return db


def _user():
    from app import User
    uid = session.get("uid")
    return User.query.get(uid) if uid else None


# ---------------------------------------------------------------------------
# Publik
# ---------------------------------------------------------------------------
@api_bp.route("/health")
def health():
    """Status sistem & metrik performa ringan."""
    from app import Transaksi, Product, Offer, Booking, User
    import time
    t0 = time.time()
    counts = dict(
        users=User.query.count(),
        products=Product.query.filter_by(status="aktif").count(),
        offers=Offer.query.count(),
        bookings=Booking.query.count(),
        transaksi=Transaksi.query.count(),
    )
    return _ok(
        status="sehat",
        waktu=datetime.now().isoformat(timespec="seconds"),
        latency_ms=round((time.time() - t0) * 1000, 1),
        env=os.environ.get("AGR_ENV", "development"),
        jumlah=counts,
    )


@api_bp.route("/kategori")
def kategori():
    from masterdata import KATEGORI, NON_HALAL_LABEL
    out = []
    for k, subs in KATEGORI.items():
        out.append({
            "kategori": k,
            "subkategori": [
                {"nama": s, "non_halal": (k == "Peternakan" and s == NON_HALAL_LABEL)}
                for s in subs
            ],
        })
    return _ok(data=out)


@api_bp.route("/produk-master")
def produk_master():
    from app import ProdukMaster
    q = (request.args.get("q") or "").strip().lower()
    kat = (request.args.get("kategori") or "").strip()
    page = max(int(request.args.get("page", 1)), 1)
    per = min(int(request.args.get("per_page", 50)), 200)
    query = ProdukMaster.query
    if q:
        query = query.filter(ProdukMaster.nama.ilike(f"%{q}%"))
    if kat:
        query = query.filter(ProdukMaster.kategori == kat)
    total = query.count()
    rows = query.order_by(ProdukMaster.nama).paginate(page=page, per_page=per, error_out=False)
    return _ok(total=total, page=page, per_page=per, data=[
        {"nama": p.nama, "kategori": p.kategori, "subkategori": p.subkategori,
         "jenis": (p.jenis or "").split(","), "non_halal": bool(p.non_halal)}
        for p in rows.items])


@api_bp.route("/ticker")
def ticker():
    from app import ticker_data
    return _ok(data=ticker_data())


# ---------------------------------------------------------------------------
# Ber-token: katalog & transaksi
# ---------------------------------------------------------------------------
@api_bp.route("/products")
@api_token_required()
def list_products():
    from app import Product
    kat = request.args.get("kategori")
    sub = request.args.get("subkategori")
    q = request.args.get("q")
    hide_haram = request.args.get("sembunyikan_non_halal") in ("1", "true")
    page = max(int(request.args.get("page", 1)), 1)
    per = min(int(request.args.get("per_page", 20)), 100)
    query = Product.query.filter_by(status="aktif")
    if kat:
        query = query.filter(Product.kategori == kat)
    if sub:
        query = query.filter(Product.subkategori == sub)
    if q:
        query = query.filter(Product.nama_produk.ilike(f"%{q}%"))
    if hide_haram:
        query = query.filter(Product.non_halal.is_(False))
    total = query.count()
    rows = query.order_by(Product.created_at.desc()).paginate(page=page, per_page=per, error_out=False)
    return _ok(total=total, page=page, per_page=per, data=[
        {"id": p.id, "nama": p.nama_produk, "jenis": p.jenis, "kategori": p.kategori,
         "subkategori": p.subkategori, "harga": p.harga, "satuan": p.satuan, "stok": p.stok,
         "seller": p.seller.nama, "seller_tipe": p.seller.tipe, "non_halal": bool(p.non_halal),
         "foto": p.foto, "created_at": p.created_at.isoformat(timespec="seconds")}
        for p in rows.items])


@api_bp.route("/products/<int:pid>")
@api_token_required()
def product_detail(pid):
    from app import Product
    p = Product.query.get_or_404(pid)
    return _ok(data={
        "id": p.id, "nama": p.nama_produk, "jenis": p.jenis, "kategori": p.kategori,
        "subkategori": p.subkategori, "deskripsi": p.deskripsi, "harga": p.harga,
        "satuan": p.satuan, "stok": p.stok, "non_halal": bool(p.non_halal),
        "sertifikasi": p.sertifikasi, "alamat_lahan": p.alamat_lahan,
        "gps": {"lat": p.lat, "lng": p.lng}, "foto": p.foto,
        "penjual": {"nama": p.seller.nama, "tipe": p.seller.tipe,
                    "kota": p.seller.kota, "verified": bool(p.seller.verified)},
    })


@api_bp.route("/products", methods=["POST"])
@api_token_required(roles=["penjual", "admin"])
def create_product():
    from app import Product, ProdukMaster
    d = request.get_json(silent=True) or {}
    required = ["nama_produk", "harga"]
    missing = [k for k in required if not d.get(k)]
    if missing:
        return _err(f"Field wajib hilang: {', '.join(missing)}")
    tok = getattr(security.g, "api_token", None)
    # tentukan seller: dari body seller_id (admin) atau token penjual -> pakai penjual pertama aktif
    from app import User
    seller = None
    if tok and tok.role == "admin" and d.get("seller_id"):
        seller = User.query.get(d["seller_id"])
    else:
        seller = User.query.filter_by(role="penjual").order_by(User.id).first()
    if not seller:
        return _err("Penjual tidak ditemukan", 404)
    p = Product(
        seller_id=seller.id, nama_produk=str(d["nama_produk"])[:120],
        jenis=d.get("jenis"), kategori=d.get("kategori"), subkategori=d.get("subkategori"),
        deskripsi=d.get("deskripsi"), harga=float(d["harga"]), satuan=d.get("satuan", "kg"),
        stok=float(d.get("stok", 0)), foto=d.get("foto"), alamat_lahan=d.get("alamat_lahan"),
        lat=float(d["lat"]) if d.get("lat") else None,
        lng=float(d["lng"]) if d.get("lng") else None,
        non_halal=bool(d.get("non_halal")), sertifikasi=d.get("sertifikasi"),
    )
    db = _db()
    db.session.add(p)
    # auto-update database produk master
    pm = ProdukMaster.query.filter(db.func.lower(ProdukMaster.nama) == str(d["nama_produk"]).lower()).first()
    if not pm:
        db.session.add(ProdukMaster(nama=str(d["nama_produk"])[:120], kategori=p.kategori,
                                   subkategori=p.subkategori, jenis=p.jenis or "",
                                   non_halal=p.non_halal, auto_added=True))
    db.session.commit()
    models_api.AuditLog.record("api_produk_dibuat", actor=f"token:{tok.nama if tok else '?'}",
                               entity="products", entity_id=p.id, detail=p.nama_produk, ip=client_ip())
    return _ok(id=p.id, message="Produk tersimpan via API"), 201


@api_bp.route("/offers")
@api_token_required(roles=["penjual", "admin"])
def list_offers():
    from app import Offer, Product
    pid = request.args.get("product_id", type=int)
    seller_id = request.args.get("seller_id", type=int)
    query = Offer.query
    if seller_id:
        prod_ids = [x.id for x in Product.query.filter_by(seller_id=seller_id).all()]
        query = query.filter(Offer.product_id.in_(prod_ids or [0]))
    elif pid:
        query = query.filter(Offer.product_id == pid)
    rows = query.order_by(Offer.created_at.desc()).limit(200).all()
    return _ok(data=[
        {"id": o.id, "product_id": o.product_id, "produk": o.product.nama_produk,
         "pembeli": o.buyer.nama, "qty": o.qty, "harga_penawaran": o.harga_penawaran,
         "total": o.total, "status": o.status, "created_at": o.created_at.isoformat(timespec="seconds")}
        for o in rows])


@api_bp.route("/offers", methods=["POST"])
@api_token_required()
def create_offer():
    from app import Offer, Product
    d = request.get_json(silent=True) or {}
    p = Product.query.get(d.get("product_id") or 0)
    if not p:
        return _err("product_id tidak valid", 404)
    qty = float(d.get("qty") or 0)
    harga = float(d.get("harga_penawaran") or 0)
    if qty <= 0 or harga <= 0:
        return _err("qty dan harga_penawaran harus > 0")
    buyer_id = d.get("buyer_id")
    from app import User
    buyer = User.query.get(buyer_id) if buyer_id else User.query.filter_by(role="pembeli").order_by(User.id).first()
    if not buyer:
        return _err("Pembeli tidak ditemukan", 404)
    o = Offer(product_id=p.id, buyer_id=buyer.id, qty=qty, harga_penawaran=harga, total=qty * harga)
    db = _db()
    db.session.add(o)
    db.session.commit()
    tok = getattr(security.g, "api_token", None)
    models_api.AuditLog.record("api_penawaran_dibuat", actor=f"token:{tok.nama if tok else '?'}",
                               entity="offers", entity_id=o.id,
                               detail=f"{p.nama_produk} x{qty}", ip=client_ip())
    return _ok(id=o.id, total=o.total), 201


@api_bp.route("/bookings")
@api_token_required(roles=["penjual", "admin"])
def list_bookings():
    from app import Booking
    rows = Booking.query.order_by(Booking.created_at.desc()).limit(200).all()
    return _ok(data=[
        {"id": b.id, "offer_id": b.offer_id, "dp": b.dp_amount, "total": b.sisa_bayar + b.dp_amount,
         "status": b.status, "jadwal_kirim": str(b.jadwal_kirim), "metode_dp": b.metode_dp,
         "created_at": b.created_at.isoformat(timespec="seconds")}
        for b in rows])


@api_bp.route("/transaksi")
@api_token_required(roles=["admin"])
def list_transaksi():
    from app import Transaksi
    status = request.args.get("status")
    query = Transaksi.query
    if status:
        query = query.filter(Transaksi.status == status)
    rows = query.order_by(Transaksi.created_at.desc()).limit(500).all()
    total_gmv = sum(t.nilai or 0 for t in rows)
    fee = sum(t.biaya_penanganan or 0 for t in rows)
    return _ok(ringkasan={"jumlah": len(rows), "gmv": total_gmv, "pendapatan_platform": fee}, data=[
        {"id": t.id, "produk": t.product_name, "penjual": t.seller.nama, "pembeli": t.buyer.nama,
         "qty": t.qty, "total": t.nilai, "dp": t.dp_dibayar, "sisa": (t.nilai or 0) - (t.dp_dibayar or 0),
         "status": t.status, "metode_bayar": t.metode_bayar, "ref_payment": t.ref_payment,
         "created_at": t.created_at.isoformat(timespec="seconds")}
        for t in rows])


@api_bp.route("/audit")
@api_token_required(roles=["admin"])
def audit_logs():
    action = request.args.get("action")
    limit = min(request.args.get("limit", 100, type=int), 500)
    query = models_api.AuditLog.query
    if action:
        query = query.filter(models_api.AuditLog.action == action)
    rows = query.order_by(models_api.AuditLog.ts.desc()).limit(limit).all()
    return _ok(data=[{"ts": r.ts.isoformat(timespec="seconds") if r.ts else None,
                      "actor": r.actor, "action": r.action, "entity": r.entity,
                      "entity_id": r.entity_id, "detail": r.detail, "ip": r.ip} for r in rows])


# ---------------------------------------------------------------------------
# Webhook payment gateway (HMAC signature)
# ---------------------------------------------------------------------------
@api_bp.route("/webhook/payment", methods=["POST"])
def webhook_payment():
    """Callback PG: validasi X-Signature = HMAC-SHA256(body, webhook_secret)."""
    from app import PaymentGatewayAPI, Booking, Transaksi
    raw = request.get_data()
    sig = request.headers.get("X-Signature", "")
    pg = PaymentGatewayAPI.query.filter_by(enabled=True).first()
    secret = (pg.webhook_secret if pg else None) or os.environ.get("AGR_WEBHOOK_SECRET", "")
    if not secret:
        return _err("Webhook secret belum dikonfigurasi", 503)
    import hmac as _hmac
    calc = _hmac.new(secret.encode(), raw, "sha256").hexdigest()
    if not _hmac.compare_digest(calc, sig):
        models_api.AuditLog.record("webhook_ditolak", actor="payment-gateway", detail="signature invalid", ip=client_ip())
        return _err("Signature tidak valid", 401)
    try:
        payload = json.loads(raw.decode() or "{}")
    except Exception:
        return _err("Body JSON tidak valid")
    ref = payload.get("reference") or payload.get("merchant_ref") or payload.get("order_id")
    status = (payload.get("status") or payload.get("transaction_status") or "").lower()
    # ref payment tersimpan di Transaksi.ref_payment (dibuat saat booking dibayar)
    t = Transaksi.query.filter_by(ref_payment=ref).first() if ref else None
    if not t:
        return _err(f"Transaksi dengan reference '{ref}' tidak ditemukan", 404)
    db = _db()
    b = Booking.query.get(t.booking_id) if t.booking_id else None
    if status in ("settlement", "capture", "success", "paid"):
        if t.status == "processing":
            t.status = "paid"
            if b and b.status == "dp_pending":
                b.status = "dp_lunas"
            models_api.AuditLog.record("webhook_dp_lunas", actor="payment-gateway",
                                       entity="transaksi", entity_id=t.id, detail=f"ref={ref}", ip=client_ip())
    elif status in ("expired", "failed", "cancel"):
        if t.status in ("processing", "paid"):
            t.status = "cancelled"
            if b and b.status in ("dp_pending", "dp_lunas"):
                b.status = "batal"
            models_api.AuditLog.record("webhook_dp_gagal", actor="payment-gateway",
                                       entity="transaksi", entity_id=t.id, detail=f"ref={ref} status={status}", ip=client_ip())
    db.session.commit()
    return _ok(message="Webhook diproses", transaksi_id=t.id, status=t.status)


# ---------------------------------------------------------------------------
# Chat AI publik (rate limited)
# ---------------------------------------------------------------------------
@api_bp.route("/chat", methods=["POST"])
def chat():
    if not security.chat_limiter.allow(client_ip()):
        return _err("Terlalu banyak permintaan, coba lagi sebentar.", 429)
    d = request.get_json(silent=True) or {}
    msg = (d.get("message") or "").strip()[:1000]
    if not msg:
        return _err("Pesan kosong")
    from app import ai_reply, ChatMessage
    u = _user()
    reply = ai_reply(msg, u)
    if u:
        db = _db()
        db.session.add(ChatMessage(user_id=u.id, sender="user", text=msg))
        db.session.add(ChatMessage(user_id=u.id, sender="ai", text=reply))
        db.session.commit()
    return _ok(reply=reply)


# ---------------------------------------------------------------------------
# Manajemen token API (dashboard admin - sesi + CSRF)
# ---------------------------------------------------------------------------
def register_admin_token_routes(app):
    from app import login_required

    @app.route("/admin/api-token", methods=["POST"])
    @login_required("admin")
    def create_api_token():
        nama = (request.form.get("nama") or "Token").strip()[:80]
        role = request.form.get("role") or "read"
        days = request.form.get("expiry_days", type=int)
        if role not in ("read", "penjual", "admin"):
            role = "read"
        raw = "agr_" + secrets.token_urlsafe(32)
        rec = models_api.ApiToken(
            nama=nama, token_hash=hash_token(raw), role=role,
            created_by=session.get("email", "admin"),
            expires_at=datetime.utcnow() + timedelta(days=days) if days else None,
        )
        _db().session.add(rec)
        _db().session.commit()
        models_api.AuditLog.record("token_api_dibuat", actor=session.get("email"), role="admin",
                                   entity="api_tokens", entity_id=rec.id, detail=f"{nama} ({role})", ip=client_ip())
        return jsonify(ok=True, token=raw, id=rec.id,
                       message="Simpan token ini sekarang - tidak dapat ditampilkan ulang.")

    @app.route("/admin/api-token/revoke/<int:tid>", methods=["POST"])
    @login_required("admin")
    def revoke_api_token(tid):
        rec = models_api.ApiToken.query.get_or_404(tid)
        rec.revoked = True
        _db().session.commit()
        models_api.AuditLog.record("token_api_dicabut", actor=session.get("email"), role="admin",
                                   entity="api_tokens", entity_id=tid, detail=rec.nama, ip=client_ip())
        return jsonify(ok=True)
