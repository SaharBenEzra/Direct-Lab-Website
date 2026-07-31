# Direct Lab — Startup Application Site

Landing page + application form for Direct Lab, the innovation hub of Zur Shamir Group (IDI Direct Insurance, Mimun Yashir, Adgar), founded with MSI.

This repo is meant to be handed to IT/engineering as-is: they take the files and wire them into the company's own servers. Everything needed to build, test, containerize and deploy it is in this repo.

## Architecture

- `index.html` — the entire site: hero, About us, application form. Self-contained (logos embedded as base64), no build step.
- `app.py` — the backend (Flask). Serves `index.html` and handles `POST /submit`.
- `requirements.txt` / `requirements-dev.txt` — runtime deps (Flask, gunicorn, pymongo) and dev deps (+ pytest).
- `tests/` — pytest suite covering `/healthz`, a successful submission, and the failure/fallback behavior described below.
- `Dockerfile` / `.dockerignore` — production container image (gunicorn, non-root user, healthcheck).
- `docker-compose.yml` — app + MongoDB for local development.
- `Start Direct Lab.command` — double-click launcher (macOS): runs `docker-compose up` and opens the site. Local dev convenience only, not used in production.
- `charts/direct-lab/` — Helm chart for Kubernetes (see below).
- `.github/workflows/` — CI (test + build/push image) and CD (deploy via Helm).
- `submissions/` — created at runtime only when local-disk saving is enabled (see below). **Never committed** — real applicant data.

On every submission, three things happen:

1. **MongoDB (required)** — the record is inserted, and every uploaded file goes into GridFS alongside it. This is the single source of truth. If this fails, the request fails (`502`) and the frontend falls back to the visitor's browser local storage, same as it already does for any backend failure.
2. **Email (best-effort)** — the same data is emailed to `NOTIFY_EMAIL` (a constant near the top of `app.py` — edit it, or override with the `NOTIFY_EMAIL` env var without touching code) via Gmail SMTP, in the same plain "Label: value" format as before, so a future inbox-reading bot can parse it. A failure here is logged but never fails the request.
3. **Local disk (best-effort, opt-in via `SAVE_TO_LOCAL_DISK=true`)** — dev convenience only. Kubernetes pods don't have durable local disk, so this is `false` by default in the Dockerfile and in the Helm chart; Mongo is what matters in production. It's `true` by default in `docker-compose.yml` for easy local inspection.

## Running locally

**Option A — Docker Compose (recommended, closest to production):**

```bash
docker-compose up --build
```

Then open `http://localhost:4174`. This starts MongoDB alongside the app; submissions land in Mongo, in `./submissions/` (bind-mounted), and — if you've filled in `.env` — by email.

**Option B — plain Python, against your own Mongo:**

```bash
pip install -r requirements.txt
python3 app.py
```

Needs a reachable MongoDB (`MONGO_URI`, default `mongodb://localhost:27017`).

Either way: email needs `SMTP_USER`/`SMTP_PASS` from a Gmail App Password (Google Account → Security → 2-Step Verification → App passwords). Copy `.env.example` to `.env` and fill them in — `.env` is gitignored and must never be committed. Set the real recipient in `NOTIFY_EMAIL` in `app.py` (or via env var).

Opening `index.html` directly (double-click / `file://`) skips the backend entirely — the form still "works" but only saves to the browser's local storage.

## Tests

```bash
pip install -r requirements-dev.txt
MONGO_URI=mongodb://localhost:27017 python -m pytest tests/ -v
```

Needs a reachable, disposable MongoDB (tests use a `directlab_test` database and clean up after themselves) — e.g. `docker run --rm -p 27017:27017 mongo:7`.

## The `/submit` contract

Unchanged from before, so `index.html` needed no changes for any of this:

- `POST /submit` with `{ "record": { ...form fields... }, "files": [ { "name", "field", "dataB64" }, ... ] }`.
- `200 {"ok": true}` on success. Non-2xx on failure (the frontend already falls back to local storage on any backend failure, so a slow/broken backend degrades gracefully).
- Form field keys/labels are in `FIELDS` at the top of `app.py` — the single source of truth for what the frontend sends.

