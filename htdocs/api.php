<?php
/**
 * ============================================================
 *  AGR.BIZ.ID — Gateway API untuk InfinityFree (docroot: htdocs)
 * ============================================================
 *  InfinityFree TIDAK mengizinkan koneksi langsung ke database
 *  eksternal (termasuk Supabase Postgres port 5432). Maka seluruh
 *  akses data dari frontend statis dilakukan lewat file PHP ini,
 *  yang memanggil:
 *    1. SUPABASE REST  (PostgREST)  -> CRUD tabel users/products/
 *       offers/bookings/transaksi/eviden/ratings/favorites/dll.
 *    2. CLOUDINARY     (signed form data) -> upload gambar/video/
 *       dokumen KYC langsung dari browser (server hanya menandatangani).
 *    3. BACKEND FLASK opsional (AGR_ID_API_URL) -> payment gateway,
 *       blockchain/dompet crypto, AI chat agent (bukan PHP-native).
 *
 *  Kredensial: salin config.example.php -> config.php
 *  lalu isi via File Manager / Git. JANGAN commit config.php!
 * ============================================================
 */

declare(strict_types=1);
error_reporting(E_ALL & ~E_DEPRECATED & ~E_NOTICE);
ini_set('display_errors', '0');
if (function_exists('mb_internal_encoding')) { mb_internal_encoding('UTF-8'); } // InfinityFree: mbstring tersedia; fallback utk pengujian lokal

/* ---------- konfigurasi ---------- */
$CFG = [
    'supabase_url'    => getenv('SUPABASE_URL') ?: '',
    'supabase_key'    => getenv('SUPABASE_ANON_KEY') ?: '',          // publishable/anon key (RLS aktif)
    'cloudinary_cloud'  => getenv('CLOUDINARY_CLOUD_NAME') ?: '',
    'cloudinary_key'    => getenv('CLOUDINARY_API_KEY') ?: '',
    'cloudinary_secret' => getenv('CLOUDINARY_API_SECRET') ?: '',
    'flask_url'       => getenv('AGR_ID_API_URL') ?: '',             // backend Flask (Render/Railway/VPS), boleh kosong
    'session_secret'  => getenv('AGR_ID_SESSION_SECRET') ?: 'ubah-secret-ini-di-config',
];
if (is_file(__DIR__ . '/config.php')) { $CFG = array_merge($CFG, require __DIR__ . '/config.php'); }

/* ---------- normalisasi & validasi konfigurasi Supabase ----------
   - nilai 'https://<ref>.supabase.co' => dipakai apa adanya
   - nilai '<ref>' saja                => dibangun jadi https://<ref>.supabase.co
   - key sb_publishable/sb_secret (format baru) TIDAK bisa dipakai sebagai
     apikey PostgREST — yang dibutuhkan adalah "anon public" key JWT lama. */

function agr_supabase_url(string $v): string {
    $v = trim($v);
    if ($v === '') return '';
    if (preg_match('#^https?://#i', $v)) return rtrim($v, '/');
    if (preg_match('/^[a-z0-9_-]{8,40}$/i', $v)) return 'https://' . strtolower($v) . '.supabase.co';
    return $v; // biarkan, validasi di bawah yang menolak
}

function agr_assert_supabase_config(array $CFG): void {
    $url = $CFG['supabase_url']; $key = (string)$CFG['supabase_key'];
    if ($url === '' || $key === '') {
        err('Supabase belum dikonfigurasi — isi supabase_url (https://<REF>.supabase.co) dan supabase_key (anon public key) di config.php', 503);
    }
    if (!preg_match('#^https://[a-z0-9-]+\.supabase\.co$#i', $url)) {
        err('SUPABASE_URL tidak valid. Format benar: https://<REF>.supabase.co — REF ada di kolom alamat dashboard Supabase (Project Settings -> API).', 500);
    }
    if (preg_match('/^sb_(publishable|secret)_/', $key)) {
        err('Kunci "' . substr($key, 0, 14) . '..." bukan anon key. Untuk gateway REST pakai Project API Key "anon public" (eyJ...) — lihat Project Settings -> API -> Legacy API Keys, atau buat via Service Roles. sb_secret_ JANGAN pernah ditaruh di hosting publik.', 500);
    }
    if (strpos($key, 'eyJ') !== 0) {
        err('supabase_key seharusnya JWT anon public key yang dimulai dengan "eyJ...".', 500);
    }
}

$CFG['supabase_url'] = agr_supabase_url((string)$CFG['supabase_url']);
agr_assert_supabase_config($CFG);

/* ---------- header & CORS ---------- */
header('Content-Type: application/json; charset=utf-8');
$origin = $_SERVER['HTTP_ORIGIN'] ?? '';
if ($origin !== '') {
    header('Access-Control-Allow-Origin: ' . $origin);
    header('Vary: Origin');
}
header('Access-Control-Allow-Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type, X-Agr-Token');
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: same-origin');
if (($_SERVER['REQUEST_METHOD'] ?? '') === 'OPTIONS') { http_response_code(204); exit; }

/* ---------- util: json response ---------- */
function out($data, int $code = 200): void { http_response_code($code); echo json_encode($data, JSON_UNESCAPED_UNICODE); exit; }
function err(string $msg, int $code = 400): void { out(['ok' => false, 'error' => $msg], $code); }
function body_json(): array { $raw = file_get_contents('php://input'); $j = json_decode($raw, true); return is_array($j) ? $j : []; }

