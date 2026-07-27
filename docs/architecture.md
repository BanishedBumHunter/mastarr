# Architecture

## The shape of the problem

Sonarr, Radarr, Lidarr, Readarr and Prowlarr all descend from the same codebase. Their APIs
are therefore *nearly* identical — same endpoint names, same envelope shapes, same
`X-Api-Key` header — but not quite:

- **API versions differ.** Sonarr and Radarr are on `/api/v3`. Prowlarr, Lidarr and Readarr
  are on `/api/v1`.
- **Media nouns differ.** Sonarr nests `series`, Radarr nests `movie`, Lidarr nests
  `artist`. Prowlarr has no media library at all.
- **Small field spellings differ.** Download clients use `enable`; Prowlarr's indexer list
  uses `enabled`.
- **Capabilities differ.** Prowlarr has no queue, no root folders, no quality profiles, and
  no disk space endpoint.

Mastarr's adapter layer exists to absorb exactly this: everything above it works with one
normalized vocabulary.

## Layers

```
  React SPA  ──────────────────────────────────  role-based route trees
      │  fetch, cookie auth
  FastAPI routers  ────────────────────────────  api/{auth,users,services,discovery,dashboard}
      │                    ▲
      │                    └── auth/deps.py    ← the single authorization seam
  services.py  ────────────────────────────────  DB rows → adapters, fan-out, snapshot cache
      │
  adapters/  ──────────────────────────────────  the ONLY place that speaks HTTP to an *arr
      │        base.py (all shared logic) + thin subclasses + registry
      ▼
  Sonarr / Radarr / Prowlarr
```

### `adapters/` — the containment boundary

`base.ArrAdapter` holds the entire shared implementation. Subclasses declare *dialect*, not
behaviour:

```python
class ProwlarrAdapter(ArrAdapter):
    service_type = "prowlarr"
    api_version = "v1"          # not v3 — this is why it's a class attribute
    default_port = 9696
    media_endpoint = None       # manages no library
    unsupported = frozenset({"disk_space", "queue", "quality_profiles", ...})
```

`RadarrAdapter` is about twenty lines. That ratio is the design goal, and
`registry.py` is what keeps it: adding a service type means one new file and one dict entry.

Two invariants make the layer worth having:

1. **No raw *arr HTTP call exists outside this package.** Every request funnels through
   `ArrAdapter._request`.
2. **No `httpx` exception escapes it.** Everything is mapped to the `AdapterError`
   hierarchy — `ServiceUnreachable`, `ServiceUnauthorized`, `ServiceError`,
   `UnsupportedOperation`. Callers catch one exception type.

#### Why there is no "missing API key" short-circuit

An early version refused to send a request when no key was configured, raising
`ServiceUnauthorized` immediately. That was wrong: it reported a **dead host** as
`unauthorized`, sending the operator to hunt for a credential problem that didn't exist.

Reachability is a property of the network, so the network decides it. An unauthenticated
request to a live *arr returns 401 quickly and cheaply; a dead one fails to connect. The
distinction survives.

### Discovery — presence vs identity

The two phases exist because the *arrs give exactly two signals:

| Phase | Endpoint | Auth | Tells you |
|-------|----------|------|-----------|
| Presence | `GET /ping` | none | something *arr-shaped is listening |
| Identity | `GET /api/<v>/system/status` | key | exactly what it is, and its version |

Presence-without-credentials is what makes a zero-config first run possible. Identity is
authoritative — `appName`, never the port number. `identify()` tries the port's implied type
first, then every other registered type, which is how a service on a non-standard port (and
therefore an unexpected API version) still resolves correctly.

### `ServiceSnapshot` — a total type

`snapshot()` never raises. Every failure becomes a snapshot carrying a `ServiceStatus`:

`ONLINE` · `DEGRADED` · `UNAUTHORIZED` · `UNREACHABLE` · `UNKNOWN`

This is the mechanism behind "the UI degrades, never crashes". The dashboard fan-out uses
`asyncio.gather(..., return_exceptions=True)` and converts even an unexpected non-adapter
exception into an `UNKNOWN` card. `GET /api/dashboard` returns 200 with a complete picture
even when every service is down.

Health severity feeds the status: `warning`/`error` issues make a service `DEGRADED`, while
a `notice` (e.g. "an update is available") leaves it `ONLINE`. An available update is not an
operational problem.

### Authorization — one seam

`auth/deps.require_role(Role.ADMIN)` is the only place an authorization decision is made.
Routers declare it once:

```python
router = APIRouter(prefix="/users", dependencies=[Depends(require_admin)])
```

Applying it at the router means a route added later cannot ship unprotected by accident.

`Role` is an enum with a rank ordering, never an `is_admin` boolean — so `ADMIN` satisfies
`REQUESTER` automatically, and a third role is one entry in `_RANK`.

Role and session epoch are re-read from the database on every request rather than trusted
from the token, so a role downgrade or password change takes effect immediately. The
`token_epoch` counter gives us session invalidation without a server-side session table.

`roles.py` lives at the package top level rather than inside `auth/` because `models` needs
it too, and the obvious placement created a `models → auth → models` import cycle.

### Frontend — role trees, not role flags

`App.tsx` mounts one of two entirely separate `<Routes>` blocks. A Requester's tree contains
no admin routes to navigate to; there is no admin component rendered-then-hidden. The
backend enforces the same boundary independently, so the UI split is defence in depth rather
than the control itself.

### Secrets

- API keys: Fernet-encrypted in SQLite. The Fernet key comes from `MASTARR_SECRET_KEY`, or a
  `0600` file on the data volume generated at first run.
- Session signing uses a **separate** secret, so rotating it (log everyone out) can't be
  confused with rotating the encryption key (make every stored API key unreadable).
- `logging.py` installs a redaction filter on the **root** logger, so it applies to every
  library, not just Mastarr's own log calls. It scrubs both registered key values and
  structural patterns (`X-Api-Key`, `?apikey=`, `Bearer …`).
- Keys travel as headers, never query params — query strings end up in every intervening
  proxy's access log.

### Persistence

SQLModel over SQLite; four tables (`service`, `user`, `schema_version`). No Alembic while
the project is INACTIVE — `create_all` plus a stamped version row. That's a deliberate
deferral recorded in `CLAUDE.md`, to be resolved before the project carries real data.

## Testing

129 tests, no network access required.

- **Adapters** — `respx` mocks httpx against recorded v3/v1 payloads: parsing, every error
  path, the version split, and the unsupported-operation declarations.
- **Discovery** — both phases, including a service on the wrong port and a non-*arr squatting
  on an *arr port.
- **Auth** — the full role matrix is parameterized over every admin endpoint, so a new
  unprotected endpoint fails the suite.
- **Degradation** — a dashboard where every service is down, and one where a single dead
  service sits beside healthy ones.
- **Secrets** — asserts the plaintext key appears in neither the database file, the API
  responses, nor captured log output.
- **Routing** — the SPA fallback must not shadow `/api`, and path traversal must not escape
  the static root.

## Extending

**A new *arr type** — write `adapters/<type>.py` with the class attributes, add it to
`ADAPTERS` in `registry.py`. Discovery, the dashboard, the type dropdown, and the API all
pick it up with no further changes; the frontend reads the type list from
`GET /api/services/types`.

**A new role** — add it to `Role` and give it a rank in `_RANK`. Existing checks keep
working.

**Priorities 3–7** — the adapter interface already declares `queue()`, `history()`,
`quality_profiles()`, `root_folders()`, `download_clients()`, `indexers()` and `search()`.
Each remaining priority is a new API module plus UI, not a refactor.
