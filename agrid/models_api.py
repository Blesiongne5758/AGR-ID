# -*- coding: utf-8 -*-
"""AGR.ID - Model tambahan backend (keamanan, audit, token API).

Model inti (User, Product, Offer, Booking, Transaksi, dst.) tetap di app.py.
File ini menambah tabel pendukung untuk keamanan & manajemen data:
  * AuditLog      : jejak aktivitas penting (login, transaksi, perubahan pengaturan)
  * ApiToken      : bearer token utk REST API /api/v1 (disimpan sebagai hash SHA-256)
  * LoginAttempt  : log percobaan login (sukses/gagal) utk deteksi anomali
"""
from datetime import datetime


_ = None  # diisi lewat init_models(db)


def init_models(db):
    """Definisikan model dengan db SQLAlchemy yang diberikan (hindari circular import)."""
    global _
    _ = db

    class AuditLog(db.Model):
        __tablename__ = "audit_logs"
        id = db.Column(db.Integer, primary_key=True)
        ts = db.Column(db.DateTime, default=datetime.utcnow, index=True)
        user_id = db.Column(db.Integer, index=True)
        actor = db.Column(db.String(40))            # email/sistem
        role = db.Column(db.String(20))
        action = db.Column(db.String(60), index=True)   # login, booking_dibuat, pembayaran, ...
        entity = db.Column(db.String(40))               # transaksi/produk/pengaturan
        entity_id = db.Column(db.Integer)
        detail = db.Column(db.Text)                     # ringkasan JSON/plain
        ip = db.Column(db.String(60))

        @staticmethod
        def record(action, actor=None, role=None, user_id=None, entity=None,
                   entity_id=None, detail="", ip=""):
            rec = AuditLog(action=action, actor=actor or "sistem", role=role or "",
                           user_id=user_id, entity=entity, entity_id=entity_id,
                           detail=(detail or "")[:2000], ip=ip)
            db.session.add(rec)
            db.session.commit()
            return rec

    class ApiToken(db.Model):
        __tablename__ = "api_tokens"
        id = db.Column(db.Integer, primary_key=True)
        nama = db.Column(db.String(80), nullable=False)     # label, mis. "Mobile App"
        token_hash = db.Column(db.String(64), unique=True, nullable=False)
        role = db.Column(db.String(20), default="read")      # read/penjual/admin
        created_by = db.Column(db.String(120))
        created_at = db.Column(db.DateTime, default=datetime.utcnow)
        expires_at = db.Column(db.DateTime)
        revoked = db.Column(db.Boolean, default=False)
        last_used = db.Column(db.DateTime)
        use_count = db.Column(db.Integer, default=0)

    class LoginAttempt(db.Model):
        __tablename__ = "login_attempts"
        id = db.Column(db.Integer, primary_key=True)
        ts = db.Column(db.DateTime, default=datetime.utcnow, index=True)
        email = db.Column(db.String(120), index=True)
        success = db.Column(db.Boolean, default=False)
        ip = db.Column(db.String(60))
        ua = db.Column(db.String(200))

    globals()["AuditLog"] = AuditLog
    globals()["ApiToken"] = ApiToken
    globals()["LoginAttempt"] = LoginAttempt
    return AuditLog, ApiToken, LoginAttempt


def get_api_token_model():
    if _ is None:
        raise RuntimeError("init_models(db) belum dipanggil")
    from models_api import ApiToken  # noqa - setelah init, kelas sudah ada di globals
    return ApiToken
