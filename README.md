# Direct Lab — Startup Application Site

Landing page + application form for Direct Lab, the innovation hub of Zur Shamir Group (IDI Direct Insurance, Mimun Yashir, Adgar), founded with MSI.

**Two ways to run this in production, both fully built out in this repo:**

- **Vercel + MongoDB Atlas** (recommended — see [Deploy to Vercel](#deploy-to-vercel-recommended)) — the fastest path to a live URL, no servers to manage.
- **Self-hosted (Docker / Kubernetes)** — for when IT wants it on the company's own infrastructure (see [Kubernetes (Helm)](#kubernetes-helm)).

Both share the same `app.py` and `index.html` — the frontend detects which backend it's talking to at runtime and adjusts (see "Two upload paths" below), so there's exactly one codebase to maintain either way.

## Architecture

- `index.html` — the entire site: hero, About us, application form. Self-contained (logos embedded as base64), no build step.
- `app.py` — the backend (Flask). Serves `index.html` and handles `POST /submit`. This one file is also the entrypoint Vercel's Python runtime detects automatically.
- `requirements.txt` / `requirements-dev.txt` — runtime deps (Flask, gunicorn, pymongo) and dev deps (+ pytest).
- `tests/` — pytest suite covering `/healthz`, a successful submission, both upload paths, and the failure/fallback behavior described below.
- `api/blob-upload.js`, `package.json` — Vercel-only: the Node.js function that issues Vercel Blob upload tokens (see "Two upload paths"). Not used by the Docker/K8s path.
- `vercel.json`, `.vercelignore` — Vercel project config.
- `Dockerfile` / `.dockerignore` — production container image (gunicorn, non-root user, healthcheck). Docker/K8s path only.
- `docker-compose.yml` — app + MongoDB for local development.
- `Start Direct Lab.command` — double-click launcher (macOS): runs `docker-compose up` and opens the site. Local dev convenience only, not used in production.
- `charts/direct-lab/` — Helm chart for Kubernetes (see below). Docker/K8s path only.
- `.github/workflows/` — CI (test + build/push image) and CD (deploy via Helm) for the Docker/K8s path. Vercel deploys itself on every push once the GitHub repo is connected — no separate workflow needed.
- `submissions/` — created at runtime only when local-disk saving is enabled (see below). **Never committed** — real applicant data.

On every submission, three things happen:

1. **MongoDB (required)** — the record is inserted. This is the single source of truth. If this fails, the request fails (`502`) and the frontend falls back to the visitor's browser local storage, same as it already does for any backend failure.
2. **Email (best-effort)** — the same data is emailed to `NOTIFY_EMAIL` (a constant near the top of `app.py` — edit it, or override with the `NOTIFY_EMAIL` env var without touching code) via Gmail SMTP, in the same plain "Label: value" format as before, so a future inbox-reading bot can parse it. A failure here is logged but never fails the request.
3. **Local disk (best-effort, opt-in via `SAVE_TO_LOCAL_DISK=true`)** — dev convenience only. Neither Kubernetes pods nor Vercel functions have durable local disk, so this is `false` by default in the Dockerfile, the Helm chart, and on Vercel; Mongo is what matters in production. It's `true` by default in `docker-compose.yml` for easy local inspection.

### Two upload paths (why there's a Node.js file in a Python project)

Uploaded files reach the backend one of two ways, and `index.html` picks automatically:

- **Vercel Blob** (used when deployed on Vercel): the browser uploads the file straight to Blob storage via a token it gets from `api/blob-upload.js`, then sends `/submit` just a `{ url, ... }` reference. Bytes never pass through the Python function, so upload size isn't limited by a function's request-body cap, and files aren't duplicated into Mongo (relevant since Atlas's free tier has a small storage cap). Mongo stores `{ field, filename, contentType, size, blobUrl }` for these.
- **Inline base64** (the original design, used everywhere else — Docker, Kubernetes, or if Blob is simply unreachable): the file is embedded as base64 straight in the `/submit` JSON body, decoded server-side, and stored in **GridFS** alongside the record. Mongo stores `{ field, filename, contentType, size, gridfsId }` for these.

The frontend always tries Blob first and falls back to inline base64 within a bounded 25s (network error, 404 because `/api/blob-upload` doesn't exist on this host, or Blob itself failing) — so the exact same `index.html` works correctly against either backend without knowing which one it's talking to. The 25s bound matters, not just a `.catch()`: `@vercel/blob/client`'s `upload()` retries retryable errors (e.g. a transient 503 from Blob storage) internally before ever rejecting, so a plain `.catch()` can sit pending through several retries instead of falling back quickly — `uploadFile()` in `index.html` races the upload against a hard timeout so the fallback is guaranteed to fire on a predictable clock regardless of what's happening inside `upload()`.

## Deploy to Vercel (recommended)

This needs three things connected in the Vercel dashboard, then it deploys itself on every push.

**1. Import the repo.** [vercel.com/new](https://vercel.com/new) → Import Git Repository → pick `SaharBenEzra/Direct-Lab-Website`. Vercel auto-detects `app.py` as a Flask entrypoint and `api/blob-upload.js` as a Node function — no build configuration needed, `vercel.json` already covers it.

**2. Add MongoDB Atlas** (Project → Storage tab → Browse Marketplace → MongoDB Atlas, or `vercel integration add mongodb-atlas` from the CLI once the project is linked). This provisions a free-tier Atlas cluster and injects its connection string as an env var automatically — `app.py` reads either `MONGO_URI` or `MONGODB_URI`, so whichever name the integration uses works with no renaming.

**3. Add Vercel Blob** (Project → Storage tab → Create Database → Blob, or `vercel blob store add`). This injects `BLOB_READ_WRITE_TOKEN`, which `api/blob-upload.js` needs. Without it, uploads still work — they just silently fall back to the slower inline-base64 path (see "Two upload paths" above).

**4. Set the remaining environment variables** (Project → Settings → Environment Variables):

| Variable | Value |
|---|---|
| `SMTP_USER` | Gmail address to send submission emails from |
| `SMTP_PASS` | a Gmail **App Password** for that account (Google Account → Security → 2-Step Verification → App passwords) — not the regular password |
| `NOTIFY_EMAIL` | *(optional)* overrides the `NOTIFY_EMAIL` constant in `app.py` without a code change |

Redeploy after adding these (Vercel doesn't hot-reload env var changes into a running deployment).

**Local dev against the same Vercel project** (optional, needs `npm i -g vercel` and `vercel login` first):

```bash
vercel link
vercel env pull .env.local   # pulls the real MONGO_URI / BLOB_READ_WRITE_TOKEN etc.
vercel dev
```

**One thing worth a quick smoke test after the first deploy:** `api/blob-upload.js` (a Node function) and `app.py` (the Flask catch-all) are two different runtimes coexisting in one project — this is Vercel's documented, standard pattern, but confirm in practice that a real upload goes through Blob rather than silently falling back every time (Network tab → submit the form → look for a successful call to `/api/blob-upload` before `/submit`). If it's always falling back, check the Blob store is actually connected to the project (step 3).

## Running locally

**Option A — Docker Compose (recommended, closest to production):**

```bash
docker-compose up --build
```

Then open `http://localhost:4174`. This starts MongoDB alongside the app; submissions land in Mongo, in `./submissions/` (bind-mounted), and — if you've filled in `.env` — by email.

**Option B — plain Python, against your own Mongo:**

```bash
pip3 install -r requirements.txt
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

- `POST /submit` with `{ "record": { ...form fields... }, "files": [ ...one entry per file... ] }`.
- Each file entry is **either** `{ "name", "field", "dataB64" }` (inline bytes) **or** `{ "name", "field", "url", "contentType", "size" }` (Blob reference) — see "Two upload paths" above. `app.py` branches on whether `url` is present.
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

## CI/CD (Docker/Kubernetes path — GitHub Actions)

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

- **Never commit real credentials.** `.env`, `charts/direct-lab/values.secrets.yaml`, the GitHub Actions secrets, and Vercel's Environment Variables are the only places real passwords/keys should exist — never in a values.yaml, `app.py`, or a workflow file.
- **`submissions/` (when enabled) contains personal data** (applicant names, emails, phone numbers, uploaded files) — same for the MongoDB data itself and for files in Vercel Blob. Treat all of these with normal PII handling: no public exposure, proper backup/retention policy for the production Mongo instance.
- **MongoDB Atlas's free tier (M0) has a small storage cap** (512MB at the time of writing) — this is exactly why the Blob upload path stores files in Blob and only a URL reference in Mongo, rather than duplicating bytes into GridFS. If Atlas ever gets upgraded off the free tier, nothing about this design needs to change.
- **Mongo is the source of truth.** If it's unreachable, submissions correctly fail loudly (`502`) rather than silently disappearing — the frontend's local-storage fallback exists for exactly this case, but it's a safety net, not a replacement for Mongo being up.
