"""Tests for the stores admin router + Visit/store binding."""

from app.models import Document, Store, Visit
from app.services.visits import ensure_visit_for_doc


class TestStoresCRUD:
    def test_create_and_list_store(self, client):
        r = client.post(
            "/api/stores",
            json={"name": "ร้านลุงโต้ง", "code": "RT-001"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "ร้านลุงโต้ง"
        assert body["code"] == "RT-001"
        assert body["active"] is True
        assert body["visit_count"] == 0

        listing = client.get("/api/stores").json()
        assert any(s["id"] == body["id"] for s in listing)

    def test_search_store(self, client):
        client.post("/api/stores", json={"name": "ร้านA"})
        client.post("/api/stores", json={"name": "ร้านB"})
        resp = client.get("/api/stores?q=B").json()
        assert len(resp) == 1
        assert resp[0]["name"] == "ร้านB"

    def test_duplicate_code_409(self, client):
        client.post("/api/stores", json={"name": "X", "code": "DUP"})
        r = client.post("/api/stores", json={"name": "Y", "code": "DUP"})
        assert r.status_code == 409

    def test_patch_store(self, client):
        s = client.post("/api/stores", json={"name": "X"}).json()
        r = client.patch(f"/api/stores/{s['id']}", json={"address": "ถ.สุขุมวิท"})
        assert r.status_code == 200
        assert r.json()["address"] == "ถ.สุขุมวิท"

    def test_delete_unlinked_store_is_hard_delete(self, client):
        s = client.post("/api/stores", json={"name": "Y"}).json()
        r = client.delete(f"/api/stores/{s['id']}")
        assert r.json()["status"] == "deleted"
        assert client.get("/api/stores").json() == []

    def test_delete_linked_store_deactivates(self, client, db_session):
        s = client.post("/api/stores", json={"name": "Z"}).json()
        v = client.post(
            "/api/visits", json={"store_id": s["id"], "rep_name": "R"}
        ).json()
        assert v["store_id"] == s["id"]
        r = client.delete(f"/api/stores/{s['id']}")
        assert r.json()["status"] == "deactivated"
        # Still in the DB but inactive.
        store = db_session.query(Store).filter(Store.id == s["id"]).first()
        assert store.active is False


class TestVisitStoreBinding:
    def test_create_visit_with_store_copies_key_and_label(self, client, db_session):
        s = client.post(
            "/api/stores",
            json={"name": "ร้านมิตรราชบุรี", "normalized_name": "มิตรราชบุรี"},
        ).json()
        v = client.post("/api/visits", json={"store_id": s["id"]}).json()
        assert v["store_id"] == s["id"]
        assert v["store_label"] == "ร้านมิตรราชบุรี"
        assert v["store_key"] == "มิตรราชบุรี"

    def test_create_visit_with_unknown_store_404(self, client):
        r = client.post("/api/visits", json={"store_id": "nope"})
        assert r.status_code == 404

    def test_auto_attach_links_to_matching_store(self, db_session):
        """When a legacy upload extracts a merchant_normalized that matches an
        existing Store, ``ensure_visit_for_doc`` should attach the doc's new
        Visit to that Store automatically."""
        db_session.add(
            Store(
                id="store-1",
                name="ร้าน A",
                normalized_name="ร้านA",
                active=True,
            )
        )
        doc = Document(
            id="doc-1",
            filename="r.png",
            file_path="/tmp/r.png",
            file_type="image",
            status="extracted",
            merchant_name="ร้าน A",
            merchant_normalized="ร้านA",
        )
        db_session.add(doc)
        db_session.flush()
        visit = ensure_visit_for_doc(db_session, doc)
        assert visit is not None
        assert visit.store_id == "store-1"

    def test_visit_reports_reviewed_count(self, client, db_session):
        s = client.post("/api/stores", json={"name": "X"}).json()
        v = client.post("/api/visits", json={"store_id": s["id"]}).json()
        # Manually drop in two docs in this visit, one reviewed.
        for did, status in (("d1", "extracted"), ("d2", "reviewed")):
            db_session.add(
                Document(
                    id=did,
                    filename=f"{did}.png",
                    file_path=f"/tmp/{did}.png",
                    file_type="image",
                    status=status,
                    visit_id=v["id"],
                )
            )
        db_session.commit()
        detail = client.get(f"/api/visits/{v['id']}").json()
        assert detail["reviewed_count"] == 1
        assert len(detail["documents"]) == 2
