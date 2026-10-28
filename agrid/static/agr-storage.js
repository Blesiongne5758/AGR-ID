/* AGR.BIZ.ID - Aset statis modul storage: validator sisi klien (gaya Zod) +
   helper direct-upload Pre-Signed URL. Aturan di sini HARUS identik dengan
   storage.py::CATEGORY_RULES (server tetap memverifikasi magic bytes —
   validasi klien hanya pagar UX pertama, bukan satu-satunya pagar). */

const AGRApi = {
  ticket: (body) => fetch('/api/v1/storage/upload-ticket', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
  }).then(r => r.json()),
  finalize: (body) => fetch('/api/v1/storage/finalize', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
  }).then(r => r.json()),
  view: (ref) => fetch('/api/v1/storage/view?ref=' + encodeURIComponent(ref)).then(r => r.json()),
};

/* ---------------- Zod-like schema (mirror CATEGORY_RULES) ---------------- */
const MB = 1024 * 1024;
const SCHEMAS = {
  product: { maxBytes: 5 * MB, mimes: ['image/jpeg', 'image/png', 'image/webp'], label: 'foto produk' },
  avatar:  { maxBytes: 5 * MB, mimes: ['image/jpeg', 'image/png', 'image/webp'], label: 'foto profil' },
  eviden:  { maxBytes: 5 * MB, mimes: ['image/jpeg', 'image/png', 'image/webp', 'image/gif'], label: 'foto eviden' },
  kyc:     { maxBytes: 8 * MB, mimes: ['image/jpeg', 'image/png', 'application/pdf'], label: 'dokumen KYC' },
  chat:    { maxBytes: 10 * MB, mimes: ['image/jpeg', 'image/png', 'application/pdf'], label: 'lampiran chat' },
  payment: { maxBytes: 8 * MB, mimes: ['image/jpeg', 'image/png', 'application/pdf'], label: 'bukti transfer' },
};

/** z.file().validate(file, category) -> {ok, error} */
function validateFile(file, category) {
  const s = SCHEMAS[category];
  if (!s) return { ok: false, error: 'Kategori upload tidak dikenal.' };
  if (!file) return { ok: false, error: 'Tidak ada file.' };
  if (file.size === 0) return { ok: false, error: 'File kosong.' };
  if (file.size > s.maxBytes)
    return { ok: false, error: `Ukuran ${s.label} maks ${(s.maxBytes / MB).toFixed(0)} MB.` };
  if (!s.mimes.includes(file.type))
    return { ok: false, error: `Tipe ${file.type || 'tidak diketahui'} tidak diizinkan untuk ${s.label}.` };
  return { ok: true };
}

/**
 * Upload langsung ke bucket via pre-signed PUT — file TIDAK pernah dikirim
 * ke web server. On progress(persen), resolve -> info finalisasi
 * {ref, url?, thumb?, visibility}. Private object => url null; gunakan
 * AGRApi.view(ref) untuk mendapatkan signed URL saat dibutuhkan.
 */
async function agrUpload(file, category, onProgress) {
  const v = validateFile(file, category);
  if (!v.ok) throw new Error(v.error);

  const t = await AGRApi.ticket({ category, filename: file.name, size: file.size, mime: file.type });
  if (!t.ok) throw new Error(t.error || 'Gagal meminta tiket upload.');

  // PUT langsung ke object storage (S3/Spaces/MinIO atau endpoint demo)
  await new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(t.method || 'PUT', t.upload_url, true);
    Object.entries(t.required_headers || {}).forEach(([k, val]) => xhr.setRequestHeader(k, val));
    xhr.upload.onprogress = e => onProgress && e.lengthComputable &&
      onProgress(Math.round(e.loaded / e.total * 100));
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300) ? resolve() : reject(new Error('Bucket menolak upload (' + xhr.status + ').'));
    xhr.onerror = () => reject(new Error('Jaringan gagal saat direct upload.'));
    xhr.send(file);
  });

  const f = await AGRApi.finalize({ category, key: t.key, mime: file.type });
  if (!f.ok) { try { await fetch(t.upload_url, { method: 'DELETE' }); } catch (e) {} throw new Error(f.error || 'Verifikasi server gagal.'); }
  f.bucket_key = t.key;
  return f;
}

/** Bind sebuah <input type=file> ke slot hasil (hidden input + preview). */
function bindAgrUploader(input, { category, hiddenId, previewEl, statusEl, onDone }) {
  input.addEventListener('change', async () => {
    const file = input.files[0];
    const hid = document.getElementById(hiddenId);
    if (!file) { if (hid) hid.value = ''; return; }
    const v = validateFile(file, category);
    if (!v.ok) { if (statusEl) statusEl.innerHTML = `<span class="text-danger small">✖ ${v.error}</span>`; input.value = ''; return; }
    if (statusEl) statusEl.innerHTML = '<span class="small text-muted">Mengunggah langsung ke cloud… 0%</span>';
    try {
      // Otomatis: Cloudinary bila aktif di konfigurasi, fallback S3 presigned.
      const info = await agrUploadAny(file, category, p => {
        if (statusEl) statusEl.innerHTML = `<span class="small text-muted">Mengunggah langsung ke cloud… ${p}%</span>`;
      });
      if (hid) hid.value = info.ref;                       // simpan ref object://…, BUKAN base64
      if (previewEl) {
        if (info.url && (info.mime || '').startsWith('image/'))
          previewEl.innerHTML = `<img src="${info.thumb || info.url}" class="rounded border" style="max-height:160px">`;
        else if (info.visibility === 'private')
          previewEl.innerHTML = `🔒 Tersimpan aman di bucket private (${info.mime}, ${(info.size / 1024).toFixed(0)} KB)`;
      }
      if (statusEl) statusEl.innerHTML = `<span class="small text-success">✔ ${info.visibility === 'public' ? 'Tersimpan di CDN' : 'Terkunci (private)'}</span>`;
      onDone && onDone(info);
    } catch (e) {
      if (statusEl) statusEl.innerHTML = `<span class="small text-danger">✖ ${e.message}</span>`;
      input.value = '';
    }
  });
}

