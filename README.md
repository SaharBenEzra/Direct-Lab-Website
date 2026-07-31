# Direct Lab — Startup Application Site

Landing page + application form for Direct Lab, the innovation hub of Zur Shamir Group (IDI Direct Insurance, Mimun Yashir, Adgar), founded with MSI.

This repo is meant to be handed to IT/engineering as-is: they take the files and wire them into the company's own servers. There is no external hosting dependency (no GitHub Pages, no third-party service) — everything needed is in this repo.

## Repo contents

- `index.html` — the entire site: hero, About us, application form. Self-contained (logos embedded as base64), no build step, no dependencies.
- `server.py` — reference backend. Serves `index.html` and handles form submissions on `POST /submit`. Pure Python standard library, no third-party packages.
- `Start Direct Lab.command` — double-click launcher, for local testing on macOS only. Not relevant to the production server.
- `submissions/` — created at runtime, one folder per applicant. **Never committed to git** (see `.gitignore`) — it holds real applicant data (names, emails, phone numbers, uploaded decks).
- `.env.example` — template for the SMTP credentials used to email each submission. Copy to `.env` and fill in real values; `.env` itself is gitignored and must never be committed.

## Running locally (for review/testing only)

```bash
python3 server.py
```

Then open `http://localhost:4174`. Opening `index.html` directly (double-click / `file://`) skips the server entirely — the form still works but falls back to saving in the browser's local storage instead of a real submissions folder.

## The `/submit` contract

This is what a production backend needs to replicate, whether that's this same script or a reimplementation in the company's own stack:

- `POST /submit` with a JSON body: `{ "record": { ...form fields... }, "files": [ { "name", "field", "dataB64" }, ... ] }`.
- On success, respond `200` with `{ "ok": true }`. On failure, any non-2xx (the frontend already falls back to local storage if the request fails or times out, so a slow/broken backend degrades gracefully rather than losing the submission from the visitor's point of view).
- Expected form field keys are listed in `FIELDS` at the top of `server.py` — that list is the single source of truth for what the frontend sends and how each field is labeled.

For each submission, `server.py` currently writes to `submissions/<Company Name>/`:

- **`details.json`** — the full record, machine-readable.
- **`summary.txt`** — the same data as plain labeled text (`Label: value`, one per line, stable field order), meant to be easy to read at a glance and easy for a script/bot to parse later — this is the format to reuse if/when submissions get emailed instead of only saved to disk.
- Every attached file (deck, logo, etc.), saved under its original name.

Saving to disk always happens first and unconditionally. Emailing the same data (see below) is best-effort on top of that — if it fails or isn't configured, the submission is still safe on disk and the HTTP response to the visitor is still a success.

## Email on submit

Every submission is also emailed to `NOTIFY_EMAIL` (a constant near the top of `server.py` — edit it to the real recipient address). The email body is the same `summary.txt` plain-labeled text, and `details.json` plus every uploaded file are attached — this is meant to be exactly what a future inbox-reading bot will parse, so the same format is used on disk and in the email.

Sending uses Gmail SMTP. Setup:

1. On the sending Gmail account: Google Account → Security → 2-Step Verification → App passwords → generate one for "Mail".
2. `cp .env.example .env`, then fill in `SMTP_USER` (that Gmail address) and `SMTP_PASS` (the App password — not the regular account password).
3. Restart `server.py`. If `SMTP_USER`/`SMTP_PASS` are missing or `NOTIFY_EMAIL` is still the placeholder, sending is skipped with a log line — submissions keep saving to disk either way.

`.env` is gitignored; it must never be committed. If this moves to the company's own mail infrastructure instead of Gmail, only `SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASS` in `server.py`/`.env` need to change — the message format stays the same.

## Notes for whoever deploys this

- **`server.py` uses Python's built-in `http.server`.** That module is explicitly meant for local development and testing, not production — no concurrency hardening, no request limits beyond what's coded here, minimal HTTP compliance. Before this goes live on a real domain, put it behind a proper WSGI/ASGI server (gunicorn, uwsgi) and a reverse proxy (nginx), or reimplement the `/submit` handler in whatever stack the company already runs. The submission format and folder layout above is the part that should carry over as-is.
- **`submissions/` contains personal data** (applicant names, emails, phone numbers, uploaded files). Wherever this is deployed, that folder needs the same access restrictions as any other store of PII — it must not be publicly served, and should not be committed to a public repo.
- **Never commit real SMTP credentials.** They belong in `.env` (gitignored) or the deployment platform's own secrets manager, not in `server.py`.
