# Installing Mastarr on TrueNAS SCALE

Written against a real target: **TrueNAS SCALE 25.10.2.1** at `192.168.1.250`, which already
runs Sonarr, Radarr, Prowlarr and Seerr as apps, plus three custom (compose-based) apps.

TrueNAS custom apps are plain `docker compose` — the app description is literally *"a custom
app where user can use his/her own docker compose file"*. So installing Mastarr is: get the
image onto the NAS, create a config directory, paste a compose file.

---

## Step 0 — Know your layout

| Thing | Value on this system |
|---|---|
| TrueNAS version | 25.10.2.1 |
| Pools | `Largestorage` (30 TB), `faststorage` (250 GB) |
| App config convention | `/mnt/faststorage/app-configs/<app>` |
| Sonarr | `192.168.1.250:8989` — API **v3** |
| Radarr | `192.168.1.250:7878` — API **v3** |
| Prowlarr | `192.168.1.250:9696` — API **v1** |
| Seerr | `192.168.1.250:5057` — note: **not** the default 5055 |

Mastarr will live at `/mnt/faststorage/app-configs/mastarr` and listen on **8770**.

> Because Mastarr runs on the same box as the *arrs, address them by the host IP
> (`http://192.168.1.250:8989`), not by container name. TrueNAS puts each app in its own
> compose project, so there is no shared network to resolve names across.

---

## Step 1 — Get the image onto the NAS

TrueNAS pulls images; it does **not** build them. `build:` in a custom app's compose file
will not work. Pick one of these.

### Option A — SSH transfer (no registry needed) ✅ simplest

SSH is already enabled on the NAS. Build locally, stream the image straight over:

```bash
cd ~/projects/mastarr
docker build -f backend/Dockerfile -t mastarr:latest .
docker save mastarr:latest | ssh truenas_admin@192.168.1.250 'docker load'
```

Then verify it landed:

```bash
ssh truenas_admin@192.168.1.250 'docker images | grep mastarr'
```

Because the image now exists locally on the NAS, the compose file must not try to pull it —
`pull_policy: never` in Step 3 handles that.

> Only password SSH is configured for `truenas_admin` (no key installed). If you want this
> to be scriptable, add your key first:
> `ssh-copy-id truenas_admin@192.168.1.250`

### Option B — Registry

Better if you'll rebuild often or want TrueNAS to handle updates:

```bash
docker build -f backend/Dockerfile -t ghcr.io/<you>/mastarr:latest .
docker push ghcr.io/<you>/mastarr:latest
```

Use that image name in Step 3 and drop `pull_policy: never`. Add registry credentials under
**Apps → Manage Container Images** if the package is private.

### Option C — Build on the NAS

Clone the repo to a dataset and `docker build` over SSH. Works, but it puts a toolchain and
source tree on the NAS for no real benefit over A. Not recommended.

---

## Step 2 — Create the config directory

Mastarr keeps its SQLite DB and generated secrets in one directory.

```bash
ssh truenas_admin@192.168.1.250 \
  'mkdir -p /mnt/faststorage/app-configs/mastarr && chown -R 1000:1000 /mnt/faststorage/app-configs/mastarr'
```

The `chown` matters: the container runs as **uid 1000** (non-root). Without it the app cannot
create its database and will crash on first start.

You can equally create the directory in the TrueNAS UI under
**Datasets → faststorage → app-configs**, then fix ownership under **Edit Permissions**.

---

## Step 3 — Create the custom app

**Apps → Discover Apps → Custom App** (top-right menu), then choose the YAML / compose
option and paste this:

