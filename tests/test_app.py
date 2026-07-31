import base64
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app as app_module  # noqa: E402  (path insert must happen first)


@pytest.fixture
def client():
    return app_module.app.test_client()


@pytest.fixture(autouse=True)
def clean_test_db():
    yield
    app_module.mongo_db["submissions"].delete_many({})
    app_module.mongo_db["attachments.files"].delete_many({})
    app_module.mongo_db["attachments.chunks"].delete_many({})


def test_index_serves_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"<!doctype html" in resp.data.lower() or b"<html" in resp.data.lower()


def test_healthz_reports_mongo_up(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["mongo"] == "up"


def test_submit_saves_record_and_attachment_to_mongo(client):
    payload = {
        "record": {
            "companyName": "Test Startup",
            "oneLiner": "does testing",
            "fullName": "A Tester",
            "email": "tester@example.com",
            "stage": "Seed",
        },
        "files": [
            {"name": "deck.pdf", "field": "deck", "dataB64": base64.b64encode(b"%PDF-fake").decode()},
        ],
    }
    resp = client.post("/submit", json=payload)
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}

    doc = app_module.mongo_db["submissions"].find_one({"companyName": "Test Startup"})
    assert doc is not None
    assert doc["email"] == "tester@example.com"
    assert len(doc["attachments"]) == 1
    assert doc["attachments"][0]["filename"] == "deck.pdf"

    files_count = app_module.mongo_db["attachments.files"].count_documents({"filename": "deck.pdf"})
    assert files_count == 1


def test_submit_without_files_still_succeeds(client):
    payload = {"record": {"companyName": "No Files Co", "email": "x@example.com"}, "files": []}
    resp = client.post("/submit", json=payload)
    assert resp.status_code == 200

    doc = app_module.mongo_db["submissions"].find_one({"companyName": "No Files Co"})
    assert doc is not None
    assert doc["attachments"] == []


def test_submit_returns_502_when_mongo_save_fails(client):
    with patch.object(app_module, "save_to_mongo", side_effect=RuntimeError("boom")):
        with patch.object(app_module, "send_submission_email") as mock_email:
            resp = client.post("/submit", json={"record": {"companyName": "Should Not Save"}, "files": []})
            assert resp.status_code == 502
            body = resp.get_json()
            assert body["ok"] is False
            # Mongo is the required sink — if it fails, we must not even try
            # the best-effort ones, and nothing should exist in the DB.
            mock_email.assert_not_called()

    assert app_module.mongo_db["submissions"].find_one({"companyName": "Should Not Save"}) is None


def test_email_failure_does_not_fail_the_request(client):
    with patch.object(app_module, "send_submission_email", side_effect=RuntimeError("smtp down")):
        resp = client.post("/submit", json={"record": {"companyName": "Email Down Co"}, "files": []})
        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True}

    # The submission itself must still be safely in Mongo despite the email failure.
    assert app_module.mongo_db["submissions"].find_one({"companyName": "Email Down Co"}) is not None