/* ---------- session token (pengganti cookie login Flask) ---------- */
function agr_token(): string {
    // Header bisa datang dalam berbagai bentuk (X-Agr-Token, HTTP_X_AGR_TOKEN);
    // beberapa host/shared hosting menormalkan header custom — fallback ke query & Authorization.
    $t = $_SERVER['HTTP_X_AGRTOKEN'] ?? $_SERVER['HTTP_X_AGR_TOKEN'] ?? ($_GET['token'] ?? '');
    if (!preg_match('/^[a-f0-9]{64}$/', (string)$t)) {
        $auth = $_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? '';
        if (preg_match('/Bearer\s+([a-f0-9]{64})/i', (string)$auth, $m)) $t = $m[1];
    }
    return preg_match('/^[a-f0-9]{64}$/', (string)$t) ? (string)$t : '';
}
function make_token(int $userId): string {
    global $CFG;
    $exp = time() + 86400 * 7;
    $payload = $userId . ':' . $exp;
    $sig = hash_hmac('sha256', $payload, $CFG['session_secret']);
    return hash('sha256', $payload . '|' . $sig . '|' . random_bytes(16));
}

/* ---------- HTTP client ---------- */
function http_req(string $method, string $url, array $headers = [], ?string $body = null, int $timeout = 20): array {
    if (function_exists('curl_init')) {
        $ch = curl_init($url);
        curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER => true, CURLOPT_CUSTOMREQUEST => $method,
            CURLOPT_HTTPHEADER => $headers, CURLOPT_TIMEOUT => $timeout]);
        if ($body !== null) curl_setopt($ch, CURLOPT_POSTFIELDS, $body);
        $res = curl_exec($ch); $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        if ($res === false) { curl_close($ch); return [0, json_encode(['error' => 'network'])]; }
        curl_close($ch); return [$code, $res];
    }
    $ctx = stream_context_create(['http' => ['method' => $method, 'header' => implode("\r\n", $headers),
        'content' => $body ?? '', 'timeout' => $timeout, 'ignore_errors' => true]]);
    $res = @file_get_contents($url, false, $ctx);
    $code = 0; foreach (($http_response_header ?? []) as $h) if (preg_match('#HTTP/\d(?:\.\d)? (\d{3})#', $h, $m)) $code = (int)$m[1];
    return [$code, $res === false ? json_encode(['error' => 'network']) : $res];
}

/* ---------- Supabase PostgREST ---------- */
function sb(string $table, string $method, array $query = [], ?array $data = null) {
    global $CFG;
    if ($CFG['supabase_url'] === '' || $CFG['supabase_key'] === '') err('Supabase belum dikonfigurasi (isi config.php)', 503);
    $url = rtrim($CFG['supabase_url'], '/') . '/rest/v1/' . $table;
    if ($query) $url .= '?' . implode('&', $query);
    $headers = ['apikey: ' . $CFG['supabase_key'], 'Authorization: Bearer ' . $CFG['supabase_key'],
        'Content-Type: application/json', 'Prefer: return=representation'];
    [$code, $res] = http_req($method, $url, $headers, $data === null ? null : json_encode($data));
    $j = json_decode($res, true);
    if ($code >= 400) err('Supabase: ' . (is_array($j) ? ($j['message'] ?? json_encode($j)) : $res), $code === 404 ? 404 : 502);
    return is_array($j) ? $j : [];
}

/* Privileged feature operations use scoped PostgreSQL RPCs. The database
   validates the app session token again and keeps chat tables private from anon. */
function sb_rpc(string $function, array $data) {
    global $CFG;
    if ($CFG['supabase_url'] === '' || $CFG['supabase_key'] === '') err('Supabase belum dikonfigurasi', 503);
    [$code, $res] = http_req('POST', rtrim($CFG['supabase_url'], '/') . '/rest/v1/rpc/' . rawurlencode($function),
        ['apikey: ' . $CFG['supabase_key'], 'Authorization: Bearer ' . $CFG['supabase_key'], 'Content-Type: application/json'],
        json_encode($data, JSON_UNESCAPED_UNICODE));
    $result = json_decode($res, true);
    if ($code >= 400) err(is_array($result) ? ($result['message'] ?? $result['details'] ?? 'Operasi database gagal') : 'Operasi database gagal', $code === 401 || $code === 403 ? $code : 400);
    if ($result === null && trim($res) !== 'null') err('Respons database tidak valid', 502);
    return $result;
}

/* ---------- Cloudinary signature ---------- */
function cloudinary_signature(array $params): array {
    global $CFG;
    if ($CFG['cloudinary_cloud'] === '' || $CFG['cloudinary_key'] === '' || $CFG['cloudinary_secret'] === '') {
        err('Cloudinary belum dikonfigurasi. Isi cloudinary_cloud, cloudinary_key, dan cloudinary_secret di config.php atau GitHub Secrets.', 503);
    }
    ksort($params);
    $toSign = implode('&', array_map(fn($k, $v) => "$k=$v", array_keys($params), array_values($params)));
    $sig = sha1($toSign . $CFG['cloudinary_secret']);
    return ['signature' => $sig, 'api_key' => $CFG['cloudinary_key'], 'cloud_name' => $CFG['cloudinary_cloud'],
            'timestamp' => $params['timestamp'], 'folder' => $params['folder'] ?? 'agrid', 'upload_params' => $params];
}

