#!/usr/bin/env python3
"""Direct Lab local intake server.

Serves the landing page and handles form submissions. Each submit creates
submissions/<Company Name>/ containing:
  - details.json   machine-readable record, for scripts/automation
  - summary.txt     plain, labeled text, meant to be pasted into (or later
                     emailed as) a message a bot can parse reliably
  - every attached file, as uploaded

Run: python3 server.py   (listens on http://localhost:4174)
"""
import base64
import json
import re
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SUBMISSIONS = ROOT / "submissions"
PORT = 4174
MAX_BODY = 200 * 1024 * 1024  # 200MB

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
            (folder / "summary.txt").write_text(
                build_summary(record, saved), encoding="utf-8")

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
