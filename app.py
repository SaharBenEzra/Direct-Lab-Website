#!/usr/bin/env python3
"""Direct Lab backend.

Serves index.html and handles POST /submit. On every submission:

  1. MongoDB (required) — the record + attachment metadata are saved. This
     is the single source of truth. If this fails, the request fails and
     the frontend falls back to the visitor's browser local storage,
     exactly as it already does for any backend failure.

     Uploaded files arrive in one of two shapes, and both are handled:
       - inline base64 ("dataB64") — the original contract, used when the
         frontend can't reach Vercel Blob (e.g. this app self-hosted on
         Docker/Kubernetes). Bytes go into GridFS alongside the record.
       - a Vercel Blob URL ("url") — used when the frontend successfully
         uploaded the file straight to Blob storage first (see
         api/blob-upload.js). Only the URL + metadata is stored; the bytes
         already live durably in Blob, so they aren't duplicated into
         Mongo/GridFS (this also matters for Atlas's free-tier storage cap).

  2. Email (best-effort) — the same data is emailed to NOTIFY_EMAIL so a
     future inbox-reading bot can pick it up. A failure here is logged but
     never fails the request — the submission is already safe in Mongo.
  3. Local disk (best-effort, opt-in via SAVE_TO_LOCAL_DISK) — convenience
     for local development only. Neither Kubernetes pods nor Vercel
     functions have durable local disk, so this is off by default in both;
     Mongo is what matters in production.

Run for local dev:  python3 app.py            (http://localhost:4174)
Run in production:  gunicorn -b 0.0.0.0:4174 app:app   (see Dockerfile)
Run on Vercel:       this file is a supported entrypoint (app.py) —
                     Vercel detects the Flask `app` instance automatically.
"""
import base64
import json
import mimetypes
import os
import re
import smtplib
import ssl
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from io import BytesIO
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from gridfs import GridFSBucket
from pymongo import MongoClient

ROOT = Path(__file__).resolve().parent
SUBMISSIONS = ROOT / "submissions"


def load_dotenv() -> None:
    """Tiny .env loader so local dev doesn't need a third-party package.

    Real environment variables always win; .env only fills in what's missing.
    """
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()

# --- Config -----------------------------------------------------------
# MONGO_URI is our own name; MONGODB_URI is what Vercel's MongoDB Atlas
# Marketplace integration injects — accept either so connecting Atlas on
# Vercel needs no renaming.
MONGO_URI = os.environ.get("MONGO_URI") or os.environ.get("MONGODB_URI") or "mongodb://localhost:27017"
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "directlab")
SAVE_TO_LOCAL_DISK = os.environ.get("SAVE_TO_LOCAL_DISK", "true").lower() == "true"

# Where submissions get emailed. Not a secret — edit this default directly,
# or override per-environment with the NOTIFY_EMAIL env var (e.g. from Helm
# values) without touching code.
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL") or "REPLACE_ME@example.com"

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")

MAX_BODY = 200 * 1024 * 1024  # 200MB

# Field order + labels for the human/bot-readable summary. Keeping this list
# as the single source of truth means summary.txt/email body always has the
# same shape, which is what makes it easy to parse later.
FIELDS = [
    ("companyName", "Company Name"),
    ("companyWebsite", "Company Website"),
    ("stage", "Stage"),
    ("oneLiner", "One-Liner"),
    ("problem", "The Problem"),
    ("solution", "The Solution"),
    ("businessModel", "Business Model"),
    ("otherModel", "Other Business Model"),
    ("differentiation", "Differentiation"),
    ("milestones", "Milestones"),
    ("fullName", "Full Name"),
    ("title", "Title"),
    ("email", "Email"),
    ("phone", "Phone"),
    ("linkedin", "LinkedIn"),
    ("article", "Optional Article"),
]

mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000, socketTimeoutMS=8000, connectTimeoutMS=5000)
mongo_db = mongo_client[MONGO_DB_NAME]
fs_bucket = GridFSBucket(mongo_db, bucket_name="attachments")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_BODY


