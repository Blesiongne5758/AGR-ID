# -*- coding: utf-8 -*-
"""AGR.BIZ.ID - Utilitas umum backend: format, upload aman, ID unik."""
import os
import re
import uuid
from datetime import datetime
from werkzeug.utils import secure_filename

ALLOWED_IMG = {"png", "jpg", "jpeg", "gif", "webp"}
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")


def ensure_upload_dir(sub=""):
    d = os.path.join(UPLOAD_DIR, sub) if sub else UPLOAD_DIR
    os.makedirs(d, exist_ok=True)
    return d


def save_upload(file_storage, subdir="umum"):
    """Simpan file upload dengan nama unik + validasi ekstensi. Return relative path atau None."""
    if not file_storage or not file_storage.filename:
        return None
    ext = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
    if ext not in ALLOWED_IMG:
        return None
    safe = secure_filename(file_storage.filename)
    name = f"{datetime.now():%Y%m%d%H%M%S}_{uuid.uuid4().hex[:8]}_{safe}"
    d = ensure_upload_dir(subdir)
    path = os.path.join(d, name)
    file_storage.save(path)
    return f"uploads/{subdir}/{name}"


_RP_RE = re.compile(r"[^0-9.]")


def parse_number(s, default=0.0):
    """Parse 'Rp 12.500' / '12,500.00' / angka -> float dengan aman."""
    try:
        if s is None:
            return float(default)
        if isinstance(s, (int, float)):
            return float(s)
        cleaned = _RP_RE.sub("", str(s))
        return float(cleaned) if cleaned else float(default)
    except (ValueError, TypeError):
        return float(default)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))
