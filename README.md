# Direct Lab — Startup Application Site

Landing page + application form for Direct Lab, the innovation hub of Zur Shamir Group (IDI Direct Insurance, Mimun Yashir, Adgar), founded with MSI.

## Structure

- `index.html` — the full site: hero, About us, form. Self-contained (logos embedded as base64), no build step.
- `server.py` — local intake server. Serves `index.html` and handles form submissions on `POST /submit`.
- `Start Direct Lab.command` — double-click launcher (macOS): starts the server and opens the site in the browser.
- `submissions/` — created at runtime, one folder per applicant. **Not committed to git** (see `.gitignore`) — it contains real applicant data.

## Running locally

```bash
python3 server.py
```

Then open `http://localhost:4174`. Do **not** open `index.html` directly by double-clicking it — as a `file://` page the form has no server to submit to, and falls back to saving in the browser's local storage instead of a real submissions folder.

## What happens on submit

Each submission creates `submissions/<Company Name>/` containing:

- **`details.json`** — the full record, machine-readable.
- **`summary.txt`** — the same data as plain labeled text (`Label: value`, one per line), meant to be easy to read at a glance and easy for a script/bot to parse later (e.g. once submissions are emailed instead of just saved locally).
- Every attached file (deck, logo, etc.), saved as uploaded.

## Current status / next steps

- The form currently only saves locally. Sending the submission by email (so a bot can later read it from an inbox) is a planned next step — not wired up yet, by design, since it needs an email account or transactional-email API key that should be created and held by the site owner, not embedded in code.
- The live site (once hosted, e.g. via GitHub Pages) currently serves the frontend only. Without a live backend behind it, submissions on the hosted site fall back to the visitor's browser local storage (the same graceful fallback used if the local server is ever unreachable). Hosting the backend live is a deferred decision.
