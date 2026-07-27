# Mastarr — Claude Code operating rules

## What this is

Mastarr is a self-hosted **control plane** for the *arr media-automation stack (Sonarr,
Radarr, Lidarr, Readarr, Prowlarr) plus request front-ends (Overseerr/Jellyseerr).

It is an **orchestration layer**. It talks to each service's existing public REST API. It
does not fork, vendor, patch, or replace any *arr. This is the property that keeps Mastarr
update-safe, and it is not negotiable.

## Project status

Status lives in `.project-status`. Currently **INACTIVE** — still building, direct commits
on the working branch are allowed after plan approval.

When this flips to ACTIVE: no direct commits to the working branch, all changes go to a
`sandbox/<short-description>` branch with an automatically opened PR, and merges are manual
and owner-only.

## Durable rules

### 1. Every service interaction goes through an adapter

No raw HTTP call to an *arr may exist outside `backend/mastarr/adapters/`. Not in a route
handler, not in a service module, not "just this once" for a quick fix. If you need a new
call, it becomes a method on the adapter interface.

### 2. Adding a new *arr type is a one-file change

A new service type = one new file in `adapters/` + one line in `adapters/registry.py`.
If adding a service type ever requires touching route handlers, the frontend, or the base
adapter, the abstraction has leaked — fix the abstraction, don't special-case the service.

### 3. The API version is per-service, never assumed

Sonarr and Radarr are on `/api/v3`. **Prowlarr, Lidarr, and Readarr are on `/api/v1`.**
The version is a class attribute on the adapter. Never hardcode `v3` in a shared path.

### 4. Identity comes from `system/status`, never from the port

A service answering on 8989 is a *hint* that it's Sonarr. The `appName` field in
`GET /api/<version>/system/status` is the proof. Port numbers are for probing only.

### 5. Absent or unreachable services degrade, never crash

Every adapter method raises from the `AdapterError` hierarchy in `adapters/errors.py`.
An `httpx` exception must never escape the adapter package. Fan-out calls use
`asyncio.gather(..., return_exceptions=True)`. A dead service renders a degraded card —
it never blanks the page, stalls the response, or trips an error boundary.

### 6. Authorization goes through one seam

Endpoints declare their required role via the `require_role(...)` dependency in
`auth/deps.py`. Ad-hoc role checks inside handlers are banned — if you find yourself
writing `if user.role == ...` in a route, that logic belongs in the seam.

`Role` is an enum (`auth/roles.py`), never a boolean. Adding a third role must be additive.

### 7. The frontend renders per role

A Requester's bundle contains no admin routes — not hidden ones, not disabled ones. Role
gating is route-tree level, not CSS.

### 8. API keys are encrypted at rest and never logged

Keys are Fernet-encrypted in SQLite. `logging.py` installs a global redaction filter.
Never `print()` a key, never put one in an error message, never commit one.

## Deliberate deferrals

- **No Alembic.** Schema is `create_all` + a `schema_version` row. The project is INACTIVE
  with no real data. Migrations get added when it goes ACTIVE — before, not after.
- **Prowlarr is health/status-only.** Indexer management is build priority 5.
- **Requester UI is a placeholder shell.** Rich discovery/browse is an Overseerr-backed
  feature (build priority 6) and is intentionally not reimplemented natively.

## Build priorities

1. ~~Adapter layer + auto-discovery + health dashboard~~ ✅
2. ~~Auth + two-role model with permission seam~~ ✅
3. Unified queue/history/activity views
4. Cross-stack config: quality profiles, custom formats, root folders, download clients
5. Indexer management via Prowlarr
6. Requests via `OverseerrAdapter`
7. Setup wizard + declarative YAML config

## Conventions

- Backend: Python 3.12, FastAPI, async throughout, SQLModel over SQLite.
- Frontend: Vite + React + TypeScript, TanStack Query, Tailwind. Dark default, dense,
  desktop-first. This is a control plane, not a consumer app.
- Tests: `pytest` + `respx` for adapter HTTP mocking. Fixtures are recorded real payloads.
- Config precedence: env > YAML > DB > defaults.