def safe_name(name: str, fallback: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .")
    return name[:80] or fallback


def unique_dir(base: Path) -> Path:
    if not base.exists():
        return base
    i = 2
    while True:
        candidate = base.with_name(f"{base.name}-{i}")
        if not candidate.exists():
            return candidate
        i += 1


def build_summary(record: dict, attachments: list) -> str:
    """Plain-text, labeled version of the submission.

    Format is deliberately simple and stable ("Label: value", one per line,
    blank line between sections) so a future email-parsing bot can rely on
    line-by-line "Label:" matching instead of anything fragile.
    """
    lines = [
        "DIRECT LAB — NEW STARTUP APPLICATION",
        f"Submitted: {record.get('submittedAt', '')}",
        "=" * 40,
        "",
    ]
    for key, label in FIELDS:
        value = str(record.get(key, "") or "").strip()
        if not value:
            continue
        lines.append(f"{label}: {value}")
    lines.append("")
    lines.append("-" * 40)
    if attachments:
        lines.append(f"Attachments ({len(attachments)}):")
        for a in attachments:
            lines.append(f"  - [{a['field']}] {a['filename']}")
    else:
        lines.append("Attachments: none")
    lines.append("")
    return "\n".join(lines)


def fetch_url_bytes(url: str, max_bytes: int = 30 * 1024 * 1024) -> bytes:
    """Fetch a Blob-hosted file's bytes (for emailing it as an attachment).
    Capped so one huge deck can't blow up function memory; callers treat a
    failure here as "skip this attachment", not a hard error.
    """
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.read(max_bytes + 1)[:max_bytes]


def save_to_mongo(record: dict, decoded_files: list, blob_files: list, submitted_at: datetime) -> list:
    """Insert the record with attachment metadata, return that metadata for
    reuse in the summary/email.

    decoded_files (raw bytes) go into GridFS. blob_files (already durably
    stored in Vercel Blob) are referenced by URL only — no bytes touch
    Mongo for those, by design.
    """
    attachments_meta = []
    for f in decoded_files:
        file_id = fs_bucket.upload_from_stream(
            f["filename"],
            BytesIO(f["data"]),
            metadata={"field": f["field"], "contentType": f["contentType"]},
        )
        attachments_meta.append({
            "field": f["field"],
            "filename": f["filename"],
            "contentType": f["contentType"],
            "size": len(f["data"]),
            "gridfsId": str(file_id),
        })
    for f in blob_files:
        attachments_meta.append({
            "field": f["field"],
            "filename": f["filename"],
            "contentType": f["contentType"],
            "size": f["size"],
            "blobUrl": f["url"],
        })

    doc = dict(record)
    doc["submittedAt"] = submitted_at
    doc["attachments"] = attachments_meta
    mongo_db["submissions"].insert_one(doc)
    return attachments_meta


def send_submission_email(record: dict, decoded_files: list, blob_files: list, summary_text: str) -> None:
    """Best-effort email of the submission. Raises on failure — the caller
    logs and swallows it, since Mongo already has the durable copy.
    """
    if not SMTP_USER or not SMTP_PASS:
        raise RuntimeError("SMTP_USER/SMTP_PASS not set")
    if not NOTIFY_EMAIL or NOTIFY_EMAIL.startswith("REPLACE_ME"):
        raise RuntimeError("NOTIFY_EMAIL not set")

    company = record.get("companyName") or "Unnamed startup"
    msg = EmailMessage()
    msg["Subject"] = f"Direct Lab application — {company}"
    msg["From"] = SMTP_USER
    msg["To"] = NOTIFY_EMAIL
    msg.set_content(summary_text)

    details_bytes = json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8")
    msg.add_attachment(details_bytes, maintype="application", subtype="json", filename="details.json")

    for f in decoded_files:
        maintype, _, subtype = f["contentType"].partition("/")
        msg.add_attachment(f["data"], maintype=maintype, subtype=subtype or "octet-stream", filename=f["filename"])

    for f in blob_files:
        try:
            data = fetch_url_bytes(f["url"])
        except Exception as exc:  # noqa: BLE001 — one bad attachment shouldn't lose the email
            app.logger.warning("could not fetch blob attachment '%s' for email: %s", f["filename"], exc)
            continue
        maintype, _, subtype = f["contentType"].partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream", filename=f["filename"])

    # timeout is essential here: some serverless platforms (Vercel included)
    # throttle or silently drop outbound SMTP traffic, and without a bound
    # this call can hang far past any reasonable request latency — email is
    # meant to be best-effort, but a hang here still blocks the whole
    # /submit response since it runs before the client gets an answer.
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=8) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
    app.logger.info("emailed submission for '%s' to %s", company, NOTIFY_EMAIL)