/* ==================== ROUTER ==================== */
$action = $_GET['action'] ?? '';
$token  = agr_token();

switch ($action) {

    /* ---- health & bootstrap ---- */
    case 'health':
        $cloudinaryReady = $CFG['cloudinary_cloud'] !== '' && $CFG['cloudinary_key'] !== '' && $CFG['cloudinary_secret'] !== '';
        out(['ok' => true, 'service' => 'AGR.BIZ.ID gateway (htdocs)', 'php' => PHP_VERSION,
             'supabase' => $CFG['supabase_url'] !== '', 'cloudinary' => $cloudinaryReady,
             'flask_bridge' => $CFG['flask_url'] !== '', 'time' => date('c')]);

    /* ---- AUTH ---- */
    case 'register': {
        $b = body_json();
        foreach (['email','password','username'] as $req) if (empty($b[$req])) err("Field wajib: $req");
        if (!filter_var($b['email'], FILTER_VALIDATE_EMAIL)) err('Email tidak valid');
        if (strlen($b['password']) < 8) err('Password minimal 8 karakter');
        $username = strtolower(trim((string)$b['username']));
        if (!preg_match('/^[a-z0-9_.-]{3,32}$/', $username)) err('Nama pengguna harus 3–32 karakter (huruf kecil, angka, titik, garis bawah, atau tanda hubung)');
        $exists = sb('users', 'GET', ['email=eq.' . urlencode(strtolower($b['email'])), 'select=id']);
        if ($exists) err('Email sudah terdaftar', 409);
        $usernameExists = sb('users', 'GET', ['username=eq.' . urlencode($username), 'select=id']);
        if ($usernameExists) err('Nama pengguna sudah dipakai', 409);
        $user = [
            'email' => strtolower($b['email']), 'username' => $username, 'nama' => $username,
            'password_hash' => password_hash($b['password'], PASSWORD_BCRYPT),
            'role' => 'pembeli', 'roles' => ['pembeli'], 'tipe' => 'Perorangan',
            'tipe_pembeli' => 'Perorangan',
            'created_at' => date('c'),
        ];
        $row = sb('users', 'POST', [], $user)[0] ?? null;
        if (!$row) err('Gagal menyimpan user', 502);
        out(['ok' => true, 'user' => public_user($row)], 201);
    }

    case 'login': {
        $b = body_json();
        // Login dapat memakai email atau nama pengguna.
        $ident = trim((string)($b['email'] ?? $b['username'] ?? ''));
        if ($ident === '') err('Email/username wajib diisi', 422);
        $rows = sb('users', 'GET', ['email=eq.' . urlencode(strtolower($ident)), 'select=*']);
        if (!$rows) $rows = sb('users', 'GET', ['username=eq.' . urlencode(strtolower($ident)), 'select=*']);
        $u = $rows[0] ?? null;
        if (!$u || !password_verify($b['password'] ?? '', $u['password_hash'] ?? '')) err('Email/password salah', 401);
        $tok = make_token((int)$u['id']);
        sb('sessions', 'POST', [], ['user_id' => $u['id'], 'token' => $tok,
            'active_role' => $u['role'], 'expires_at' => date('c', time() + 604800)]);
        out(['ok' => true, 'token' => $tok, 'user' => public_user($u)]);
    }

    case 'logout':
        if ($token) sb('sessions', 'DELETE', ['token=eq.' . $token]);
        out(['ok' => true]);

    case 'me':
        out(['ok' => true, 'user' => public_user(require_session($token))]);

    case 'update-profile': {
        $u = require_session($token);
        $b = body_json();
        $sellerTypes = ['Perorangan','Kelompok/Paguyuban','Koperasi','Perusahaan'];
        $tipe = trim((string)($b['tipe_penjual'] ?? ''));
        if ($tipe !== '' && !in_array($tipe, $sellerTypes, true)) err('Tipe penjual tidak valid', 422);
        $lat = ($b['lat'] ?? '') === '' || ($b['lat'] ?? null) === null ? null : filter_var($b['lat'], FILTER_VALIDATE_FLOAT);
        $lng = ($b['lng'] ?? '') === '' || ($b['lng'] ?? null) === null ? null : filter_var($b['lng'], FILTER_VALIDATE_FLOAT);
        if (($b['lat'] ?? '') !== '' && $lat === false || ($b['lng'] ?? '') !== '' && $lng === false) err('Koordinat GPS tidak valid', 422);
        if ($lat !== null && ($lat < -90 || $lat > 90) || $lng !== null && ($lng < -180 || $lng > 180)) err('Koordinat GPS di luar rentang', 422);
        out(sb_rpc('agr_profile_update', ['p_token' => $token, 'p_payload' => $b]));
    }

    case 'switch-role': {
        $u = require_session($token);
        if (($u['role'] ?? '') === 'admin') err('Mode admin tidak dapat diganti', 403);
        $b = body_json();
        $target = $b['role'] ?? '';
        if (!in_array($target, ['penjual','pembeli'], true))
            err('Mode akun yang dipilih tidak tersedia', 422);
        out(sb_rpc('agr_role_switch', ['p_token' => $token, 'p_role' => $target]));
    }

    /* ---- GANTI PASSWORD (semua role: penjual/pembeli/admin) ---- */
    case 'change-password': {
        $u = require_session($token);
        $b = body_json();
        $old = (string)($b['old_password'] ?? '');
        $new = (string)($b['new_password'] ?? '');
        if ($old === '') err('Password lama wajib diisi', 422);
        if (!password_verify($old, $u['password_hash'] ?? '')) err('Password lama salah', 401);
        if (strlen($new) < 8) err('Password baru minimal 8 karakter', 422);
        if (!preg_match('/[A-Z]/', $new) || !preg_match('/[a-z]/', $new) || !preg_match('/\d/', $new))
            err('Password baru harus mengandung huruf besar, huruf kecil & angka', 422);
        if (password_verify($new, $u['password_hash'])) err('Password baru tidak boleh sama dengan password lama', 422);
        $rows = sb('users', 'PATCH', ['id=eq.' . $u['id']], ['password_hash' => password_hash($new, PASSWORD_BCRYPT)]);
        if (!$rows) err('Gagal memperbarui password', 502);
        sb('sessions', 'DELETE', ['user_id=eq.' . $u['id'], 'token=neq.' . $token]); // logout perangkat lain
        out(['ok' => true, 'message' => 'Password berhasil diganti']);
    }

    /* ---- PRODUK ---- */
    case 'products': {
        $q = ['select=*', 'order=created_at.desc', 'limit=' . min((int)($_GET['limit'] ?? 60), 200)];
        if (!empty($_GET['offset'])) $q[] = 'offset=' . (int)$_GET['offset'];
        if (!empty($_GET['kategori'])) $q[] = "kategori=eq." . urlencode($_GET['kategori']);
        if (!empty($_GET['sub_kategori'])) $q[] = "sub_kategori=eq." . urlencode($_GET['sub_kategori']);
        if (!empty($_GET['q'])) $q[] = "nama_product=ilike.*" . str_replace('%', '', urlencode($_GET['q'])) . "*";
        if (!empty($_GET['seller'])) $q[] = "user_id=eq." . (int)$_GET['seller'];
        out(sb('products', 'GET', $q));
    }

    case 'product': {
        $id = (int)($_GET['id'] ?? 0); if (!$id) err('id wajib');
        $rows = sb('products', 'GET', ['id=eq.' . $id]);
        if (!$rows) err('Produk tidak ditemukan', 404);
        $seller = sb('users', 'GET', ['id=eq.' . $rows[0]['user_id'], 'select=id,nama,tipe,tipe_penjual,alamat,lat,lng']);
        if ($seller) $seller[0]['tipe'] = $seller[0]['tipe_penjual'] ?: $seller[0]['tipe'];
        $rows[0]['seller'] = $seller[0] ?? null;
        out($rows[0]);
    }

    case 'product-create': {
        $u = require_session($token, 'penjual');
        $b = body_json();
        foreach (['nama_product','kategori','harga','satuan'] as $req) if (!isset($b[$req]) || $b[$req] === '') err("Field wajib: $req");
        $row = sb_rpc('agr_product_create', ['p_token' => $token, 'p_payload' => $b]);
        out(['ok' => true, 'product' => $row], 201);
    }

    case 'product-update': {
        $u = require_session($token, 'penjual');
        $b = body_json(); $id = (int)($b['id'] ?? 0); if (!$id) err('id wajib');
        unset($b['id'], $b['user_id']); $b['updated_at'] = date('c');
        sb('products', 'PATCH', ['id=eq.' . $id, 'user_id=eq.' . $u['id']], $b);
        out(['ok' => true]);
    }

    case 'product-delete': {
        $u = require_session($token, 'penjual');
        $id = (int)($_GET['id'] ?? 0);
        sb('products', 'DELETE', ['id=eq.' . $id, 'user_id=eq.' . $u['id']]);
        out(['ok' => true]);
    }

    /* ---- OFFER / BOOKING / DP ---- */
    case 'offer-create': {
        $u = require_session($token, 'pembeli');
        $b = body_json();
        $row = sb_rpc('agr_offer_create', ['p_token' => $token, 'p_product_id' => (int)($b['product_id'] ?? 0),
            'p_price' => (float)($b['harga_tawar'] ?? 0), 'p_quantity' => (float)($b['jumlah'] ?? 1), 'p_note' => (string)($b['catatan'] ?? '')]);
        out(['ok' => true, 'offer' => $row], 201);
    }
    case 'offers-mine': {
        require_session($token);
        out(sb_rpc('agr_offers_list', ['p_token' => $token]));
    }
    case 'offer-respond': {
        $u = require_session($token, 'penjual');
        $b = body_json(); $id = (int)($b['id'] ?? 0);
        out(['ok' => true, 'offer' => sb_rpc('agr_offer_respond', ['p_token' => $token, 'p_offer_id' => $id,
            'p_decision' => ($b['status'] ?? '') === 'terima' ? 'terima' : 'tolak'])]);
    }
    case 'booking-create': {
        $u = require_session($token, 'pembeli');
        $b = body_json();
        $result = sb_rpc('agr_order_create', ['p_token' => $token, 'p_product_id' => (int)($b['product_id'] ?? 0),
            'p_quantity' => (float)($b['jumlah'] ?? 0), 'p_offer_id' => (int)($b['offer_id'] ?? 0),
            'p_method' => (string)($b['metode_dp'] ?? ''), 'p_delivery' => (string)($b['jadwal_kirim'] ?? ''),
            'p_carrier' => (string)($b['ekspedisi'] ?? '')]);
        out(['ok' => true] + (is_array($result) ? $result : []), 201);
    }

    case 'order-create': {
        require_session($token, 'pembeli');
        $b = body_json();
        $result = sb_rpc('agr_order_create', ['p_token' => $token, 'p_product_id' => (int)($b['product_id'] ?? 0),
            'p_quantity' => (float)($b['jumlah'] ?? 0), 'p_offer_id' => 0,
            'p_method' => (string)($b['metode_dp'] ?? ''), 'p_delivery' => (string)($b['jadwal_kirim'] ?? ''),
            'p_carrier' => (string)($b['ekspedisi'] ?? '')]);
        out(['ok' => true] + (is_array($result) ? $result : []), 201);
    }

    /* ---- BAYAR DP: konfirmasi pembayaran (gateway/transfer manual) ---- */
    case 'dp-confirm': {
        require_session($token, 'pembeli'); $b = body_json();
        out(sb_rpc('agr_payment_submit', ['p_token' => $token, 'p_transaction_id' => (int)($b['transaction_id'] ?? 0),
            'p_proof' => (string)($b['bukti'] ?? ''), 'p_note' => '', 'p_reference' => (string)($b['ref_payment'] ?? '')]));
    }

    /* ---- PELUNASAN DP: pembeli upload bukti -> approval penjual ---- */
    case 'pelunasan-submit': {
        $u = require_session($token, 'pembeli');
        $b = body_json();
        $id = (int)($b['transaction_id'] ?? 0);
        out(sb_rpc('agr_payment_submit', ['p_token' => $token, 'p_transaction_id' => $id,
            'p_proof' => (string)($b['bukti'] ?? ''), 'p_note' => (string)($b['catatan'] ?? ''), 'p_reference' => '']));
    }
    case 'pelunasan-list': {
        $u = require_session($token, 'penjual');
        out(array_values(array_filter(sb_rpc('agr_transactions_list', ['p_token' => $token, 'p_side' => 'penjualan']), fn($tx) => ($tx['status'] ?? '') === 'menunggu_approval')));
    }
    case 'pelunasan-respond': {
        $u = require_session($token, 'penjual');
        $b = body_json(); $id = (int)($b['transaction_id'] ?? 0);
        out(sb_rpc('agr_payment_approve', ['p_token' => $token, 'p_transaction_id' => $id, 'p_approve' => ($b['keputusan'] ?? '') === 'setuju']));
    }

    /* ---- KIRIM & SELESAI ---- */
    case 'tx-kirim': {
        $u = require_session($token, 'penjual');
        $b = body_json(); $id = (int)($b['transaction_id'] ?? 0);
        $rows = sb('transaksi', 'GET', ['id=eq.' . $id]);
        if (!$rows || (int)$rows[0]['seller_id'] !== (int)$u['id']) err('Tidak ditemukan / bukan hak Anda', 403);
        sb('transaksi', 'PATCH', ['id=eq.' . $id], ['status' => 'dikirim',
            'tracking_code' => $b['tracking_code'] ?? '', 'ekspedisi' => $b['ekspedisi'] ?? '']);
        if (!empty($b['booking_id'])) sb('bookings', 'PATCH', ['id=eq.' . (int)$b['booking_id']], ['status' => 'dikirim', 'tracking_code' => $b['tracking_code'] ?? '']);
        out(['ok' => true]);
    }
    case 'tx-complete': {
        $u = require_session($token);
        $b = body_json(); $id = (int)($b['transaction_id'] ?? 0);
        $rows = sb('transaksi', 'GET', ['id=eq.' . $id]);
        if (!$rows) err('Transaksi tidak ditemukan', 404);
        if (!in_array($u['role'], ['admin']) && (int)$rows[0]['buyer_id'] !== (int)$u['id'] && (int)$rows[0]['seller_id'] !== (int)$u['id']) err('Bukan transaksi Anda', 403);
        if ($rows[0]['status'] !== 'dikirim') err('Hanya transaksi berstatus dikirim yang dapat diselesaikan', 409);
        sb('transaksi', 'PATCH', ['id=eq.' . $id], ['status' => 'completed']);
        if (!empty($rows[0]['booking_id'])) sb('bookings', 'PATCH', ['id=eq.' . $rows[0]['booking_id']], ['status' => 'completed']);
        out(['ok' => true]);
    }

    /* ---- TRANSAKSI & LAPORAN (dashboard) ---- */
    case 'transactions': {
        $u = require_session($token);
        $side = $_GET['side'] ?? ($u['role'] === 'penjual' ? 'penjualan' : 'pembelian');
        out(sb_rpc('agr_transactions_list', ['p_token' => $token, 'p_side' => $side]));
    }
    case 'report-admin': {
        require_admin($token);
        $tx = sb_rpc('agr_transactions_list', ['p_token' => $token, 'p_side' => 'pembelian']);
        $gmv = 0; $rev = 0; $perbulan = [];
        foreach ($tx as $t) {
            $gmv += (float)$t['harga_total']; $rev += (float)($t['potongan_platform'] ?? 0);
            $mk = substr((string)$t['created_at'], 0, 7);
            $perbulan[$mk] = ($perbulan[$mk] ?? 0) + (float)$t['harga_total'];
        }
        out(['ok' => true, 'gmv' => $gmv, 'pendapatan_platform' => $rev, 'per_bulan' => $perbulan, 'jumlah' => count($tx)]);
    }

    /* ---- EVIDEN / KETELUSURAN ---- */
    case 'evidence-add': {
        $u = require_session($token);
        $b = body_json();
        sb('eviden', 'POST', [], ['transaction_id' => (int)($b['transaction_id'] ?? 0), 'uploader_id' => $u['id'],
            'tahap' => $b['tahap'] ?? 'pengemasan', 'keterangan' => $b['keterangan'] ?? '', 'foto' => $b['foto'] ?? '',
            'lat' => $b['lat'] ?? null, 'lng' => $b['lng'] ?? null, 'created_at' => date('c')]);
        out(['ok' => true], 201);
    }
    case 'evidence-list': {
        $id = (int)($_GET['transaction_id'] ?? 0);
        out(sb('eviden', 'GET', ['transaction_id=eq.' . $id, 'select=*', 'order=created_at.asc']));
    }

    /* ---- RATINGS dua arah ---- */
    case 'rate': {
        $u = require_session($token);
        $b = body_json();
        sb('ratings', 'POST', [], ['transaction_id' => (int)($b['transaction_id'] ?? 0), 'from_user' => $u['id'],
            'to_user' => (int)($b['to_user'] ?? 0), 'skor' => max(1, min(5, (int)($b['skor'] ?? 5))),
            'ulasan' => $b['ulasan'] ?? '', 'aspek' => json_encode($b['aspek'] ?? new stdClass()), 'created_at' => date('c')]);
        out(['ok' => true], 201);
    }
    case 'ratings-for': {
        $uid = (int)($_GET['user_id'] ?? 0);
        $rs = sb('ratings', 'GET', ['to_user=eq.' . $uid, 'select=skor,ulasan,created_at']);
        $avg = $rs ? round(array_sum(array_column($rs, 'skor')) / count($rs), 2) : null;
        out(['ok' => true, 'rata_rata' => $avg, 'jumlah' => count($rs), 'ulasan' => $rs]);
    }

    /* ---- FAVORIT penjual/produk ---- */
    case 'favorite-toggle': {
        $u = require_session($token, 'pembeli');
        $b = body_json();
        $tt = in_array($b['target_type'] ?? '', ['produk','penjual']) ? $b['target_type'] : 'produk';
        $result = sb_rpc('agr_favorite_toggle', ['p_token' => $token, 'p_target_type' => $tt, 'p_target_id' => (int)($b['target_id'] ?? 0)]);
        out(['ok' => true, 'favorit' => (bool)($result['favorit'] ?? false)]);
    }
    case 'favorites': {
        require_session($token, 'pembeli');
        out(sb_rpc('agr_favorites_list', ['p_token' => $token]));
    }

    /* ---- PESAN PRODUK: percakapan buyer dengan pemilik listing ---- */
    case 'chat-start': {
        require_session($token, 'pembeli');
        $b = body_json(); $productId = (int)($b['product_id'] ?? 0);
        if (!$productId) err('Produk tidak valid');
        out(sb_rpc('agr_product_chat_start', ['p_token' => $token, 'p_product_id' => $productId]), 201);
    }
    case 'chats': {
        require_session($token);
        out(sb_rpc('agr_product_chat_list', ['p_token' => $token]));
    }
    case 'chat-messages': {
        require_session($token);
        $id = (int)($_GET['id'] ?? 0); if (!$id) err('Percakapan tidak valid');
        out(sb_rpc('agr_product_chat_messages', ['p_token' => $token, 'p_conversation_id' => $id]));
    }
    case 'chat-send': {
        require_session($token);
        $b = body_json(); $id = (int)($b['conversation_id'] ?? 0);
        if (!$id) err('Percakapan tidak valid');
        out(['ok' => true, 'message' => sb_rpc('agr_product_chat_send', [
            'p_token' => $token, 'p_conversation_id' => $id, 'p_body' => (string)($b['body'] ?? ''),
        ])], 201);
    }

    /* ---- CHAT AI bridge (butuh backend Flask) ---- */
    case 'chat': {
        if ($CFG['flask_url'] === '') err('Chat AI butuh backend Flask (set AGR_ID_API_URL di config.php)', 503);
        $b = body_json();
        [$code, $res] = http_req('POST', rtrim($CFG['flask_url'], '/') . '/api/v1/chat', ['Content-Type: application/json'], json_encode($b));
        http_response_code($code ?: 200); echo $res; exit;
    }

    /* ---- BLOCKCHAIN / DOMPET CRYPTO bridge ---- */
    case 'crypto': {
        if ($CFG['flask_url'] === '') err('Dompet crypto butuh backend Flask (set AGR_ID_API_URL)', 503);
        $sub = preg_replace('/[^a-z\/]/', '', $_GET['sub'] ?? 'balance');
        [$code, $res] = http_req('GET', rtrim($CFG['flask_url'], '/') . '/api/v1/crypto/' . $sub . '?token=' . urlencode($token));
        http_response_code($code ?: 200); echo $res; exit;
    }

    /* ---- MEDIA: signature Cloudinary (kebijakan bucket publik/privat) ---- */
    case 'media-signature': {
        $u = require_session($token);
        $b = body_json();
        $visibility = $b['visibility'] ?? 'public';
        $purpose = $b['purpose'] ?? '';
        if ($visibility === 'public') {
            // Product photos are only issued to an active seller. Other public
            // evidence uploads must declare a known purpose explicitly.
            if ($purpose === 'product' || $purpose === '') {
                if ($u['role'] !== 'penjual') err('Hanya penjual yang dapat mengunggah foto produk publik', 403);
                $purpose = 'product';
            } elseif (!in_array($purpose, ['eviden', 'auction'], true)) {
                err('Purpose upload publik tidak valid');
            }
            $folder = 'agrid/public/' . $purpose;
        } elseif ($visibility === 'private') {
            if (!in_array($purpose, ['kyc', 'chat'], true)) err('Purpose privat tidak valid');
            $folder = 'agrid/private/' . $u['id'] . '/' . $purpose;
        } else {
            err('Visibility upload tidak valid');
        }
        $allowedFormats = $visibility === 'private' && $purpose === 'kyc'
            ? 'jpg,jpeg,png,webp,pdf' : 'jpg,jpeg,png,webp';
        $params = ['timestamp' => time(), 'folder' => $folder, 'tags' => 'agrid',
            'allowed_formats' => $allowedFormats, 'eager' => 'w_400,h_400,c_limit,quality_auto,f_auto|w_100,h_100,c_thumb,q_auto,f_webp'];
        out(['ok' => true] + cloudinary_signature($params)
            + ['endpoint' => 'https://api.cloudinary.com/v1_1/' . $CFG['cloudinary_cloud'] . ($visibility === 'private' ? '/auto/upload' : '/image/upload')]);
    }
    case 'media-private-url': {
        // pre-signed GET pendek utk dokumen privat — hanya pemilik / setelah DP dibayar
        $u = require_session($token);
        $pubId = preg_replace('#[^A-Za-z0-9_\-/]#', '', $_GET['public_id'] ?? '');
        if (!$pubId || strpos($pubId, 'agrid/private/') !== 0) err('public_id privat tidak valid');
        $ownerId = (int)explode('/', $pubId)[2];
        if ($ownerId !== (int)$u['id'] && $u['role'] !== 'admin') {
            $rel = sb('transaksi', 'GET', ['buyer_id=eq.' . $u['id'], 'status=in.(dp_paid,lunas,completed,dikirim)', 'select=id']);
            if (!$rel) err('Akses ditolak: dokumen privat hanya terbuka setelah DP dibayar', 403);
        }
        $exp = time() + 300; // 5 menit
        $sig = sha1("e=$exp/$pubId" . $CFG['cloudinary_secret']);
        out(['ok' => true, 'url' => "https://res.cloudinary.com/{$CFG['cloudinary_cloud']}/image/authenticated/s--{$sig}--/v{$exp}/{$pubId}?e=expire:{$exp}"]);
    }

    /* ---- DATA PEMBAYARAN PER AKUN ---- */
    case 'seller-payment-settings': {
        $u = require_session($token);
        $settingKey = 'pembayaran_penjual_' . (int)$u['id'];
        if (($_SERVER['REQUEST_METHOD'] ?? '') === 'GET') {
            $rows = get_pengaturan($settingKey);
            $cfg = json_decode((string)($rows[0]['value'] ?? ''), true);
            if (!is_array($cfg)) $cfg = [];
            out(['ok' => true] + array_merge(['metode_dp' => ['Transfer Bank'], 'rekening' => '', 'qris' => '', 'tujuan_tunai' => ''], $cfg));
        }
        $b = body_json();
        $allowed = ['Transfer Bank', 'QRIS', 'Tunai'];
        $methods = array_values(array_intersect($allowed, is_array($b['metode_dp'] ?? null) ? $b['metode_dp'] : []));
        $cfg = [
            'metode_dp' => $methods ?: ['Transfer Bank'],
            'rekening' => trim((string)($b['rekening'] ?? '')),
            'qris' => trim((string)($b['qris'] ?? '')),
            'tujuan_tunai' => trim((string)($b['tujuan_tunai'] ?? '')),
        ];
        if (strlen($cfg['rekening']) > 160 || strlen($cfg['qris']) > 500 || strlen($cfg['tujuan_tunai']) > 300) err('Data pembayaran terlalu panjang', 422);
        $saved = sb_rpc('agr_seller_payment_settings_save', ['p_token' => $token, 'p_settings' => $cfg]);
        out(['ok' => true, 'settings' => is_array($saved) ? $saved : $cfg]);
    }

    /* ---- PENGATURAN admin ---- */
    case 'settings': {
        if (($_SERVER['REQUEST_METHOD'] ?? '') === 'GET') {
            if ($token !== '') {
                $activeSession = sb('sessions', 'GET', ['token=eq.' . urlencode($token), 'select=user_id,active_role,expires_at']);
                if ($activeSession && strtotime((string)$activeSession[0]['expires_at']) > time() && ($activeSession[0]['active_role'] ?? '') === 'admin') out(get_pengaturan());
            }
            $publicKeys = ['footer_tagline','footer_email','footer_wa','footer_alamat','footer_copy','ticker_harian','beranda_aktif'];
            out(array_values(array_filter(get_pengaturan(), fn($row) => in_array($row['key'] ?? '', $publicKeys, true))));
        }
        require_admin($token); $b = body_json();
        out(sb_rpc('agr_admin_settings_save', ['p_token' => $token, 'p_settings' => (object)$b]));
    }

    case 'checkout-config': {
        $keys = ['fitur_pembayaran','fitur_booking_dp','fitur_biaya','persen_dp','biaya_penanganan','biaya_tambahan_flat'];
        $all = get_pengaturan(); $cfg = [];
        foreach ($all as $row) if (in_array($row['key'] ?? '', $keys, true)) $cfg[$row['key']] = $row['value'];
        out(['payment_enabled' => ($cfg['fitur_pembayaran'] ?? '1') !== '0',
            'dp_enabled' => ($cfg['fitur_booking_dp'] ?? '1') !== '0',
            'fees_enabled' => ($cfg['fitur_biaya'] ?? '1') !== '0',
            'dp_percent' => (float)($cfg['persen_dp'] ?? 20)]);
    }

    default:
        err('Action tidak dikenal: ' . htmlspecialchars($action), 404);
}

