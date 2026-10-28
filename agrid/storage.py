# -*- coding: utf-8 -*-
"""
AGR.BIZ.ID - Storage & Media Architecture (STRICT)
================================================
TIDAK ada file upload yang disimpan pada filesystem lokal web server.
Seluruh media dialirkan ke Cloud Object Storage (AWS S3 / DigitalOcean
Spaces / MinIO) melalui **Pre-Signed URL (Direct Upload)** sehingga
bandwidth & memori server tetap ringan.

Provider  : boto3 S3-compatible (AGR_S3_ENDPOINT_URL untuk MinIO/Spaces)
Optimasi  : Cloudinary / ImageKit (kompresi, WebP, thumbnail) via CDN
Bucket    : PUBLIC  -> foto listing, foto profil   (dilayani via CDN)
            PRIVATE -> dokumen KYC (KTP/NPWP/B3), lampiran chat, bukti transfer
                      hanya dapat dibaca lewat Pre-Signed GET berumur pendek
                      yang diterbitkan backend SETELAH kepemilikan/status
                      transaksi diverifikasi (mis. lokasi/dokumen terbuka
                      setelah DP dibayar).
Validasi  : MIME + ukuran divalidasi di KLIEN (Zod-like rules pada JS) dan
            di SERVER (magic bytes via `filetype` + Pillow) — ekstensi saja
            tidak dipercaya sama sekali.

Mode demo tanpa kredensial cloud: provider "local" meniru objek storage
(in-memory bucket) + presign HMAC, sehingga seluruh alur dapat diuji.
"""
import os
import io
import re
import hmac
import uuid
import base64
import hashlib
import time
from datetime import datetime

try:
    import filetype                                  # deteksi magic bytes
except ImportError:
    filetype = None

try:
    from PIL import Image as PILImage                # validasi integritas gambar
except ImportError:
    PILImage = None

# ---------------------------------------------------------------------------
# Konfigurasi environment (lihat .env.example)
# ---------------------------------------------------------------------------
S3_ENDPOINT      = os.environ.get("AGR_S3_ENDPOINT_URL", "")          # MinIO/Spaces
S3_REGION        = os.environ.get("AGR_S3_REGION", "ap-southeast-1")  # lokal ID
S3_ACCESS_KEY    = os.environ.get("AGR_S3_ACCESS_KEY", "")
S3_SECRET_KEY    = os.environ.get("AGR_S3_SECRET_KEY", "")
BUCKET_PUBLIC    = os.environ.get("AGR_BUCKET_PUBLIC", "agrid-media-public")
BUCKET_PRIVATE   = os.environ.get("AGR_BUCKET_PRIVATE", "agrid-docs-private")
CDN_BASE         = os.environ.get("AGR_CDN_BASE", "")                 # https://cdn.agr.id
PRESIGN_PUT_TTL  = int(os.environ.get("AGR_PRESIGN_PUT_TTL", "300"))  # 5 menit
PRESIGN_GET_TTL  = int(os.environ.get("AGR_PRESIGN_GET_TTL", "60"))   # 60 detik

# Cloudinary / ImageKit (opsional; bila terisi, transformasi & CDN didelegasikan)
CLOUDINARY_URL   = os.environ.get("CLOUDINARY_URL", "")
IMAGEKIT_URLBASE = os.environ.get("IMAGEKIT_URL_BASE", "")            # https://ik.imagekit.net/<id>/

_SIGNING_SECRET  = os.environ.get("AGR_STORAGE_SECRET", "agr-dev-storage-secret")

# ---------------------------------------------------------------------------
# Kebijakan validasi file (harus SAMA dengan aturan Zod di sisi klien)
# ---------------------------------------------------------------------------
MAX_IMAGE_BYTES  = 5 * 1024 * 1024          # 5 MB  (foto produk/eviden)
MAX_DOC_BYTES    = 8 * 1024 * 1024          # 8 MB  (PDF KTP/NPWP/B3)
MAX_CHAT_BYTES   = 10 * 1024 * 1024         # 10 MB (lampiran chat)

# mime -> (ekstensi kanonik, magic-byte prefix yang diterima)
MIME_POLICY = {
    "image/jpeg": {"ext": "jpg",  "magic": [b"\xff\xd8\xff"]},
    "image/png":  {"ext": "png",  "magic": [b"\x89PNG\r\n\x1a\n"]},
    "image/webp": {"ext": "webp", "magic": [b"RIFF"]},           # + check WEBP
    "image/gif":  {"ext": "gif",  "magic": [b"GIF8"]},
    "application/pdf": {"ext": "pdf", "magic": [b"%PDF-"]},
}
# Blok eksplisit: script / executable yang menyamar sebagai gambar/dokumen
BLOCKED_MAGIC = [b"\x7fELF", b"MZ", b"#!/", b"<script", b"<?php", b"\x1f\x8b"]