```yaml
services:
  mastarr:
    image: mastarr:latest
    # Required for Option A — the image was loaded locally, so don't try to pull it.
    pull_policy: never
    restart: unless-stopped

    ports:
      - "8770:8000"

    environment:
      MASTARR_DATA_DIR: /data

      # Generate these ONCE and keep them. See the warning below.
      MASTARR_SECRET_KEY: "PASTE_FERNET_KEY_HERE"
      MASTARR_JWT_SECRET: "PASTE_RANDOM_STRING_HERE"

      MASTARR_LOG_LEVEL: INFO
      MASTARR_SESSION_HOURS: "12"

      # Pre-fill the discovery scan box with this host.
      MASTARR_DISCOVERY_HOSTS: '["192.168.1.250"]'

    volumes:
      - /mnt/faststorage/app-configs/mastarr:/data
```

Notes on why this file looks the way it does:

- **No `container_name`** — TrueNAS manages the compose project and naming.
- **No `build:`** — unsupported for apps; see Step 1.
- **Host path, not a named volume** — matches how your Sonarr/Radarr/Prowlarr apps already
  store config, so backups and snapshots cover it the same way.

### Generate the two secrets first

```bash
# MASTARR_SECRET_KEY — encrypts stored *arr API keys
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# MASTARR_JWT_SECRET — signs login sessions
openssl rand -base64 48
```

> **Set these explicitly.** If left unset, Mastarr generates them into `/data` on first run,
> which is fine — until the dataset is recreated or the app is reinstalled, at which point
> every stored *arr API key becomes permanently unreadable and everyone is logged out.
> Setting them in the app config makes the install reproducible.

---

## Step 4 — First run

Browse to **`http://192.168.1.250:8770`**.

1. The first screen creates your **admin account** — it is only available while no user
   exists, so claim it immediately.
2. Go to **Services → Scan**, enter `192.168.1.250`, press **Scan**. Sonarr, Radarr and
   Prowlarr should be found without any credentials (Mastarr uses the unauthenticated
   `/ping` endpoint for this).
3. Paste each service's API key into the row and press **Add**.

### Where the API keys are

In each service's own UI under **Settings → General → Security → API Key**. Or read them
directly off the NAS:

```bash
ssh truenas_admin@192.168.1.250 \
  'grep -o "<ApiKey>[^<]*" /mnt/faststorage/app-configs/{sonarr,radarr,prowlarr}/config.xml'
```

Once keys are in, each card should flip from **Needs API key** to **Online** with a version
number, health warnings and disk usage.

---

## Step 5 — Reverse proxy (optional)

You already run NPMplus on 443. To serve Mastarr over TLS, add a proxy host pointing at
`192.168.1.250:8770`.

The session cookie is deliberately **not** marked `Secure`, so plain-HTTP LAN access keeps
working. Terminate TLS at NPMplus; nothing in Mastarr needs changing.

---

## Troubleshooting

**App won't start / crashes immediately**
Almost always directory ownership. Confirm:
`ssh truenas_admin@192.168.1.250 'ls -ln /mnt/faststorage/app-configs | grep mastarr'`
The numeric owner must be `1000`.

**`image not found` / app stuck pulling**
`pull_policy: never` is set but the image was never loaded. Re-run Step 1 Option A and check
`docker images | grep mastarr` on the NAS.

**Everything shows "Unreachable"**
Mastarr can't reach the *arrs. Verify from the NAS itself:
`ssh truenas_admin@192.168.1.250 'curl -s http://192.168.1.250:8989/ping'` → `{"status":"OK"}`

**Everything shows "Needs API key" after adding keys**
The key was rejected. The card's error distinguishes *"No API key configured"* from *"API key
was rejected"* — the latter means the key is wrong, not missing.

**Logged out after redeploying, or keys unreadable**
`MASTARR_JWT_SECRET` / `MASTARR_SECRET_KEY` changed or were regenerated. Set them explicitly
(Step 3) so they survive reinstalls.

---

## Updating

```bash
cd ~/projects/mastarr && git pull
docker build -f backend/Dockerfile -t mastarr:latest .
docker save mastarr:latest | ssh truenas_admin@192.168.1.250 'docker load'
```

Then **Apps → mastarr → Restart**. The `/data` volume persists, so services, users and
settings survive the update.