/* ==================== helpers ==================== */
function get_pengaturan(?string $key = null): array {
    $q = $key ? ['key=eq.' . urlencode($key), 'select=value'] : ['select=*'];
    try { return sb('pengaturan', 'GET', $q); } catch (Throwable $e) { return []; }
}
function seller_profile_missing(array $u): array {
    $missing = [];
    foreach ([
        'nama' => 'nama lengkap/nama usaha', 'no_hp' => 'nomor telepon',
        'alamat' => 'alamat lengkap', 'kota' => 'kota/kabupaten', 'provinsi' => 'provinsi',
    ] as $field => $label) {
        if (trim((string)($u[$field] ?? '')) === '') $missing[] = $label;
    }
    if (strtolower(trim((string)($u['nama'] ?? ''))) === strtolower(trim((string)($u['username'] ?? '')))
        && !in_array('nama lengkap/nama usaha', $missing, true)) $missing[] = 'nama lengkap/nama usaha';
    if (!is_numeric($u['lat'] ?? null) || !is_numeric($u['lng'] ?? null)) $missing[] = 'koordinat lokasi (GPS)';
    $sellerTypes = ['Perorangan','Kelompok/Paguyuban','Koperasi','Perusahaan'];
    $tipe = $u['tipe_penjual'] ?? null;
    if (!in_array($tipe, $sellerTypes, true)) $missing[] = 'tipe penjual';
    elseif ($tipe !== 'Perorangan') {
        if (trim((string)($u['npwp'] ?? '')) === '') $missing[] = 'NPWP usaha/organisasi';
        if (trim((string)($u['nib'] ?? '')) === '') $missing[] = 'NIB usaha/organisasi';
    }
    return $missing;
}
function public_user(array $u): array {
    unset($u['password_hash']);
    $roles = $u['roles'] ?? [];
    if (is_string($roles)) $roles = json_decode($roles, true) ?: [];
    $u['roles'] = is_array($roles) ? $roles : [];
    if (($u['role'] ?? '') === 'penjual' && !empty($u['tipe_penjual'])) $u['tipe'] = $u['tipe_penjual'];
    if (($u['role'] ?? '') === 'pembeli' && !empty($u['tipe_pembeli'])) $u['tipe'] = $u['tipe_pembeli'];
    return $u;
}
function require_session(string $token, ?string $role = null): array {
    if ($token === '') err('Login diperlukan (sertakan header X-Agr-Token)', 401);
    $s = sb('sessions', 'GET', ['token=eq.' . $token, 'select=user_id,expires_at,active_role']);
    if (!$s) err('Token tidak valid', 401);
    if (strtotime((string)$s[0]['expires_at']) < time()) { sb('sessions', 'DELETE', ['token=eq.' . $token]); err('Sesi kedaluwarsa', 401); }
    $u = sb('users', 'GET', ['id=eq.' . $s[0]['user_id'], 'select=*'])[0] ?? null;
    if (!$u) err('User tidak ditemukan', 401);
    $roles = $u['roles'] ?? [];
    if (is_string($roles)) $roles = json_decode($roles, true) ?: [];
    $active = $s[0]['active_role'] ?? $u['role'];
    if (!is_array($roles) || !in_array($active, $roles, true)) $active = $u['role'];
    $u['role'] = $active;
    $u['roles'] = is_array($roles) ? $roles : [$u['role']];
    if ($role && $u['role'] !== $role) err("Hanya untuk role: $role", 403);
    return $u;
}
function require_admin(string $token): array {
    $u = require_session($token);
    if ($u['role'] !== 'admin') err('Akses khusus admin', 403);
    return $u;
}