CATEGORY_RULES = {                    # (bucket, prefix folder, max bytes, mimes)
    "product":  ("public",  "products",  MAX_IMAGE_BYTES, {"image/jpeg", "image/png", "image/webp"}),
    "avatar":   ("public",  "avatars",   MAX_IMAGE_BYTES, {"image/jpeg", "image/png", "image/webp"}),
    "eviden":   ("public",  "eviden",    MAX_IMAGE_BYTES, {"image/jpeg", "image/png", "image/webp", "image/gif"}),
    "kyc":      ("private", "kyc",       MAX_DOC_BYTES,   {"image/jpeg", "image/png", "application/pdf"}),
    "chat":     ("private", "chat",      MAX_CHAT_BYTES,  {"image/jpeg", "image/png", "application/pdf"}),
    "payment":  ("private", "payments",  MAX_DOC_BYTES,   {"image/jpeg", "image/png", "application/pdf"}),
}


class ValidationError(Exception):
    pass


# ---------------------------------------------------------------------------
# Provider abstrak
# ---------------------------------------------------------------------------
class _LocalBucket:
    """Meniru object storage in-memory utk dev/test tanpa cloud.
    BUKAN filesystem web server — tidak ada file yang ditulis ke disk."""
    objects = {}                                    # key -> (bytes, content_type)

    def put(self, key, data, content_type, bucket):
        _LocalBucket.objects[(bucket, key)] = (data, content_type)

    def presign_put(self, bucket, key, expires):
        exp = int(time.time()) + expires
        sig = self._sig(bucket, key, exp)
        return f"/storage-demo/{bucket}/{key}?exp={exp}&sig={sig}"

    def presign_get(self, bucket, key, expires):
        return self.presign_put(bucket, key, expires)

    @staticmethod
    def _sig(bucket, key, exp):
        msg = f"{bucket}|{key}|{exp}".encode()
        return hmac.new(_SIGNING_SECRET.encode(), msg, hashlib.sha256).hexdigest()[:32]

    def get(self, bucket, key, sig=None, exp=None):
        if sig is not None:                         # verifikasi presign
            if exp is None or int(exp) < time.time():
                raise ValidationError("URL kedaluwarsa")
            if not hmac.compare_digest(self._sig(bucket, key, int(exp)), str(sig)):
                raise ValidationError("Signature tidak valid")
        obj = _LocalBucket.objects.get((bucket, key))
        if not obj:
            raise ValidationError("Objek tidak ditemukan")
        return obj


class _S3Provider:
    def __init__(self):
        import boto3
        from botocore.config import Config as BotoConfig
        kw = dict(region_name=S3_REGION,
                  config=BotoConfig(signature_version="s3v4"))
        if S3_ENDPOINT:
            kw["endpoint_url"] = S3_ENDPOINT
        if S3_ACCESS_KEY:
            kw["aws_access_key_id"] = S3_ACCESS_KEY
            kw["aws_secret_access_key"] = S3_SECRET_KEY
        self.s3 = boto3.client("s3", **kw)
        self.public_base = (CDN_BASE.rstrip("/") + "/" if CDN_BASE else None)

    def ensure_buckets(self):
        for b in (BUCKET_PUBLIC, BUCKET_PRIVATE):
            try:
                self.s3.head_bucket(Bucket=b)
            except Exception:
                params = {"Bucket": b}
                if S3_REGION != "us-east-1":
                    params["CreateBucketConfiguration"] = {"LocationConstraint": S3_REGION}
                try:
                    self.s3.create_bucket(**params)
                except Exception:
                    pass

    def presign_put(self, bucket, key, expires):
        return self.s3.generate_presigned_url(
            "put_object", Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires, HttpMethod="PUT")

    def presign_get(self, bucket, key, expires):
        return self.s3.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires, HttpMethod="GET")

    def put(self, key, data, content_type, bucket):
        self.s3.put_object(Bucket=bucket, Key=key, Body=data,
                           ContentType=content_type)

    def get(self, bucket, key, sig=None, exp=None):
        obj = self.s3.get_object(Bucket=bucket, Key=key)
        return (obj["Body"].read(), obj.get("ContentType", "application/octet-stream"))


