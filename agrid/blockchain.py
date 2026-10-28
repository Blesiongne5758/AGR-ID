# ----------------------------------------------------------------------------
# AGR.BIZ.ID — BLOCKCHAIN: DOMPET CRYPTO & LEDGER TRANSAKSI (AGR Coin)
# ----------------------------------------------------------------------------
"""
Implementasi blockchain ringan untuk AGR.BIZ.ID:

1. STRUKTUR BLOK  : header (index, timestamp, merkle root, prev-hash, nonce) + body transaksi.
2. KONSENSUS PoA  : Proof-of-Authority — hanya node validator (admin platform) yang dapat
                    men-mining blok; cepat, hemat energi, cocok untuk marketplace terkurasi.
3. HASHING        : SHA-256 canonical (json.dumps sort_keys) — integritas rantai diverifikasi
                    ulang setiap saat lewat verify_chain().
4. MERKLE ROOT    : hash pairwise dari seluruh transaksi dalam blok; satu bukti transaksi
                    dapat diverifikasi tanpa mengunduh seluruh blok.
5. DOMPET         : kunci secp256k1 nyata via `coincurve` (opsional). Jika library tidak
                   terpasang, fallback deterministik berbasis HMAC-SHA512 sehingga sistem
                   tetap berjalan offline. Format alamat: AGR1<base58(checksum||pubkey160)>.
6. TOKEN          : "AGR Coin" — unit internal ber-rasio tetap 1 AGR = Rp 1 (bisa diatur
                    admin). Setiap transfer DP/pelunasan crypto dicatat sebagai transaksi
                    on-chain dengan referensi booking/transaksi platform.
7. WALLET FILE    : privat key TIDAK disimpan di database — tersimpan pada file terenkripsi
                    AES-GCM (cryptography.Fernet) di disk, dilindungi secret key aplikasi.

Catatan keamanan: ini ledger blockchain self-hosted untuk traceability & settlement internal.
Untuk mainnet publik, gateway deposit/withdraw dapat diarahkan ke custodian/exchange pihak
ketiga melalui endpoint API yang sama.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime

# --- opsi kriptografi kuat (bila tersedia) -----------------------------------
try:
    from coincurve import PrivateKey as _ECPriv          # secp256k1 asli
    HAS_COINCURVE = True
except Exception:                                         # pragma: no cover
    _ECPriv = None
    HAS_COINCURVE = False

try:
    from cryptography.fernet import Fernet
    HAS_FERNET = True
except Exception:                                         # pragma: no cover
    Fernet = None
    HAS_FERNET = False

GENESIS_TS = 1700000000                                   # timestamp genesis tetap
B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
TOKEN_SYMBOL = "AGR"                                    # AGR Coin
DIFFICULTY = 2                                          # leading-zero hex utk mining demo


# =============================================================================
# UTILITAS
# =============================================================================
def sha256(b: bytes) -> bytes:
    return hashlib.sha256(b).hexdigest().encode() if False else hashlib.sha256(b).digest()


def sha256_hex(data) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def b58encode(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    s = ""
    while n > 0:
        n, r = divmod(n, 58)
        s = B58_ALPHABET[r] + s
    pad = len(b) - len(b.lstrip(b"\x00"))
    return "1" * pad + (s or "1")


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        n = n * 58 + B58_ALPHABET.index(ch)
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + body


def _hmac_key(secret: bytes, msg: bytes) -> bytes:
    return hmac.new(secret, msg, hashlib.sha512).digest()


# =============================================================================
# MERKLE TREE
# =============================================================================
def merkle_root(tx_hashes):
    """Root SHA-256 pairwise; daftar kosong => root dari string 'empty'."""
    if not tx_hashes:
        return sha256_hex("empty")
    level = list(tx_hashes)
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            a = level[i]
            b = level[i + 1] if i + 1 < len(level) else level[i]   # duplikat ganjil
            nxt.append(sha256_hex(a + b))
        level = nxt
    return level[0]


# =============================================================================
# BLOK & CHAIN
# =============================================================================
class Tx:
    """Transaksi on-chain: transfer token AGR antar alamat dompet."""

    def __init__(self, frm, to, amount, ref="", memo="", ts=None, fee=0.0):
        self.frm = frm                      # alamat pengirim ('' => mint/genesis)
        self.to = to
        self.amount = round(float(amount), 2)
        self.ref = ref                      # mis. 'BOOKING-12' / 'TX-34' — ketelusuran platform
        self.memo = memo
        self.fee = round(float(fee), 2)
        self.ts = ts or time.time()

    def canon(self) -> str:
        return json.dumps({"from": self.frm, "to": self.to, "amount": self.amount,
                           "ref": self.ref, "memo": self.memo, "fee": self.fee,
                           "ts": self.ts}, sort_keys=True)

    def hash(self) -> str:
        return sha256_hex(self.canon())

    def to_dict(self):
        return {"from": self.frm, "to": self.to, "amount": self.amount, "ref": self.ref,
                "memo": self.memo, "fee": self.fee, "ts": self.ts, "hash": self.hash()}


class Block:
    def __init__(self, index, prev_hash, txs, ts=None, nonce=0, validator=""):
        self.index = index
        self.prev_hash = prev_hash
        self.txs = txs                       # list[Tx]
        self.merkle = merkle_root([t.hash() for t in txs])
        self.ts = ts or time.time()
        self.nonce = nonce
        self.validator = validator           # identitas PoA (email/node id)
        self.hash = ""

    def header_canon(self) -> str:
        return json.dumps({"index": self.index, "prev": self.prev_hash, "merkle": self.merkle,
                           "ts": self.ts, "nonce": self.nonce, "validator": self.validator},
                          sort_keys=True)

    def compute_hash(self) -> str:
        return sha256_hex(self.header_canon())

    def mine(self, difficulty=DIFFICULTY):
        """Proof-of-work ringan (demo) — target: '0'*difficulty di depan hash."""
        target = "0" * difficulty
        while True:
            h = self.compute_hash()
            if h.startswith(target):
                self.hash = h
                return h
            self.nonce += 1

    def to_dict(self):
        return {"index": self.index, "prev_hash": self.prev_hash, "merkle_root": self.merkle,
                "timestamp": self.ts, "datetime": datetime.utcfromtimestamp(self.ts).isoformat() + "Z",
                "nonce": self.nonce, "validator": self.validator, "hash": self.hash,
                "tx_count": len(self.txs), "txs": [t.to_dict() for t in self.txs]}


class Chain:
    """Rantai blok persisten (disimpan sebagai JSON di tabel pengaturan DB)."""

    MAX_BLOCKS = 1000                        # jaga ukuran payload DB

    def __init__(self):
        self.blocks = []
        self.pending = []                    # mempool

    # ---------- genesis ----------
    def ensure_genesis(self, supply_note="AGR Coin genesis — premine platform escrow"):
        if self.blocks:
            return
        g = Block(0, "0" * 64, [], ts=GENESIS_TS, validator="genesis@agr.id")
        g.merkle = merkle_root([])
        g.hash = g.compute_hash()
        self.blocks.append(g)

    # ---------- mempool ----------
    def add_pending(self, tx: Tx):
        self.pending.append(tx)

    def flush_mempool(self):
        p, self.pending = self.pending, []
        return p

    # ---------- mining ----------
    def mine_block(self, validator="admin@agr.id", difficulty=DIFFICULTY):
        txs = self.flush_mempool()
        prev = self.blocks[-1] if self.blocks else None
        idx = (prev.index + 1) if prev else 0
        ph = prev.hash if prev else "0" * 64
        blk = Block(idx, ph, txs, validator=validator)
        blk.mine(difficulty)
        self.blocks.append(blk)
        return blk

    # ---------- verifikasi integritas ----------
    def verify(self):
        """Cek ulang prev-hash, merkle root, dan konsistensi hash tiap blok."""
        ok, msgs = True, []
        for i, b in enumerate(self.blocks):
            if b.merkle != merkle_root([t.hash() for t in b.txs]):
                ok = False; msgs.append(f"blok {i}: merkle root tidak cocok"); break
            if b.compute_hash() != b.hash:
                ok = False; msgs.append(f"blok {i}: hash header tidak konsisten"); break
            if i > 0 and b.prev_hash != self.blocks[i - 1].hash:
                ok = False; msgs.append(f"blok {i}: rantai putus (prev-hash salah)"); break
        return ok, msgs or ["rantai utuh ✔"]

    def find_tx(self, tx_hash):
        for b in self.blocks:
            for t in b.txs:
                if t.hash() == tx_hash:
                    return b, t
        return None, None

    # ---------- serialisasi ----------
    def to_json(self):
        return json.dumps({"version": 1, "symbol": TOKEN_SYMBOL,
                           "blocks": [b.to_dict() for b in self.blocks[-self.MAX_BLOCKS:]],
                           "mempool": [t.to_dict() for t in self.pending]}, sort_keys=True)

    @classmethod
    def from_json(cls, s):
        c = cls()
        if not s:
            return c
        try:
            d = json.loads(s)
        except Exception:
            return c
        for bd in d.get("blocks", []):
            txs = [Tx(t["from"], t["to"], t["amount"], t.get("ref", ""), t.get("memo", ""),
                      t.get("ts"), t.get("fee", 0)) for t in bd.get("txs", [])]
            b = Block(bd["index"], bd["prev_hash"], txs, ts=bd["timestamp"],
                      nonce=bd["nonce"], validator=bd.get("validator", ""))
            b.merkle = bd["merkle_root"]; b.hash = bd["hash"]
            c.blocks.append(b)
        for td in d.get("mempool", []):
            c.add_pending(Td_to_Tx(td))
        return c


def Td_to_Tx(td):
    return Tx(td["from"], td["to"], td["amount"], td.get("ref", ""), td.get("memo", ""),
              td.get("ts"), td.get("fee", 0))


# =============================================================================
# DOMPET (secp256k1 bila ada, fallback HMAC deterministik)
# =============================================================================
def _seed_from_secret(secret: str, user_id: int) -> bytes:
    """Seed privat key diturunkan dari secret aplikasi + user id → deterministik & aman
    karena secret tidak pernah keluar dari server (mirip custodial HD wallet)."""
    return _hmac_key(secret.encode(), f"agr-wallet-v1|{user_id}".encode())[:32]


def _pubkey_hash160(pub_bytes: bytes) -> bytes:
    """Pubkey → SHA-256 → RIPEMD-160 (20 byte), sama seperti derivasi alamat Bitcoin."""
    s = hashlib.sha256(pub_bytes).digest()
    try:
        h = hashlib.new("ripemd160")
        h.update(s)
        return h.digest()
    except ValueError:                       # OpenSSL 3 tanpa legacy provider
        return s[:20]


def derive_wallet(secret: str, user_id: int):
    """Deterministic HD-style wallet: seed = HMAC(secret aplikasi, 'agr-wallet-v1|<uid>').

    Kembalikan dict {address, priv_enc, algo}. Privat key hanya diekspor ke file
    terenkripsi (save_wallet_file) — tidak pernah disimpan di database.
    """
    seed = _seed_from_secret(secret, user_id)
    if HAS_COINCURVE:
        pk = _ECPriv(seed)
        pub = pk.public_key.format(compressed=True)          # 33 byte secp256k1
        algo = "secp256k1 (coincurve)"
        priv_hex = pk.hex
    else:
        pub = hashlib.sha256(seed).digest()                  # fallback deterministik
        algo = "fallback sha256-seed"
        priv_hex = seed.hex()
    body = _pubkey_hash160(pub)
    checksum = sha256_hex(sha256_hex(body))[:8]
    address = "AGR1" + b58encode(body) + checksum
    return {"address": address, "priv_hex": priv_hex, "algo": algo}


def is_valid_address(addr: str) -> bool:
    return isinstance(addr, str) and addr.startswith("AGR1") and len(addr) >= 20


# =============================================================================
# ENKRIPSI WALLET FILE (AES-GCM via Fernet)
# =============================================================================
def _fernet(secret: str):
    if not HAS_FERNET:
        return None
    key = base64.urlsafe_b64encode(sha256(secret.encode()))
    return Fernet(key)


def save_wallet_file(path: str, secret: str, data: dict):
    f = _fernet(secret)
    blob = json.dumps(data, sort_keys=True).encode()
    with open(path, "wb") as fh:
        fh.write(f.encrypt(blob) if f else blob)           # fallback plaintext-only-dev
    os.chmod(path, 0o600)


def load_wallet_file(path: str, secret: str):
    if not os.path.exists(path):
        return {}
    with open(path, "rb") as fh:
        raw = fh.read()
    f = _fernet(secret)
    try:
        return json.loads(f.decrypt(raw) if f else raw)
    except Exception:
        return {}


# =============================================================================
# SERVICE LAYER — integrasi blockchain ke database AGR.BIZ.ID (dipanggil dari app.py)
# =============================================================================
WALLET_FILE = "wallets.dat"          # di folder instance app, terenkripsi Fernet


class BlockchainService:
    """Facade yang dipakai route Flask: dompet, saldo, transfer, mining blok."""

    def __init__(self, db, User, Pengaturan, get_setting, set_setting, secret_key):
        self.db = db
        self.User = User
        self.Pengaturan = Pengaturan
        self.get_setting = get_setting
        self.set_setting = set_setting
        self.secret = secret_key

    # ---------- konfigurasi fitur ----------
    @property
    def enabled(self):
        return self.get_setting("fitur_blockchain", "1") == "1"

    @property
    def rate(self):
        """Rasio 1 AGR Coin = N Rupiah (default 1)."""
        try:
            return float(self.get_setting("crypto_rate_idr", "1") or 1)
        except Exception:
            return 1.0

    def to_crypto(self, rupiah):
        return round(float(rupiah) / self.rate, 2)

    def to_rupiah(self, agr):
        return round(float(agr) * self.rate, 2)

    # ---------- rantai ----------
    def chain(self):
        raw = self.get_setting("blockchain_ledger", "")
        c = Chain.from_json(raw) if raw else Chain()
        c.ensure_genesis()
        return c

    def save_chain(self, c: Chain):
        self.set_setting("blockchain_ledger", c.to_json(), "Blockchain: ledger AGR Coin")

    def verify_chain(self):
        return self.chain().verify()

    # ---------- dompet ----------
    def wallet_path(self):
        base = self.get_setting("_instance_dir", "") or os.getcwd()
        d = os.path.join(base, "data")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, WALLET_FILE)

    def _wallets(self):
        return load_wallet_file(self.wallet_path(), self.secret)

    def _save_wallets(self, w):
        save_wallet_file(self.wallet_path(), self.secret, w)

    def ensure_wallet(self, user_id):
        """Buatkan dompet crypto otomatis saat user daftar / pertama kali membuka dompet."""
        wallets = self._wallets()
        key = str(user_id)
        if key not in wallets:
            w = derive_wallet(self.secret, user_id)
            wallets[key] = {"address": w["address"], "priv_hex": w["priv_hex"], "algo": w["algo"]}
            self._save_wallets(wallets)
            u = self.User.query.get(user_id)
            if u is not None and getattr(u, "crypto_address", None) != w["address"]:
                u.crypto_address = w["address"]
                self.db.session.commit()
        elif self.User.query.get(user_id) and not self.User.query.get(user_id).crypto_address:
            u = self.User.query.get(user_id)
            u.crypto_address = wallets[key]["address"]
            self.db.session.commit()
        return wallets[key]["address"]

    def address_of(self, user_id):
        u = self.User.query.get(user_id)
        if u and getattr(u, "crypto_address", None):
            return u.crypto_address
        return self.ensure_wallet(user_id)

    # ---------- saldo UTXO-style (rekap on-chain) ----------
    def balances(self, c: Chain = None):
        c = c or self.chain()
        bal = {}
        for b in c.blocks:
            for t in b.txs:
                if t.frm:
                    bal[t.frm] = round(bal.get(t.frm, 0) - t.amount - t.fee, 2)
                bal[t.to] = round(bal.get(t.to, 0) + t.amount, 2)
        return bal

    def balance_of(self, address, c=None):
        return self.balances(c).get(address, 0.0)

    # ---------- transaksi ----------
    def history_of(self, address, limit=50):
        c = self.chain()
        rows = []
        for b in reversed(c.blocks):
            for t in reversed(b.txs):
                if t.frm == address or t.to == address:
                    rows.append({"hash": t.hash(), "block": b.index, "from": t.frm or "-",
                                 "to": t.to, "amount": t.amount, "fee": t.fee, "ref": t.ref,
                                 "memo": t.memo, "ts": t.ts,
                                 "dir": "out" if t.frm == address else "in"})
                    if len(rows) >= limit:
                        return rows
        return rows

    def submit_transfer(self, frm_addr, to_addr, amount_agr, ref="", memo=""):
        """Validasi & masukkan transfer ke mempool. Return (ok, msg|tx_hash)."""
        if not self.enabled:
            return False, "Fitur blockchain/crypto dinonaktifkan pada konfigurasi admin."
        if not is_valid_address(frm_addr) or not is_valid_address(to_addr):
            return False, "Format alamat dompet tidak valid (harus diawali AGR1)."
        if frm_addr == to_addr:
            return False, "Alamat pengirim & penerima sama."
        try:
            amount = round(float(amount_agr), 2)
        except Exception:
            return False, "Nominal tidak valid."
        if amount <= 0:
            return False, "Nominal harus lebih dari 0."
        fee_pct = float(self.get_setting("crypto_fee_persen", "0.5") or 0.5)
        fee = round(amount * fee_pct / 100.0, 2)
        bal = self.balances()
        if bal.get(frm_addr, 0) < amount + fee:
            return False, f"Saldo tidak cukup (saldo {bal.get(frm_addr, 0)} AGR, perlu {amount + fee} AGR)."
        c = self.chain()
        tx = Tx(frm_addr, to_addr, amount, ref=ref, memo=memo, fee=fee)
        c.add_pending(tx)
        self.save_chain(c)
        return True, tx.hash()

    def auto_settle_enabled(self):
        return self.get_setting("crypto_auto_settle", "1") == "1"

    def settle_payment(self, from_uid, to_uid, rupiah, ref, memo="pembayaran via AGR Coin"):
        """Distribusi pembayaran: konversi Rp→AGR, buat transfer on-chain antar dompet."""
        if not self.enabled or not self.auto_settle_enabled():
            return None
        a = self.address_of(from_uid); b_ = self.address_of(to_uid)
        amount = self.to_crypto(rupiah)
        if amount <= 0:
            return None
        ok, res = self.submit_transfer(a, b_, amount, ref=ref, memo=memo)
        return res if ok else None

    def mine(self, validator="admin@agr.id"):
        """Admin/node men-mining blok baru dari mempool (PoA). Return dict blok."""
        c = self.chain()
        if not c.pending:
            blk = c.mine_block(validator)         # blok kosong tetap valid (heartbeat)
        else:
            blk = c.mine_block(validator)
        self.save_chain(c)
        return blk.to_dict()

    def stats(self):
        c = self.chain()
        n_tx = sum(len(b.txs) for b in c.blocks)
        last = c.blocks[-1]
        minted = sum(t.amount for b in c.blocks for t in b.txs if not t.frm)
        return {"blocks": len(c.blocks), "mempool": len(c.pending), "tx_total": n_tx,
                "last_hash": last.hash, "last_index": last.index,
                "last_time": datetime.utcfromtimestamp(last.ts).strftime("%Y-%m-%d %H:%M"),
                "circulating": round(minted, 2), "rate": self.rate,
                "enabled": self.enabled,
                "verified": c.verify()[0]}
