# -*- coding: utf-8 -*-
"""
AGR.BIZ.ID - Cloudinary Media Integration (cloudinary.com)
======================================================
Penyimpanan & optimasi file multimedia (foto produk, avatar, eviden, dokumen)
didelegasikan ke Cloudinary — TIDAK ada file di filesystem web server.

Dua mode kerja:
1. UNSIGNED (default untuk hosting shared seperti InfinityFree yang tidak bisa
   menjalankan backend): klien mengirim file langsung ke endpoint
   /image/upload atau /auto/upload milik Cloudinary memakai API key + upload
   preset (unsigned). Kredensial hanya berupa public "api_key" + preset nama —
   aman dipublikasikan selama preset membatasi folder & tipe file.
2. SIGNED (untuk backend Flask/Railway/Render): signature SHA-1 dibuat server
   dari CLOUDINARY_URL, dipakai bersama policy bucket private di storage.py.

Semua nilai dibaca dari environment; dapat dioverride lewat dashboard admin
(kunci pengaturan cloudinary_* — lihat app.py route /admin/konfigurasi-cloud).
"""
import os
import re
import time
import hashlib

CLOUDINARY_URL = os.environ.get("CLOUDINARY_URL", "")      # cloudinary://key:secret@cloud_name
_CLOUD_CFG = {"cloud_name": "", "api_key": "", "api_secret": ""}

if CLOUDINARY_URL:
    _m = re.match(r"cloudinary://(?P<api>[^:]*):(?P<sec>[^@]*)@(?P<cloud>[^/]*)", CLOUDINARY_URL)
    if _m:
        _CLOUD_CFG = {"cloud_name": _m.group("cloud"), "api_key": _m.group("api"),
                      "api_secret": _m.group("sec")}


def cfg():
    """Konfigurasi aktif (env > override DB diisi oleh app.py via set_override)."""
    return dict(_CLOUD_CFG)


def set_override(cloud_name=None, api_key=None, api_secret=None):
    """Dipanggil dari dashboard admin bila kredensial disimpan di tabel pengaturan."""
    if cloud_name is not None:
        _CLOUD_CFG["cloud_name"] = cloud_name.strip()
    if api_key is not None:
        _CLOUD_CFG["api_key"] = api_key.strip()
    if api_secret is not None:
        _CLOUD_CFG["api_secret"] = api_secret.strip()


def enabled():
    c = cfg()
    return bool(c["cloud_name"] and c["api_key"])


def signed_enabled():
    c = cfg()
    return bool(c["cloud_name"] and c["api_key"] and c["api_secret"])


def unsigned_endpoint(folder="agr.id"):
    """Endpoint direct-upload tanpa signature (untuk frontend statis InfinityFree)."""
    resource = "auto" if folder in ("docs", "chat", "kyc") else "image"
    c = cfg()
    return f"https://api.cloudinary.com/v1_1/{c['cloud_name']}/{resource}/upload"


def public_params(folder="products", preset=None, max_bytes=None):
    """Parameter form untuk POST langsung dari browser ke Cloudinary (unsigned)."""
    c = cfg()
    p = {
        "cloud_name": c["cloud_name"],
        "api_key": c["api_key"],
        "folder": f"agr.id/{folder}",
        "upload_preset": preset or os.environ.get("CLOUDINARY_UPLOAD_PRESET", "agr_unsigned"),
        "timestamp": int(time.time()),
    }
    if max_bytes:
        p["max_file_size"] = max_bytes
    if folder in ("products", "eviden", "avatar"):          # foto listing publik
        p.update({"access_mode": "public"})
    return p


def sign_params(params):
    """Tambahkan signature SHA-1 (mode SIGNED, dipakai backend saat secret tersedia)."""
    c = cfg()
    to_sign = "&".join(f"{k}={params[k]}" for k in sorted(params)
                       if k in ("folder", "public_id", "timestamp", "type",
                                "effect", "tags", "access_mode", "eager"))
    sig = hashlib.sha1((to_sign + c["api_secret"]).encode()).hexdigest()
    out = dict(params)
    out["signature"] = sig
    out["api_key"] = c["api_key"]
    return out


def optimized_url(public_id_or_url, width=800, format_auto=True):
    """URL dengan transformasi f_auto (WebP/AVIF) + q_auto (kompresi cerdas)."""
    c = cfg()
    if not c["cloud_name"]:
        return public_id_or_url
    if public_id_or_url.startswith("https://res.cloudinary.com"):
        # sisipkan transform setelah /image/upload/
        return re.sub(r"/(image|video|raw)/upload/",
                      rf"/\1/upload/f_auto,q_auto,w_{width}/",
                      public_id_or_url) if format_auto else public_id_or_url
    t = f"f_auto,q_auto,w_{width}" if format_auto else f"w_{width}"
    return f"https://res.cloudinary.com/{c['cloud_name']}/image/upload/{t}/{public_id_or_url}"


def thumb_url(public_id_or_url, width=300):
    return optimized_url(public_id_or_url, width=width)


def secure_download_url(public_id, expires_in=60):
    """Pre-signed GET berumur pendek utk aset 'private' (type authenticated /
    raw + token). Digunakan utk dokumen KYC/bukti transfer setelah verifikasi
    kepemilikan/status transaksi oleh backend (lihat storage_api._access_ok)."""
    c = cfg()
    exp = int(time.time()) + expires_in
    to_sign = f"encrypted_expiration={exp}&folder=agr.id/private&public_id={public_id}"
    sig = hashlib.sha1((to_sign + c["api_secret"]).encode()).hexdigest()
    return (f"https://res.cloudinary.com/{c['cloud_name']}/image/authenticated/"
            f"{sig}/{to_sign.replace('&', '/')[:0]}{public_id}"  # path dasar
            f"?Expires={exp}")


def probe():
    """Cek koneksi ke Cloudinary (dipakai tombol 'Uji Koneksi' di admin)."""
    import json
    try:
        from urllib.request import urlopen, Request
        import base64
        c = cfg()
        if not c["api_key"]:
            return {"ok": False, "error": "API key belum diisi"}
        auth = base64.b64encode(f"{c['api_key']}:{c['api_secret']}".encode()).decode()
        req = Request(f"https://api.cloudinary.com/v1_1/{c['cloud_name']}/resources/image",
                      headers={"Authorization": f"Basic {auth}"})
        with urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        return {"ok": True, "cloud_name": c["cloud_name"],
                "total_resource": len(data.get("resources", []))}
    except Exception as e:
        return {"ok": False, "error": str(e)}
