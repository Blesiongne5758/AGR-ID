# -*- coding: utf-8 -*-
"""
AGR.ID - Storage API Blueprint
==============================
Endpoint pendukung arsitektur media terpisahkan (Cloud Object Storage):

  POST /api/v1/storage/upload-ticket   {category, filename, size, mime}
        -> pre-signed PUT URL (direct upload klien -> bucket; file TIDAK
           melewati web server). Klien memvalidasi ulang aturan Zod-like
           sebelum meminta tiket.
  POST /api/v1/storage/finalize        {category, key}
        -> server menarik objek dr bucket, cek MAGIC BYTES + ukuran +
           integritas gambar (Pillow). Public -> mengembalikan CDN URL &
           thumbnail; Private -> hanya mengembalikan ref object:// (tanpa URL).
  GET  /api/v1/storage/view?ref=object://private/...
        -> Pre-Signed GET berumur pendek HANYA bila pemeriksaan akses lolos:
           pemilik file ATAU pihak transaksi terkait DAN (untuk dokumen
           sensitif) status DP sudah dibayar/disetujui penjual.
  GET  /storage-demo/<bucket>/<key>?exp=&sig=      (mode dev: meniru S3 PUT/GET)
  GET  /media/<int:eviden_id>/foto                 (proxy aman utk private)

Semua jalur menghormati konfigurasi admin `fitur_storage_cloud` — bila
dinonaktifkan seluruh endpoint menolak dengan 403 (fallback mode legacy).
"""
from flask import Blueprint, current_app, jsonify, request, Response

import storage

storage_bp = Blueprint("storage", __name__)


def _app():
    return current_app._get_current_object()


def _authz():
    from app import current_user, fitur_on
    if not fitur_on("fitur_storage_cloud"):
        return None, (jsonify(ok=False, error="Fitur storage cloud dinonaktifkan pada konfigurasi admin."), 403)
    u = current_user()
    if not u:
        return None, (jsonify(ok=False, error="Login diperlukan untuk operasi storage."), 401)
    return u, None


# ---------------------------------------------------------------------------
# 1) Tiket presigned PUT (direct upload)
# ---------------------------------------------------------------------------
@storage_bp.route("/api/v1/storage/upload-ticket", methods=["POST"])
def upload_ticket():
    u, err = _authz()
    if err:
        return err
    j = request.get_json(silent=True) or request.form
    category = j.get("category", "product")
    try:
        ticket = storage.create_upload_ticket(
            user_id=u.id, category=category,
            filename=j.get("filename", "file"),
            size=int(float(j.get("size") or 0)),
            declared_mime=j.get("mime"))
    except storage.ValidationError as e:
        return jsonify(ok=False, error=str(e)), 422
    from app import audit_current
    audit_current("storage_ticket", "storage", None, f"{category}:{ticket['key']}")
    return jsonify(ok=True, provider=storage.PROVIDER_NAME, **ticket)


# ---------------------------------------------------------------------------
# 2) Finalisasi: verifikasi objek yang sudah masuk bucket
# ---------------------------------------------------------------------------
@storage_bp.route("/api/v1/storage/finalize", methods=["POST"])
def finalize():
    u, err = _authz()
    if err:
        return err
    j = request.get_json(silent=True) or request.form
    category = j.get("category", "product")
    key = j.get("key", "")
    # kunci harus berada di bawah folder milik user tsb (anti take-over key orang lain)
    if f"/{u.id}/" not in f"/{key}" and u.role != "admin":
        return jsonify(ok=False, error="Key bukan milik akun ini."), 403
    try:
        info = storage.finalize_upload(u.id, category, key, j.get("mime"))
    except storage.ValidationError as e:
        return jsonify(ok=False, error=str(e)), 422
    from app import audit_current
    audit_current("storage_finalize", "storage", None, f"{category}:{info['ref']} ({info['mime']})")
    return jsonify(ok=True, **info)