def _build_provider():
    if S3_ACCESS_KEY or os.environ.get("AGR_FORCE_S3"):
        p = _S3Provider()
        p.ensure_buckets()
        return "s3", p
    return "local", _LocalBucket()


PROVIDER_NAME, PROVIDER = _build_provider()


# ---------------------------------------------------------------------------
# Transformasi media (Cloudinary / ImageKit bila dikonfigurasi)
# ---------------------------------------------------------------------------
def public_url(key):
    """URL publik final — lewat CDN/transform service bila aktif."""
    if CLOUDINARY_URL:
        cfg = re.match(r"cloudinary://(?P<api>[^@]+)@(?P<cloud>[^.]+)", CLOUDINARY_URL)
        if cfg:                                     # signed fetch sederhana
            base = f"https://res.cloudinary.com/{cfg.group('cloud')}/fetch/f_auto,q_auto,w_800/"
            return base + f"{BUCKET_PUBLIC}/{key}"
    if IMAGEKIT_URLBASE:
        return f"{IMAGEKIT_URLBASE.rstrip('/')}/tr:f-auto,q-auto,w-800/{BUCKET_PUBLIC}/{key}"
    if CDN_BASE:
        return f"{CDN_BASE.rstrip('/')}/{key}"
    if PROVIDER_NAME == "s3":
        host = (S3_ENDPOINT or f"s3.{S3_REGION}.amazonaws.com").replace("https://", "")
        return f"https://{BUCKET_PUBLIC}.{host}/{key}"
    return f"/storage-demo/public/{key}"


def thumb_url(key, width=300):
    if CLOUDINARY_URL:
        cfg = re.match(r"cloudinary://[^@]+@([^.]+)", CLOUDINARY_URL)
        return f"https://res.cloudinary.com/{cfg.group(1)}/image/upload/f_webp,q_auto,w_{width}/{key}"
    if IMAGEKIT_URLBASE:
        return f"{IMAGEKIT_URLBASE.rstrip('/')}/tr:f-webp,q-auto,w-{width}/{key}"
    return public_url(key)


# ---------------------------------------------------------------------------
# Validasi SIPEK Server-side (magic bytes, bukan ekstensi)
# ---------------------------------------------------------------------------
def sniff_mime(data):
    if filetype:
        kind = filetype.guess(data)
        if kind:
            return kind.mime
    # fallback manual magic-bytes
    for mime, rule in MIME_POLICY.items():
        for mg in rule["magic"]:
            if data[:len(mg)] == mg:
                if mime == "image/webp" and data[8:12] != b"WEBP":
                    continue
                return mime
    return None


def validate_bytes(data, category, declared_mime=None):
    """Return mime hasil sniff; raise ValidationError bila ditolak."""
    if not data:
        raise ValidationError("File kosong")
    _, _, maxb, allowed = CATEGORY_RULES[category]
    if len(data) > maxb:
        raise ValidationError(f"Ukuran melebihi batas {maxb // (1024*1024)} MB")
    for bad in BLOCKED_MAGIC:
        if data.lstrip()[:len(bad)] == bad:
            raise ValidationError("Jenis file berbahaya ditolak (script/executable)")
    mime = sniff_mime(data)
    if mime is None:
        raise ValidationError("Format file tidak dikenali dari magic bytes")
    if mime not in allowed:
        raise ValidationError(f"Tipe {mime} tidak diizinkan untuk '{category}'")
    if declared_mime and declared_mime.split(";")[0] not in allowed:
        raise ValidationError("Deklarasi MIME klien tidak valid")
    if declared_mime and mime != declared_mime.split(";")[0] and \
            not (mime.startswith("image/") and declared_mime.startswith("image/")):
        raise ValidationError("MIME deklarasikan ≠ konten sebenarnya (kemungkinan penyamaran)")
    if mime.startswith("image/") and PILImage:
        try:
            img = PILImage.open(io.BytesIO(data))
            img.verify()                            # integritas penuh
        except Exception:
            raise ValidationError("Berkas gambar rusak / tidak valid")
    return mime


def build_key(category, user_id, filename, mime):
    ext = MIME_POLICY[mime]["ext"]
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", os.path.basename(filename))[:60] or "file"
    now = datetime.utcnow()
    bucket, folder, _, _ = CATEGORY_RULES[category]
    return (bucket,
            f"{folder}/{now:%Y/%m}/{user_id or 'anon'}/{now:%H%M%S}-{uuid.uuid4().hex[:8]}-{safe}.{ext}")


