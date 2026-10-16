from tests.conftest import BILL, photo_jpeg, scanned_pdf, text_pdf


def upload(client, data, name="document.pdf", mime="application/pdf"):
    return client.post("/documents", files={"file": (name, data, mime)})


def cats(client):
    return {c["name"]: c for c in client.get("/categories").json()}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_upload_reads_and_files_a_bill(client):
    r = upload(client, text_pdf(BILL), "scan_0042.pdf")
    assert r.status_code == 201 and r.json()["status"] == "processing"
    d = client.get(f"/documents/{r.json()['id']}").json()
    assert d["status"] == "ready" and d["category_name"] == "Bills & Utilities"
    assert (d["issuer"], d["doc_date"], d["amount"]) == ("British Gas", "2026-10-03", "£84.20")
    assert d["suggested_name"] == "2026-10-03 British Gas Bill.pdf"
    assert "Amount due" in d["text"] and d["text_source"] == "pdf" and d["pages"] == 1
    assert d["summary_source"] == "quick" and "£84.20" in d["summary"]
    assert cats(client)["Bills & Utilities"]["count"] == 1


def test_files_and_previews_are_served_with_signed_links(client):
    d = upload(client, text_pdf(BILL)).json()
    d = client.get(f"/documents/{d['id']}").json()
    no_auth = {"Authorization": ""}
    f = client.get(d["file_url"], headers=no_auth)
    assert f.status_code == 200 and f.content.startswith(b"%PDF") and "inline" in f.headers["content-disposition"]
    dl = client.get(d["download_url"], headers=no_auth)
    from urllib.parse import unquote
    assert "attachment" in dl.headers["content-disposition"]
    assert "2026-10-03 British Gas Bill.pdf" in unquote(dl.headers["content-disposition"])
    assert client.get(d["thumb_url"], headers=no_auth).content[:2] == b"\xff\xd8"
    assert client.get(d["file_url"].split("?")[0] + "?sig=wrong", headers=no_auth).status_code == 404


def test_same_file_twice_is_one_document(client):
    data = text_pdf(BILL)
    a, b = upload(client, data).json(), upload(client, data).json()
    assert a["id"] == b["id"] and b["already_saved"]
    assert client.get("/documents").json()["total"] == 1


def test_same_content_different_file_is_flagged_as_duplicate(client):
    long = BILL + [f"Line {i} of the terms and conditions for this account" for i in range(10)]
    first = upload(client, text_pdf(long)).json()
    second = upload(client, text_pdf(long + [""])).json()  # different bytes, same words
    assert client.get(f"/documents/{second['id']}").json()["duplicate_of"] == first["id"]
    assert [d["id"] for d in client.get("/documents?duplicates=true").json()["items"]] == [second["id"]]


def test_scans_and_photos_are_searchable(client):
    upload(client, scanned_pdf(["Aviva", "Certificate of insurance", "Policy number ZX9981"]), "scan.pdf")
    upload(client, photo_jpeg(["TESCO", "Receipt", "Total 12.50"]), "IMG_2231.jpg", "image/jpeg")
    found = client.get("/documents", params={"q": "ZX9981"}).json()["items"]
    assert len(found) == 1 and found[0]["category_name"] == "Insurance"
    photo = client.get("/documents", params={"q": "TESCO"}).json()["items"][0]
    assert photo["kind"] == "image" and photo["category_name"] == "Receipts & Purchases"


def test_phone_upload_with_api_key(client):
    no_auth = {"Authorization": ""}
    r = client.post(f"/u/{client.api_key}?name=bill.pdf", content=text_pdf(BILL), headers=no_auth)
    assert r.status_code == 200 and r.text.startswith("Saved ✓")
    r = client.post(f"/u/{client.api_key}", content=text_pdf(BILL), headers=no_auth)
    assert r.text.startswith("Already saved ✓")
    r = client.post(f"/u/{client.api_key}", files={"file": ("p.jpg", photo_jpeg(["Receipt"]), "image/jpeg")},
                    headers=no_auth)
    assert r.status_code == 200
    assert client.post("/u/dv_wrong", content=text_pdf(BILL), headers=no_auth).status_code == 401
    assert client.post(f"/u/{client.api_key}", content=b"not a document", headers=no_auth).status_code == 422


def test_moving_records_a_correction_and_new_categories(client):
    d = upload(client, text_pdf(["Hello", "see you soon"])).json()
    assert client.get(f"/documents/{d['id']}").json()["needs_review"]
    r = client.patch(f"/documents/{d['id']}", json={"category_id": cats(client)["Home & Property"]["id"]})
    assert r.json()["category_name"] == "Home & Property" and not r.json()["needs_review"]
    r = client.patch(f"/documents/{d['id']}", json={"category": "Pets"})
    assert r.json()["category_name"] == "Pets" and "Pets" in cats(client)
    from app.db import SessionLocal
    from app.models import Correction
    with SessionLocal() as db:
        assert db.query(Correction).count() == 2


def test_edit_favorite_delete(client):
    d = upload(client, text_pdf(BILL)).json()
    r = client.patch(f"/documents/{d['id']}", json={"title": "My bill", "is_favorite": True, "note": "paid"})
    assert (r.json()["title"], r.json()["is_favorite"], r.json()["note"]) == ("My bill", True, "paid")
    assert client.get("/documents?favorite=true").json()["total"] == 1
    assert client.delete(f"/documents/{d['id']}").status_code == 204
    assert client.get("/documents").json()["total"] == 0


def test_categories_crud_and_reorder(client):
    r = client.post("/categories", json={"name": "Pets", "icon": "pets"})
    assert r.status_code == 201
    pets = r.json()["id"]
    ids = [c["id"] for c in client.get("/categories").json()]
    out = client.post("/categories/reorder", json={"ids": [pets]}).json()
    assert out[0]["id"] == pets and len(out) == len(ids)
    other = cats(client)["Other"]["id"]
    assert client.delete(f"/categories/{other}").status_code == 400
    assert client.delete(f"/categories/{pets}").status_code == 204


def test_login_and_closed_registration(client, monkeypatch):
    r = client.post("/auth/login", json={"email": "ME@example.com", "password": "correct-horse"})
    assert r.status_code == 200 and r.json()["api_key"].startswith("dv_")
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "allow_registration", False)
    assert client.post("/auth/register", json={"email": "x@example.com", "password": "password123"}).status_code == 403


def test_add_page_is_served(client):
    r = client.get("/add", headers={"Authorization": ""})
    assert r.status_code == 200 and 'type="file"' in r.text and "flutter.dv_token" in r.text


def test_rename_title_and_file_name(client):
    d = upload(client, text_pdf(BILL)).json()
    r = client.patch(f"/documents/{d['id']}", json={"title": "  Gas bill October  ", "file_name": 'Gas: bill/Oct?.PDF'})
    assert r.status_code == 200
    assert r.json()["title"] == "Gas bill October" and r.json()["suggested_name"] == "Gas bill Oct.pdf"
    from urllib.parse import unquote
    dl = client.get(r.json()["download_url"], headers={"Authorization": ""})
    assert "Gas bill Oct.pdf" in unquote(dl.headers["content-disposition"])
    photo = upload(client, photo_jpeg(["Receipt"]), "p.jpg", "image/jpeg").json()
    assert client.patch(f"/documents/{photo['id']}", json={"file_name": "Tesco receipt"}).json()["suggested_name"] == "Tesco receipt.jpg"
    assert client.patch(f"/documents/{d['id']}", json={"file_name": "  ///  "}).status_code == 422
    assert client.patch(f"/documents/{d['id']}", json={"title": "   "}).status_code == 422