## Docker

```bash
docker build -t direct-lab-website .
docker run -p 4174:4174 -e MONGO_URI=... direct-lab-website
```

Runs `gunicorn` (2 workers, 4 threads), non-root, with a container `HEALTHCHECK` hitting `/healthz`.

## Kubernetes (Helm)

`charts/direct-lab/` deploys the app plus a self-hosted MongoDB (via the [Bitnami mongodb chart](https://github.com/bitnami/charts/tree/main/bitnami/mongodb) as a dependency — its own `PersistentVolumeClaim`, independent of `SAVE_TO_LOCAL_DISK`).

```bash
helm dependency build charts/direct-lab

cp charts/direct-lab/values.secrets.yaml.example charts/direct-lab/values.secrets.yaml
# fill in real passwords/credentials in that file — it's gitignored

helm upgrade --install direct-lab charts/direct-lab \
  -f charts/direct-lab/values.yaml \
  -f charts/direct-lab/values.secrets.yaml
```

Key values (`charts/direct-lab/values.yaml`):

- `image.repository` / `image.tag` — where the built image lives (CI pushes to `ghcr.io/saharbenezra/direct-lab-website`).
- `app.notifyEmail`, `app.saveToLocalDisk` (`false` by default — correct for a cluster), `app.smtp.*`.
- `ingress.enabled` / `ingress.host` — off by default; turn on and set a real hostname when there's a domain + ingress controller to point at.
- `autoscaling.enabled` — off by default; a basic CPU-based HPA is there if needed.
- `mongodb.*` — passed straight to the Bitnami subchart (persistence size, auth, etc).

This was validated end-to-end on a real local cluster (colima + k3s) during development: `helm lint`, `helm template` + `kubeconform` schema validation, then an actual install with both pods reaching `Ready`, a real submission through the cluster's Service, and confirming the record + GridFS attachment landed in the in-cluster MongoDB.

## CI/CD (GitHub Actions)

- **`.github/workflows/ci.yml`** — on every push/PR: installs deps, runs the pytest suite against a real `mongo:7` service container. On push to `main` only, also builds the Docker image and pushes it to `ghcr.io/saharbenezra/direct-lab-website` (tagged by commit SHA and `latest`).
- **`.github/workflows/cd.yml`** — deploys via `helm upgrade --install`, using the same chart described above. **Inert by default** — it checks for a `KUBE_CONFIG_DATA` secret and cleanly skips the deploy steps if it's not set, so this workflow needs no code changes once a real cluster is ready; it just needs these repo secrets added (Settings → Secrets and variables → Actions):

  | Secret | What it is |
  |---|---|
  | `KUBE_CONFIG_DATA` | base64-encoded kubeconfig for the target cluster |
  | `MONGO_ROOT_PASSWORD` | MongoDB root password |
  | `MONGO_APP_PASSWORD` | MongoDB password for the app's `directlab` user |
  | `SMTP_USER` | Gmail address submissions are sent from |
  | `SMTP_PASS` | Gmail App Password for that account |

  Can also be run manually (Actions tab → CD → Run workflow) for a deliberate one-off deploy.

## Notes for whoever deploys this

- **Never commit real credentials.** `.env`, `charts/direct-lab/values.secrets.yaml`, and the CI/CD secrets above are all the only places real passwords/keys should exist — never in a values.yaml, app.py, or a workflow file.
- **`submissions/` (when enabled) contains personal data** (applicant names, emails, phone numbers, uploaded files) — same for the MongoDB data itself. Treat both with normal PII handling: no public exposure, proper backup/retention policy for the production Mongo instance.
- **Mongo is the source of truth.** If it's unreachable, submissions correctly fail loudly (`502`) rather than silently disappearing — the frontend's local-storage fallback exists for exactly this case, but it's a safety net, not a replacement for Mongo being up.
