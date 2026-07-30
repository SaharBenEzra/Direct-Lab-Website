# Direct Lab — Startup Application Site

Landing page + application form for Direct Lab, the innovation hub of Zur Shamir Group (IDI Direct Insurance, Mimun Yashir, Adgar), founded with MSI.

This repo is meant to be handed to IT/engineering as-is: they take the files and wire them into the company's own servers. There is no external hosting dependency (no GitHub Pages, no third-party service) — everything needed is in this repo.

## Repo contents

- `index.html` — the entire site: hero, About us, application form. Self-contained (logos embedded as base64), no build step, no dependencies.
- `server.py` — reference backend. Serves `index.html` and handles form submissions on `POST /submit`. Pure Python standard library, no third-party packages.
- `Start Direct Lab.command` — double-click launcher, for local testing on macOS only. Not relevant to the production server.
- `submissions/` — created at runtime, one folder per applicant. **Never committed to git** (see `.gitignore`) — it holds real applicant data (names, emails, phone numbers, uploaded decks).

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

## Notes for whoever deploys this

- **`server.py` uses Python's built-in `http.server`.** That module is explicitly meant for local development and testing, not production — no concurrency hardening, no request limits beyond what's coded here, minimal HTTP compliance. Before this goes live on a real domain, put it behind a proper WSGI/ASGI server (gunicorn, uwsgi) and a reverse proxy (nginx), or reimplement the `/submit` handler in whatever stack the company already runs. The submission format and folder layout above is the part that should carry over as-is.
- **`submissions/` contains personal data** (applicant names, emails, phone numbers, uploaded files). Wherever this is deployed, that folder needs the same access restrictions as any other store of PII — it must not be publicly served, and should not be committed to a public repo.
- **Email delivery is intentionally not implemented yet.** The plan is for each submission to eventually be emailed (or otherwise forwarded) so a separate bot can parse it — `summary.txt`'s plain, stable "Label: value" format was designed with that in mind. Wiring up actual sending needs an email account or a transactional-email API key, which should be created and held by whoever owns that infrastructure, not embedded in this code.