# ---------------------------------------------------------------------------
# 3) Signed GET utk objek PRIVATE — dengan pemeriksaan bisnis
# ---------------------------------------------------------------------------
def _access_ok(viewer, ref):
    """Kepemilikan ATAU keterlibatan transaksi + syarat pembayaran."""
    from app import db, Pelunasan, Transaksi, Eviden
    key = ref.split("/", 1)[1] if ref.startswith("object://") else ref
    # a) pemilik langsung (folder /kyc|chat|payments/<yyyy>/<mm>/<uid>/...)
    parts = key.split("/")
    owner_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    if owner_id == viewer.id or viewer.role == "admin":
        return True
    # b) bukti pelunasan: penjual(penerima) boleh melihat setelah diajukan;
    #    pembeli(pengunggah) sudah tercakup poin (a)
    pl = Pelunasan.query.filter(Pelunasan.bukti == ref).first()
    if pl:
        t = Transaksi.query.get(pl.transaksi_id)
        if t and viewer.id == t.seller_id and pl.status in ("menunggu", "disetujui"):
            return True
    # c) eviden privat (mis. dokumen B3/kyc pengiriman): terbuka bila DP lunas
    ev = Eviden.query.filter(Eviden.foto == ref).first()
    if ev:
        t = Transaksi.query.get(ev.transaksi_id)
        if t and viewer.id in (t.seller_id, t.buyer_id) and \
                t.status in ("dp_dibayar", "menunggu_approval", "lunas",
                             "dijadwalkan", "dikirim", "delivered", "completed"):
            return True
    return False


@storage_bp.route("/api/v1/storage/view")
def view_signed():
    u, err = _authz()
    if err:
        return err
    ref = request.args.get("ref", "")
    try:
        url = storage.signed_view_url(ref, u, _access_ok)
    except PermissionError as e:
        from app import audit_current
        audit_current("storage_access_ditolak", "storage", None, f"{ref} oleh user#{u.id}")
        return jsonify(ok=False, error=str(e)), 403
    except storage.ValidationError as e:
        return jsonify(ok=False, error=str(e)), 422
    ttl = storage.PRESIGN_GET_TTL if ref.startswith("object://" + storage.BUCKET_PRIVATE) else 0
    return jsonify(ok=True, url=url, expires_in=ttl,
                   note="URL berlaku singkat; jangan disisipkan ke log/link permanen.")


# ---------------------------------------------------------------------------
# 4) Endpoint demo-mode (meniru perilaku S3 utk direct upload tanpa cloud)
# ---------------------------------------------------------------------------
@storage_bp.route("/storage-demo/<bucket>/<path:key>", methods=["PUT", "GET"])
def demo_object(bucket, key):
    exp = request.args.get("exp")
    sig = request.args.get("sig")
    try:
        if request.method == "PUT":
            data = request.get_data()
            ctype = request.headers.get("Content-Type", "application/octet-stream")
            storage.PROVIDER.put(key, data, ctype, bucket)     # verifikasi signature di dalam get(); put demo bebas utk flow test
            return Response(status=200, headers={"ETag": '"demo"'})
        body, ctype = storage.PROVIDER.get(bucket, key, sig=sig, exp=exp)
        return Response(body, mimetype=ctype,
                        headers={"Cache-Control": "private, max-age=30"})
    except storage.ValidationError as e:
        return jsonify(ok=False, error=str(e)), 403


# ---------------------------------------------------------------------------
# 5) Proxy aman gambar private (mis. thumbnail bukti pada dashboard) —
#    stream dari bucket, TANPA pernah menyentuh filesystem server.
# ---------------------------------------------------------------------------
@storage_bp.route("/media/private")
def media_private():
    u, err = _authz()
    if err:
        return err
    ref = request.args.get("ref", "")
    if not ref.startswith("object://" + storage.BUCKET_PRIVATE):
        return jsonify(ok=False, error="Hanya untuk objek private."), 400
    try:
        if not _access_ok(u, ref):
            raise PermissionError("Akses ditolak.")
        data, ctype = storage.read_private(ref)
    except PermissionError:
        return jsonify(ok=False, error="Anda belum berhak melihat file ini (butuh DP dibayar/approval)."), 403
    except storage.ValidationError as e:
        return jsonify(ok=False, error=str(e)), 404
    return Response(data, mimetype=ctype,
                    headers={"Cache-Control": "no-store",
                             "X-Content-Type-Options": "nosniff",
                             "Content-Disposition": "inline"})
