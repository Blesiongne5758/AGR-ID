# -*- coding: utf-8 -*-
"""AGR.BIZ.ID - Keamanan sistem.

Cakupan:
  * Secret key & session cookie hardening (HttpOnly, SameSite, Secure)
  * Proteksi CSRF global untuk semua POST (kecuali endpoint API ber-token)
  * Rate limiting login berbasis memori
  * Lockout akun setelah N kali gagal login
  * Validasi password kuat + policy
  * Header keamanan HTTP (X-Frame-Options, CSP, HSTS, dll.)
  * Masking API key di respons/log
  * Token API sederhana untuk REST API (dikelola admin)
"""
import hashlib
import hmac
import os
import re
import secrets
import time
from functools import wraps
from threading import Lock

from flask import g, jsonify, request, session, abort

# ---------------------------------------------------------------------------
# Session / cookie hardening config (dipakai app.py saat init)
# ---------------------------------------------------------------------------
def session_config(app):
    """Terapkan konfigurasi keamanan session/cookie Flask."""
    secret = os.environ.get("AGR_SECRET_KEY")
    if not secret:
        # fallback stabil per-instalasi: simpan di file .secret_key
        path = os.path.join(app.root_path, ".secret_key")
        if os.path.exists(path):
            secret = open(path).read().strip()
        else:
            secret = secrets.token_hex(32)
            try:
                with open(path, "w") as f:
                    f.write(secret)
                os.chmod(path, 0o600)
            except OSError:
                pass
        app.config["_AGR_FALLBACK_SECRET"] = True
    app.secret_key = secret
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("AGR_ENV") == "production",
        PERMANENT_SESSION_LIFETIME=1800,          # 30 menit idle timeout
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,       # batas upload 8 MB
    )


# ---------------------------------------------------------------------------
# CSRF token
# ---------------------------------------------------------------------------
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


CSRF_EXEMPT_PATHS = {"/api/v1"}   # prefix yang memakai token, bukan sesi+CSRF


def init_security(app, login_endpoint="login"):
    """Pasang hook CSRF + header keamanan + context csrf untuk template."""

    @app.context_processor
    def _inject_csrf():
        return {"csrf_token": csrf_token}

    @app.before_request
    def _csrf_protect():
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return None
        # API JSON versi 1 dilindungi token, bukan sesi
        if request.path.startswith("/api/v1"):
            return None
        tok = request.form.get("_csrf") or request.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(str(tok), str(session.get("_csrf", ""))):
            if request.is_json:
                return jsonify(ok=False, error="CSRF token tidak valid"), 400
            abort(400, description="CSRF token tidak valid. Muat ulang halaman.")
        return None

    @app.after_request
    def _security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "geolocation=(self)")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; font-src 'self' data:; frame-ancestors 'self'",
        )
        if os.environ.get("AGR_ENV") == "production":
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp


# ---------------------------------------------------------------------------
# Rate limiting (in-memory, thread-safe)
# ---------------------------------------------------------------------------
class RateLimiter:
    def __init__(self, max_req=10, window=60):
        self.max_req, self.window = max_req, window
        self._hits = {}
        self._lock = Lock()

    def allow(self, key):
        now = time.time()
        with self._lock:
            arr = [t for t in self._hits.get(key, []) if now - t < self.window]
            if len(arr) >= self.max_req:
                self._hits[key] = arr
                return False
            arr.append(now)
            self._hits[key] = arr
            return True

    def reset(self, key):
        with self._lock:
            self._hits.pop(key, None)


login_limiter = RateLimiter(max_req=10, window=60)      # 10 percobaan / menit / IP
chat_limiter = RateLimiter(max_req=30, window=60)       # anti spam chat/API publik


def client_ip():
    fwd = request.headers.get("X-Forwarded-For", "")
    return fwd.split(",")[0].strip() if fwd else (request.remote_addr or "unknown")


# ---------------------------------------------------------------------------
# Lockout akun
# ---------------------------------------------------------------------------
MAX_FAILED = 5
LOCK_SECONDS = 15 * 60


def register_failed_login(user):
    user.failed_logins = (user.failed_logins or 0) + 1
    if user.failed_logins >= MAX_FAILED:
        from datetime import datetime, timedelta
        user.locked_until = datetime.utcnow() + timedelta(seconds=LOCK_SECONDS)


def clear_failed_login(user):
    user.failed_logins = 0
    user.locked_until = None


def is_locked(user):
    from datetime import datetime
    return bool(user.locked_until and user.locked_until > datetime.utcnow())


def lock_remaining_min(user):
    from datetime import datetime
    if not is_locked(user):
        return 0
    delta = (user.locked_until - datetime.utcnow()).total_seconds()
    return int(delta // 60) + 1


# ---------------------------------------------------------------------------
# Password policy
# ---------------------------------------------------------------------------
_PWD_UPPER = re.compile(r"[A-Z]")
_PWD_LOWER = re.compile(r"[a-z]")
_PWD_DIGIT = re.compile(r"\d")


def check_password_strength(pw):
    """Return list pesan kelemahan (kosong = lolos policy)."""
    errs = []
    if not pw or len(pw) < 8:
        errs.append("Password minimal 8 karakter.")
    if pw and not (_PWD_UPPER.search(pw or "") and _PWD_LOWER.search(pw or "")):
        errs.append("Password harus mengandung huruf besar dan kecil.")
    if pw and not _PWD_DIGIT.search(pw or ""):
        errs.append("Password harus mengandung angka.")
    common = {"password", "12345678", "qwerty", "admin123", "agr.id", "petani123"}
    if pw and pw.lower() in common:
        errs.append("Password terlalu umum.")
    return errs


# ---------------------------------------------------------------------------
# Masking API key utk tampilan/log
# ---------------------------------------------------------------------------
def mask_key(k):
    if not k:
        return "-"
    k = str(k)
    if len(k) <= 8:
        return "*" * len(k)
    return k[:4] + "*" * (len(k) - 8) + k[-4:]


# ---------------------------------------------------------------------------
# Token API untuk /api/v1 (header Authorization: Bearer <token>)
# ---------------------------------------------------------------------------
def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def api_token_required(roles=None):
    """Decorator: verifikasi bearer token dari tabel ApiToken (models_api.ApiToken)."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            import models_api
            hdr = request.headers.get("Authorization", "")
            token = hdr[7:] if hdr.startswith("Bearer ") else request.args.get("token", "")
            if not token:
                return jsonify(ok=False, error="Token API wajib diisi (Authorization: Bearer)"), 401
            th = hash_token(token)
            rec = models_api.ApiToken.query.filter_by(token_hash=th, revoked=False).first()
            if not rec:
                return jsonify(ok=False, error="Token API tidak valid / dicabut"), 403
            from datetime import datetime
            if rec.expires_at and rec.expires_at < datetime.utcnow():
                return jsonify(ok=False, error="Token API kedaluwarsa"), 403
            if rec.role == "koperasi" and request.path != "/api/v1/cooperatives/sync":
                return jsonify(ok=False, error="Token ini hanya dapat menyinkronkan direktori koperasi"), 403
            if roles and rec.role != "admin" and rec.role not in roles:
                return jsonify(ok=False, error="Token tidak punya hak akses ini"), 403
            rec.last_used = datetime.utcnow()
            rec.use_count = (rec.use_count or 0) + 1
            try:
                from app import db as _appdb
                _appdb.session.commit()
            except Exception:
                pass
            g.api_token = rec
            return fn(*a, **kw)
        return wrapper
    return decorator
