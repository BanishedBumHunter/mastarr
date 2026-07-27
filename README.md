# Mastarr

A unified control plane for the *arr stack — one pane of glass and one config surface over
Sonarr, Radarr, Prowlarr and friends.

Mastarr is an **orchestration layer**. It talks to each service's existing public REST API
and does not fork, patch, or replace any of them. That is what keeps it update-safe: it
depends only on the documented *arr API and Overseerr's API, so upstream releases don't
break it.

```
┌─────────────────────────────────────────┐
│  Mastarr  (FastAPI + React, 1 container) │
└───────────────────┬─────────────────────┘
                    │  HTTP + X-Api-Key
      ┌─────────────┼──────────────┐
      ▼             ▼              ▼
   Sonarr        Radarr        Prowlarr        …over the LAN, no shared network
   :8989 v3      :7878 v3      :9696 v1           namespace required
```

## Status

Build priorities **1 and 2 are complete**:

| # | Feature | Status |
|---|---------|--------|
| 1 | Adapter layer, auto-discovery, health dashboard | ✅ Done |
| 2 | Auth + two-role model with a permission seam | ✅ Done |
| 3 | Unified queue / history / activity views | Planned |
| 4 | Cross-stack config push (profiles, root folders, clients) | Planned |
| 5 | Indexer management via Prowlarr | Planned |
| 6 | Requests via `OverseerrAdapter` | Planned |
| 7 | Setup wizard + declarative YAML | Partial — YAML config works, wizard planned |

Currently supported service types: **Sonarr**, **Radarr**, **Prowlarr** (health/status).

## Quickstart

### Docker (recommended)

```bash
git clone <your-remote> mastarr && cd mastarr
docker compose -f deploy/docker-compose.yml up --build -d
```

Open <http://localhost:8770>. The first screen creates your admin account.

Then either press **Scan** on the Services page to find your *arr services automatically,
or add them by hand. Each service's API key is under its own
**Settings → General → Security**.

### Local development

Backend:

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
MASTARR_DATA_DIR=./data .venv/bin/uvicorn mastarr.main:app --reload
```

Frontend (Vite proxies `/api` to port 8000):

```bash
cd frontend && npm install && npm run dev
```

Tests:

```bash
cd backend && .venv/bin/python -m pytest
```

## How discovery works

The *arrs expose exactly two useful signals, so discovery has two phases:

1. **Presence** — `GET /ping` is unauthenticated on every *arr and returns
   `{"status":"OK"}`. Mastarr finds services this way *before* you've supplied any
   credentials.
2. **Identity** — `GET /api/<version>/system/status` returns an `appName` field, and
   requires a key. That field is authoritative.

The port is only ever a **hint** used to guess which API version to try first. A service on
8989 reporting `appName: Radarr` is treated as Radarr.

> **The API version is per-service.** Sonarr and Radarr are on `/api/v3`; **Prowlarr,
> Lidarr and Readarr are on `/api/v1`**. Mastarr parameterizes this per adapter, so mixed
> stacks work transparently.

## Configuration

Precedence: **environment variables > `config.yml` > defaults.**

| Variable | Default | Purpose |
|----------|---------|---------|
| `MASTARR_DATA_DIR` | `/data` | SQLite DB, generated secrets |
| `MASTARR_CONFIG_FILE` | *(unset)* | Path to a declarative `config.yml` |
| `MASTARR_SECRET_KEY` | *generated* | Fernet key encrypting stored API keys |
| `MASTARR_JWT_SECRET` | *generated* | Session token signing key |
| `MASTARR_SESSION_HOURS` | `12` | Session lifetime |
| `MASTARR_HTTP_TIMEOUT` | `10` | Per-request timeout against *arr services |
| `MASTARR_DASHBOARD_CACHE_SECONDS` | `5` | Snapshot cache TTL |
| `MASTARR_DISCOVERY_HOSTS` | `[]` | Hosts scanned when the form is left empty |
| `MASTARR_LOG_LEVEL` | `INFO` | Log verbosity |

Both secrets are generated and persisted to the data volume (mode `0600`) on first run.
**Set them explicitly if you ever recreate the volume** — a lost `secret.key` makes every
stored API key unreadable.

For a version-controlled setup, see [`deploy/config.example.yml`](deploy/config.example.yml).
Services declared there are marked read-only in the UI, because a UI edit would be reverted
on the next restart. Use `api_key_env` rather than `api_key` so the committed file stays
credential-free.

## Deploying on TrueNAS SCALE

Mastarr ships as a single container plus one volume, which maps cleanly onto a TrueNAS
custom app.

1. **Create a dataset** for persistent state, e.g. `tank/apps/mastarr`.

2. **Build and publish the image** (TrueNAS pulls, it does not build):

   ```bash
   docker build -f backend/Dockerfile -t <your-registry>/mastarr:latest .
   docker push <your-registry>/mastarr:latest
   ```

   For a registry-free setup, build on the NAS itself and reference `mastarr:latest`.

3. **Apps → Discover Apps → Custom App** (or *Install via YAML* on newer releases) and use
   [`deploy/docker-compose.yml`](deploy/docker-compose.yml) as your starting point. The
   pieces that matter:

   - **Image**: `<your-registry>/mastarr:latest`
   - **Port**: container `8000` → host `8770` (any free host port)
   - **Storage**: host path `/mnt/tank/apps/mastarr` → mount `/data`
   - **Environment**: at minimum set `MASTARR_SECRET_KEY` and `MASTARR_JWT_SECRET` so a
     redeploy doesn't invalidate stored keys and sessions

4. **Permissions.** The container runs as uid **1000**. Make sure the dataset is writable
   by it, or the app cannot create its database:

   ```bash
   chown -R 1000:1000 /mnt/tank/apps/mastarr
   ```

5. **Networking.** Mastarr reaches the *arrs over the LAN by URL — it does **not** need to
   share their network namespace. Use the addresses you'd type in a browser, e.g.
   `http://192.168.1.250:8989`. If your *arr apps are only on an internal bridge, expose
   them or put Mastarr on the same bridge.

6. Browse to `http://<nas-ip>:8770` and create the admin account.

Put Mastarr behind your reverse proxy for TLS. The session cookie is intentionally **not**
`Secure`, because that would silently break plain-HTTP LAN access — terminate TLS at the
proxy.

## Security notes

- API keys are **Fernet-encrypted at rest**; no endpoint ever returns a stored key, only
  whether one is set.
- A **global logging filter** redacts key material — both keys Mastarr knows about and
  anything matching `X-Api-Key`, `?apikey=`, or `Authorization: Bearer` patterns — so a
  third-party library cannot leak one into the logs.
- Passwords are hashed with **argon2**.
- Sessions are httpOnly cookies; the frontend never holds a token. Scripts can get a Bearer
  token from `POST /api/auth/token`.
- Role and session validity are **re-read from the database on every request**, so a role
  downgrade or forced logout takes effect immediately rather than at token expiry.

## Architecture

See [docs/architecture.md](docs/architecture.md). Project conventions and durable rules
live in [CLAUDE.md](CLAUDE.md).

## Licence

Unlicensed / private homelab project.
