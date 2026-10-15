/* AGR.ID - Aset statis modul storage: validator sisi klien (gaya Zod) +
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
      const info = await agrUpload(file, category, p => {
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
  if (refOrUrl.startsWith('object://')) {
    const r = await AGRApi.view(refOrUrl);
    if (r.ok && r.url) el.src = r.url;
    else el.outerHTML = '<span class="badge bg-secondary">🔒 File privat — akses terbatas</span>';
  } else if (!refOrUrl.startsWith('data:')) {
    el.src = refOrUrl;
  }
}