def save_to_local_disk(company: str, record: dict, decoded_files: list, summary_text: str) -> None:
    """Dev-only convenience copy. Never used as the source of truth."""
    folder = unique_dir(SUBMISSIONS / safe_name(company, "unnamed-startup"))
    folder.mkdir(parents=True)
    for f in decoded_files:
        target = folder / f["filename"]
        target = unique_dir(target) if target.exists() else target
        target.write_bytes(f["data"])
    (folder / "details.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / "summary.txt").write_text(summary_text, encoding="utf-8")


@app.get("/")
@app.get("/index.html")
def index():
    return send_from_directory(ROOT, "index.html")


@app.get("/healthz")
def healthz():
    try:
        mongo_client.admin.command("ping")
        return jsonify(ok=True, mongo="up")
    except Exception as exc:  # noqa: BLE001
        return jsonify(ok=False, mongo="down", error=str(exc)), 503


@app.post("/submit")
def submit():
    payload = request.get_json(silent=True) or {}
    record = payload.get("record") or {}
    incoming_files = payload.get("files") or []

    decoded_files = []  # inline base64 — bytes travel in this request
    blob_files = []     # already uploaded to Vercel Blob — URL reference only
    for f in incoming_files:
        filename = safe_name(str(f.get("name", "file")), "file")
        field = f.get("field", "")
        if f.get("url"):
            content_type = f.get("contentType") or mimetypes.guess_type(filename)[0] or "application/octet-stream"
            blob_files.append({
                "field": field,
                "filename": filename,
                "contentType": content_type,
                "size": int(f.get("size") or 0),
                "url": f["url"],
            })
        else:
            data = base64.b64decode(f.get("dataB64", "") or "")
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            decoded_files.append({
                "field": field,
                "filename": filename,
                "contentType": content_type,
                "data": data,
            })

    submitted_at = datetime.utcnow()
    submitted_at_iso = submitted_at.isoformat(timespec="seconds") + "Z"

    try:
        attachments_meta = save_to_mongo(record, decoded_files, blob_files, submitted_at)
    except Exception as exc:  # noqa: BLE001 — Mongo is required; surface the failure
        app.logger.exception("Mongo save failed")
        return jsonify(ok=False, error=f"database error: {exc}"), 502

    display_record = {**record, "submittedAt": submitted_at_iso}
    summary_text = build_summary(display_record, attachments_meta)

    try:
        send_submission_email(display_record, decoded_files, blob_files, summary_text)
    except Exception as exc:  # noqa: BLE001 — email is best-effort
        app.logger.warning("email send failed: %s", exc)

    if SAVE_TO_LOCAL_DISK:
        try:
            save_to_local_disk(str(record.get("companyName", "")), display_record, decoded_files, summary_text)
        except Exception as exc:  # noqa: BLE001 — local disk is best-effort
            app.logger.warning("local disk save failed: %s", exc)

    return jsonify(ok=True)


if __name__ == "__main__":
    if SAVE_TO_LOCAL_DISK:
        SUBMISSIONS.mkdir(exist_ok=True)
    port = int(os.environ.get("PORT", "4174"))
    print(f"Direct Lab intake server on http://localhost:{port}")
    print(f"Mongo: {MONGO_URI} / db={MONGO_DB_NAME}")
    print(f"Local disk save: {SAVE_TO_LOCAL_DISK}")
    app.run(host="0.0.0.0", port=port, debug=False)
