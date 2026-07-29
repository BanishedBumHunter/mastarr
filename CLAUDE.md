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

Sonarr and Radarr are on `/api/v3`. **Prowlarr, Lidarr, Readarr and Jellyseerr are all on
`/api/v1`.**
The version is a class attribute on the adapter. Never hardcode `v3` in a shared path.

### 4. Identity comes from `system/status`, never from the port

A service answering on 8989 is a *hint* that it's Sonarr. The `appName` field in
`GET /api/<version>/system/status` is the proof. Port numbers are for probing only.

### 5. Declare what a service type cannot do

Every type must list the endpoints it lacks in its `unsupported` frozenset — verified by
probing, not guessed. An undeclared gap 404s at runtime and becomes a "service failed"
banner on every aggregated view. A warning that is always present is one people learn to
ignore, which costs you the warnings that matter.

Prowlarr and Jellyseerr both needed this: neither has a calendar, library, queue or disk
space, despite sharing the *arr transport.

### 6. Absent or unreachable services degrade, never crash

Every adapter method raises from the `AdapterError` hierarchy in `adapters/errors.py`.
An `httpx` exception must never escape the adapter package. Fan-out calls use
`asyncio.gather(..., return_exceptions=True)`. A dead service renders a degraded card —
it never blanks the page, stalls the response, or trips an error boundary.

### 7. Authorization goes through one seam

Endpoints declare their required role via the `require_role(...)` dependency in
`auth/deps.py`. Ad-hoc role checks inside handlers are banned — if you find yourself
writing `if user.role == ...` in a route, that logic belongs in the seam.

`Role` is an enum in `mastarr/roles.py` — top level, not inside `auth/`, because `models`
needs it too and the obvious placement created a `models -> auth -> models` import cycle.
Never a boolean; adding a third role must be additive.

### 8. The frontend renders per role

A Requester's bundle contains no admin routes — not hidden ones, not disabled ones. Role
gating is route-tree level, not CSS.

### 9. API keys are encrypted at rest and never logged

Keys are Fernet-encrypted in SQLite. `logging.py` installs a global redaction filter.
Never `print()` a key, never put one in an error message, never commit one.

### 10. Config portability is computed, not assumed

Not everything can be copied between services. A **quality profile** is a list of quality
*IDs*, and the IDs mean different things per type — Sonarr's vocabulary is
`SDTV`/`DVD`/`Bluray-480p`, Radarr's is `WORKPRINT`/`CAM`/`TELESYNC`. Copying one across
produces a profile referencing qualities that don't exist. **Naming** is per-type too.
**Custom formats** are specification-based and portable anywhere.

`config_sync.PORTABILITY` encodes this and `compatibility()` enforces it. A target that
can't take a resource is reported `incompatible` with a reason, never written to.

Config writes are always **preview then confirm**, and `apply` re-runs the preview rather
than trusting a plan the client sends back — a stale diff would overwrite newer work.

### 11. Compare behaviour, not presentation

Diffs strip cosmetic metadata (`infoLink`, `implementationName`, field `label`/`helpText`,
ids). The *arrs regenerate all of it, and some is service-branded — a Sonarr custom
format's `infoLink` points at the Sonarr wiki and Radarr rewrites it on save. Comparing it
made a correctly-synced item show a permanent "update available".

### 12. Aggregated views report what's missing

When a fan-out view drops a service, say so (`failures[]` → `PartialWarning`). Silently
returning partial data is worse than an error: the user believes their library really is
that small.

## Deliberate deferrals

- **No Alembic.** Schema is `create_all` + a `schema_version` row, plus additive-only
  column adds in `db._apply_additive_migrations`. If a change ever needs more than an
  `ALTER TABLE ADD COLUMN`, that is the signal to adopt Alembic rather than grow that
  function.
- **Prowlarr is health/status-only.** Indexer management is build priority 5.
- **Deep per-service config is not reimplemented.** Custom formats, naming schemes, import
  lists and connection settings stay in the native apps, reached by deep link from the item
  detail view. That is four admin UIs' worth of surface for a handful of set-once settings,
  and the part most likely to break on upstream changes.

## Build priorities

1. ~~Adapter layer + auto-discovery + health dashboard~~ ✅
2. ~~Auth + two-role model with permission seam~~ ✅
3. ~~Unified queue/history/activity views~~ ✅
4. ~~Cross-stack config: profiles, custom formats, root folders, clients, naming~~ ✅
5. ~~Indexer management via Prowlarr~~ ✅
6. ~~Requests via Jellyseerr/Overseerr~~ ✅
7. ~~Setup wizard + declarative YAML config~~ ✅

All seven complete. Also shipped beyond the original list: unified calendar, unified
library with everyday management, an admin Settings surface, and Lidarr/Readarr adapters.

## Conventions

- Backend: Python 3.12, FastAPI, async throughout, SQLModel over SQLite.
- Frontend: Vite + React + TypeScript, TanStack Query, hand-written CSS (no framework —
  one less build dependency and full control over a dense grid). Dark default,
  desktop-first. This is a control plane, not a consumer app.
- Tests: `pytest` + `respx` for adapter HTTP mocking. Fixtures are recorded real payloads.
- Config precedence: env > YAML > DB > defaults.