/** Pengganti <img src="data:..."> lama → render dari cloud/signed URL. */
async function renderMedia(el, refOrUrl) {
  if (!refOrUrl) return;
  if (refOrUrl.startsWith('cloud://')) {
    // Cloudinary: petakan folder private -> signed URL via backend bila tersedia.
    const pid = refOrUrl.slice(8);
    if (/\/private-|agr.id\/private/.test(pid) && window.AGRApi && AGRApi.view) {
      try { const r = await AGRApi.view(refOrUrl); if (r.ok && r.url) { el.src = r.url; return; } } catch (e) {}
      el.outerHTML = '<span class="badge bg-secondary">🔒 File privat — akses terbatas</span>';
      return;
    }
    el.src = 'https://res.cloudinary.com/' + ((await agrConfig()).cloudinary || {}).cloud_name +
             '/image/upload/f_auto,q_auto,w_600/' + pid;
    return;
  }
  if (refOrUrl.startsWith('object://')) {
    const r = await AGRApi.view(refOrUrl);
    if (r.ok && r.url) el.src = r.url;
    else el.outerHTML = '<span class="badge bg-secondary">🔒 File privat — akses terbatas</span>';
  } else if (!refOrUrl.startsWith('data:')) {
    el.src = refOrUrl;
  }
}

/* ===========================================================================
   CLOUDINARY (cloudinary.com) — direct upload tanpa backend signature.
   Dipakai saat frontend di-hosting statis di InfinityFree: browser mengirim
   file LANGSUNG ke Cloudinary memakai unsigned upload preset. Aturan validasi
   Zod-like di atas tetap dijalankan sebelum kirim; folder & tipe dibatasi
   oleh preset di dashboard Cloudinary (server-side enforcement).
   =========================================================================== */
let _AGR_CFG = null;
async function agrConfig(force) {
  if (_AGR_CFG && !force) return _AGR_CFG;
  try {
    const r = await fetch((window.AGR_API_BASE || '') + '/api/v1/config');
    _AGR_CFG = await r.json();
  } catch (e) { _AGR_CFG = { ok: false }; }
  return _AGR_CFG;
}

/* Implementasi final dengan pengambilan JSON respons */
async function cloudUpload(file, category, onProgress) {
  const v = validateFile(file, category);
  if (!v.ok) throw new Error(v.error);
  const cfgj = await agrConfig();
  const c = (cfgj && cfgj.cloudinary) || {};
  if (!c.enabled || !c.cloud_name) throw new Error('Cloudinary belum dikonfigurasi pada dashboard admin.');
  const folderMap = { product: 'products', avatar: 'avatar', eviden: 'eviden',
                      kyc: 'private-kyc', chat: 'private-chat', payment: 'private-payment' };
  const folder = 'agr.id/' + (folderMap[category] || category);
  const isImg = (file.type || '').startsWith('image/');
  const endpoint = `https://api.cloudinary.com/v1_1/${c.cloud_name}/${isImg ? 'image' : 'raw'}/upload`;
  const fd = new FormData();
  fd.append('file', file);
  fd.append('upload_preset', c.upload_preset);
  fd.append('folder', folder);
  if (isImg) fd.append('eager', JSON.stringify([{ transformation: 'f_auto,q_auto,w_300', crop: 'limit' }]));
  const resp = await new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', endpoint, true);
    xhr.upload.onprogress = e => onProgress && e.lengthComputable &&
      onProgress(Math.round(e.loaded / e.total * 100));
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) { try { resolve(JSON.parse(xhr.responseText)); } catch (e) { reject(new Error('Respons Cloudinary tidak valid.')); } }
      else reject(new Error('Cloudinary menolak upload (' + xhr.status + ').'));
    };
    xhr.onerror = () => reject(new Error('Jaringan gagal saat direct upload ke Cloudinary.'));
    xhr.send(fd);
  });
  if (!resp.public_id) throw new Error('Upload gagal: public_id tidak diterima.');
  const priv = folder.indexOf('private') > -1;
  return {
    ref: 'cloud://' + resp.public_id,
    visibility: priv ? 'private' : 'public',
    mime: resp.format ? (isImg ? 'image/' + resp.format : resp.bytes ? file.type : file.type) : file.type,
    size: resp.bytes || file.size,
    url: priv ? null : resp.secure_url,
    thumb: priv ? null : (resp.eager && resp.eager[0] ? resp.eager[0].secure_url : resp.secure_url),
  };
}

/* agrCloud-aware uploader: pakai Cloudinary bila aktif, fallback S3 presigned. */
async function agrUploadAny(file, category, onProgress) {
  const cfgj = await agrConfig();
  if (cfgj && cfgj.ok && cfgj.cloudinary && cfgj.cloudinary.enabled) return cloudUpload(file, category, onProgress);
  return agrUpload(file, category, onProgress);
}