# ---------------------------------------------------------------------------
# API tingkat aplikasi
# ---------------------------------------------------------------------------
def create_upload_ticket(user_id, category, filename, size, declared_mime):
    """Langkah 1 direct-upload: validasi kebijakan + terbitkan pre-signed PUT.
    File TIDAK melewati web server; klien meng-PUT langsung ke bucket."""
    if category not in CATEGORY_RULES:
        raise ValidationError("Kategori upload tidak dikenal")
    bucket, folder, maxb, allowed = CATEGORY_RULES[category]
    if size > maxb:
        raise ValidationError(f"Ukuran melebihi batas {maxb // (1024*1024)} MB")
    if declared_mime and declared_mime not in allowed:
        raise ValidationError(f"Tipe {declared_mime} tidak diizinkan untuk '{category}'")
    key = build_key(category, user_id, filename,
                    MIME_POLICY.get(declared_mime, {"ext": "bin"}) and declared_mime or "image/jpeg")
    url = PROVIDER.presign_put(bucket, key, PRESIGN_PUT_TTL)
    return {
        "upload_url": url, "method": "PUT", "key": key, "bucket": bucket,
        "visibility": "public" if bucket == BUCKET_PUBLIC else "private",
        "expires_in": PRESIGN_PUT_TTL,
        "required_headers": {"Content-Type": declared_mime or "application/octet-stream"},
    }


def finalize_upload(user_id, category, key, declared_mime=None):
    """Langkah 2: server memverifikasi objek yang sudah masuk bucket
    (magic bytes + ukuran) SEBELUM dianggap sah. Private key tidak pernah
    menghasilkan URL publik."""
    if category not in CATEGORY_RULES:
        raise ValidationError("Kategori tidak dikenal")
    want_bucket, _, maxb, _ = CATEGORY_RULES[category]
    if not key.startswith(want_bucket.replace("agrid-", "") + "/") and "/" not in key:
        raise ValidationError("Key tidak valid")
    data, ctype = PROVIDER.get(want_bucket, key)
    mime = validate_bytes(data, category, declared_mime or ctype)
    ref = f"object://{want_bucket}/{key}"
    if want_bucket == BUCKET_PUBLIC:
        return {"ref": ref, "url": public_url(key), "thumb": thumb_url(key),
                "mime": mime, "size": len(data), "visibility": "public"}
    return {"ref": ref, "url": None, "thumb": None,   # private: sengaja tanpa URL
            "mime": mime, "size": len(data), "visibility": "private"}


def signed_view_url(ref, viewer_user, reason_check):
    """Akses file PRIVATE HANYA lewat Pre-Signed GET berumur pendek.
    `reason_check(viewer_user, ref)` harus mengembalikan True (kepemilikan
    atau status transaksi cukup, mis. DP sudah dibayar) — dievaluasi
    oleh pemanggil (app layer) sebelum URL diterbitkan."""
    bucket, key = _parse_ref(ref)
    if bucket == BUCKET_PUBLIC:
        return public_url(key)
    if not reason_check(viewer_user, ref):
        raise PermissionError("Akses ditolak: belum memenuhi syarat (verifikasi kepemilikan/status pembayaran).")
    return PROVIDER.presign_get(bucket, key, PRESIGN_GET_TTL)


def read_private(ref):
    bucket, key = _parse_ref(ref)
    data, ctype = PROVIDER.get(bucket, key)
    return data, ctype


def ingest_data_uri(data_uri, user_id, category):
    """Kompatibilitas: konversi data URI (hasil FileReader lama) menjadi
    objek cloud sungguhan — menghapus kebiasaan menyimpan base64 di DB."""
    m = re.match(r"data:([\w/+-]+);base64,(.+)", data_uri or "", re.S)
    if not m:
        return None
    mime, b64 = m.group(1), m.group(2)
    data = base64.b64decode(b64)
    validate_bytes(data, category, mime)
    bucket, key = build_key(category, user_id, f"legacy.{MIME_POLICY[mime]['ext']}", mime)
    PROVIDER.put(key, data, mime, bucket)
    return f"object://{bucket}/{key}"


def _parse_ref(ref):
    m = re.match(r"object://([^/]+)/(.+)", ref or "")
    if not m:
        raise ValidationError("Referensi media tidak valid")
    return m.group(1), m.group(2)
