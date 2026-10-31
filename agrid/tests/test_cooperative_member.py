"""Regression tests for cooperative member access and marketplace discovery."""
import os
import secrets
import sys
import unittest
from pathlib import Path

os.environ["AGR_DATABASE_URL"] = "sqlite://"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as marketplace


class CooperativeMemberTests(unittest.TestCase):
    def setUp(self):
        marketplace.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        with marketplace.app.app_context():
            marketplace.db.drop_all()
            marketplace.db.create_all()
            member = marketplace.User(
                username="member", nama="Anggota Uji", email="member@example.test",
                password="hash", role="pembeli", roles=["pembeli"],
            )
            seller = marketplace.User(
                username="seller", nama="Petani Uji", email="seller@example.test",
                password="hash", role="penjual", roles=["penjual"],
            )
            other = marketplace.User(
                username="other", nama="Anggota Lain", email="other@example.test",
                password="hash", role="pembeli", roles=["pembeli"],
            )
            cooperative = marketplace.Koperasi(kode="KOPTEST", nama="Koperasi Uji", status="aktif")
            marketplace.db.session.add_all([member, seller, other, cooperative])
            marketplace.db.session.flush()
            marketplace.db.session.add_all([
                marketplace.KeanggotaanKoperasi(
                    user_id=member.id, koperasi_id=cooperative.id, nomor_anggota="A-001",
                    nama_terdaftar=member.nama, status="terdaftar",
                ),
                marketplace.KeanggotaanKoperasi(
                    user_id=seller.id, koperasi_id=cooperative.id, nomor_anggota="A-002",
                    nama_terdaftar=seller.nama, status="terdaftar",
                ),
                marketplace.KoperasiAnggota(
                    koperasi_id=cooperative.id, external_id="external-joiner",
                    nomor_anggota="A-003", nama="Anggota Baru", email="joiner@example.test",
                    status="aktif",
                ),
                marketplace.Product(
                    seller_id=seller.id, nama_produk="Cabai Koperasi", kategori="Pertanian",
                    harga=12000, satuan="kg", stok=20, status="aktif",
                ),
            ])
            marketplace.db.session.commit()
            self.member_id = member.id
            self.other_id = other.id
            self.cooperative_id = cooperative.id
            self.member_number = "A-001"
        self.client = marketplace.app.test_client()

    def tearDown(self):
        with marketplace.app.app_context():
            marketplace.db.session.remove()
            marketplace.db.drop_all()

    def login_as(self, user_id):
        with self.client.session_transaction() as session:
            session["uid"] = user_id

    def test_member_dashboard_shows_products_from_verified_co_members(self):
        self.login_as(self.member_id)
        response = self.client.get(f"/ruang-koperasi/{self.cooperative_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Produk anggota koperasi", response.data)
        self.assertIn(b"Cabai Koperasi", response.data)

    def test_member_dashboard_blocks_other_marketplace_accounts(self):
        self.login_as(self.other_id)
        response = self.client.get(f"/ruang-koperasi/{self.cooperative_id}")
        self.assertEqual(response.status_code, 404)

    def test_member_verification_token_only_returns_membership_status(self):
        with marketplace.app.app_context():
            membership = marketplace.KeanggotaanKoperasi.query.filter_by(
                user_id=self.member_id, koperasi_id=self.cooperative_id
            ).one()
            token = marketplace.cooperative_member_signer().dumps({
                "membership_id": membership.id,
                "user_id": self.member_id,
                "koperasi_id": self.cooperative_id,
            })
        response = self.client.get(f"/member/verify/{token}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"ANGGOTA TERVERIFIKASI", response.data)
        self.assertIn(b">Aktif</span>", response.data)
        self.assertNotIn(b"Rp", response.data)
        self.assertEqual(self.client.get("/member/verify/not-a-signed-token").status_code, 404)

    def test_membership_request_matches_official_roster(self):
        with marketplace.app.app_context():
            joiner = marketplace.User(
                username="joiner", nama="Anggota Baru", email="joiner@example.test",
                password="hash", role="pembeli", roles=["pembeli"],
            )
            marketplace.db.session.add(joiner)
            marketplace.db.session.commit()
            joiner_id = joiner.id
        self.login_as(joiner_id)
        with self.client.session_transaction() as session:
            session["_csrf"] = "test-csrf"
        response = self.client.post("/akun/keanggotaan-koperasi", data={
            "_csrf": "test-csrf",
            "koperasi_id": str(self.cooperative_id),
            "nomor_anggota": "A-003",
            "nama_terdaftar": "Anggota Baru",
        })
        self.assertEqual(response.status_code, 302)
        with marketplace.app.app_context():
            membership = marketplace.KeanggotaanKoperasi.query.filter_by(
                user_id=joiner_id, koperasi_id=self.cooperative_id
            ).one()
            self.assertEqual(membership.status, "terdaftar")

    def test_cooperative_sync_updates_directory_and_roster_with_scoped_role(self):
        token = secrets.token_urlsafe(32)
        with marketplace.app.app_context():
            api_token = marketplace.models_api.ApiToken(
                nama="Test koperasi", token_hash=marketplace.security.hash_token(token),
                role="koperasi", revoked=False,
            )
            marketplace.db.session.add(api_token)
            marketplace.db.session.commit()
        response = self.client.post("/api/v1/cooperatives/sync", json={
            "cooperatives": [{
                "id": "source-coop-1", "code": "NEWSYNC", "name": "Koperasi Sinkron",
                "active": True,
                "members": [{"id": "source-member-1", "number": "NS-001",
                             "name": "Anggota Sinkron", "active": True}],
            }],
        }, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 200, response.get_json())
        with marketplace.app.app_context():
            cooperative = marketplace.Koperasi.query.filter_by(kode="NEWSYNC").one()
            roster = marketplace.KoperasiAnggota.query.filter_by(
                koperasi_id=cooperative.id, nomor_anggota="NS-001"
            ).one()
            self.assertEqual(roster.nama, "Anggota Sinkron")


if __name__ == "__main__":
    unittest.main()
