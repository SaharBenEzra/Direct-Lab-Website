#!/usr/bin/env python3
"""Direct Lab local intake server.

Serves the landing page and handles form submissions. Each submit:
  1. Always saves to submissions/<Company Name>/ — the durable record:
       - details.json   machine-readable record, for scripts/automation
       - summary.txt     plain, labeled text, meant to be pasted into (or
                          emailed as) a message a bot can parse reliably
       - every attached file, as uploaded
  2. Best-effort emails the same details.json + summary.txt + attachments to
     NOTIFY_EMAIL below, via Gmail SMTP. Saving to disk always happens first
     and never depends on the email succeeding — see send_submission_email().

Run: python3 server.py   (listens on http://localhost:4174)

Email setup: this reads SMTP_USER / SMTP_PASS from the environment (or a
local, gitignored .env file — see .env.example). Never hardcode credentials
here. NOTIFY_EMAIL below is not a secret, just the recipient address.
"""
import base64
import json
import mimetypes
import os
import re
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SUBMISSIONS = ROOT / "submissions"
PORT = 4174
MAX_BODY = 200 * 1024 * 1024  # 200MB

# --- Where submissions get emailed. Edit this to the real address. ---------
NOTIFY_EMAIL = "REPLACE_ME@example.com"

# --- Sending account, read from the environment / .env, never hardcoded. ---
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


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
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")

# Field order + labels for the human/bot-readable summary. Keeping this list
# as the single source of truth means summary.txt always has the same shape,
# which is what makes it easy to parse later (e.g. "Company Name: <value>").
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


def build_summary(record: dict, saved_files: list) -> str:
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
    if saved_files:
        lines.append(f"Attachments ({len(saved_files)}):")
        for f in saved_files:
            lines.append(f"  - [{f['field']}] {f['file']}")
    else:
        lines.append("Attachments: none")
    lines.append("")
    return "\n".join(lines)


def send_submission_email(record: dict, saved_files: list, folder: Path, summary_text: str) -> None:
    """Best-effort email of the submission. Never raises past this function —
    the caller treats a failure here as a warning, not a request failure,
    since the submission is already safely on disk by the time this runs.
    """
    if not SMTP_USER or not SMTP_PASS:
        print("[directlab] SMTP_USER/SMTP_PASS not set — skipping email (submission still saved to disk)")
        return
    if not NOTIFY_EMAIL or NOTIFY_EMAIL.startswith("REPLACE_ME"):
        print("[directlab] NOTIFY_EMAIL not set — skipping email (submission still saved to disk)")
        return

    company = record.get("companyName") or "Unnamed startup"
    msg = EmailMessage()
    msg["Subject"] = f"Direct Lab application — {company}"
    msg["From"] = SMTP_USER
    msg["To"] = NOTIFY_EMAIL
    msg.set_content(summary_text)

    details_bytes = json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8")
    msg.add_attachment(details_bytes, maintype="application", subtype="json", filename="details.json")

    for f in saved_files:
        fpath = folder / f["file"]
        data = fpath.read_bytes()
        ctype, _ = mimetypes.guess_type(fpath.name)
        maintype, _, subtype = (ctype or "application/octet-stream").partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream", filename=fpath.name)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
    print(f"[directlab] emailed submission for '{company}' to {NOTIFY_EMAIL}")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_POST(self):
        if self.path != "/submit":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > MAX_BODY:
            self.send_error(413, "Payload too large or empty")
            return
        try:
            payload = json.loads(self.rfile.read(length))
            record = payload.get("record", {})
            files = payload.get("files", [])

            company = safe_name(str(record.get("companyName", "")).strip(),
                                "unnamed-startup")
            folder = unique_dir(SUBMISSIONS / company)
            folder.mkdir(parents=True)

            saved = []
            for f in files:
                fname = safe_name(str(f.get("name", "file")), "file")
                target = unique_dir(folder / fname) if (folder / fname).exists() else folder / fname
                target.write_bytes(base64.b64decode(f.get("dataB64", "")))
                saved.append({"file": target.name, "field": f.get("field", "")})

            record["submittedAt"] = datetime.now().isoformat(timespec="seconds")
            record["attachments"] = saved
            (folder / "details.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            summary_text = build_summary(record, saved)
            (folder / "summary.txt").write_text(summary_text, encoding="utf-8")

            try:
                send_submission_email(record, saved, folder, summary_text)
            except Exception as exc:  # noqa: BLE001 - email is best-effort, never blocks the save
                print(f"[directlab] email send failed: {exc}")

            body = json.dumps({"ok": True, "folder": folder.name}).encode()
            self.send_response(200)
        except Exception as exc:  # noqa: BLE001 - report any failure to the client
            body = json.dumps({"ok": False, "error": str(exc)}).encode()
            self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[directlab] {fmt % args}")


if __name__ == "__main__":
    SUBMISSIONS.mkdir(exist_ok=True)
    print(f"Direct Lab intake server on http://localhost:{PORT}")
    print(f"Submissions folder: {SUBMISSIONS}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
