# Installing Mastarr on TrueNAS SCALE

A complete walkthrough, from an empty repo to a running app. Written for TrueNAS SCALE
24.10+ (tested against 25.10), where apps are Docker and custom apps are plain
`docker compose`.

**If you just want to install it and someone already published the image**, skip to
[Part 3](#part-3--install-on-truenas). Parts 1–2 are for whoever is publishing.

---

## The one thing to understand first

TrueNAS **pulls images. It does not build them.**

There is no `git clone` step, and `build:` in a custom app's compose file does nothing.
So putting this repo on GitHub is *not by itself* enough to install it — something has to
turn the source into a published container image first. That's what Part 2 sets up, once,
after which installing really is just pasting a YAML file.

```
  your machine              GitHub                    your NAS
  ───────────              ──────                    ────────
  git push        ──►   Actions builds image  ──►   TrueNAS pulls
                        pushes to GHCR              custom app YAML
```

---

## Part 1 — Build and test locally

Verify it works on your machine before publishing anything.

```bash
git clone <your-repo-url> mastarr && cd mastarr

# Backend tests — no network or *arr services required.
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q          # expect: all passing
cd ..

# Build the image exactly as CI will. Context is the repo root, so the build
# sees both ./frontend and ./backend.
docker build -f backend/Dockerfile -t mastarr:latest .

# Run it. Any writable directory works for /data.
mkdir -p /tmp/mastarr-data
docker run --rm -p 8770:8000 \
  --user "$(id -u):$(id -g)" \
  -v /tmp/mastarr-data:/data \
  mastarr:latest
```

Browse to <http://localhost:8770>. You should get a "create admin account" screen. That
confirms the image is good. Ctrl-C to stop.

---

## Part 2 — Publish to GitHub (once)

### 2.1 Push the repo

```bash
git remote add origin git@github.com:YOUR_USERNAME/mastarr.git
git push -u origin main
```

Before pushing, sanity-check that no credentials are going with it:

```bash
git ls-files | grep -E '\.env$|config\.yml$|\.db$|secret'
```

That should print **nothing**. `.gitignore` already covers `.env*`, `config.yml`,
`*.db`, `secret.key` and `jwt.secret` — only the `.example` files are tracked.

### 2.2 Let CI build the image

`.github/workflows/build.yml` runs the tests, builds the frontend, builds the image, and
pushes it to GitHub Container Registry on every push to `main`. There are **no secrets to
configure** — it uses the `GITHUB_TOKEN` that Actions provides automatically.

Watch it under the repo's **Actions** tab. It takes a few minutes.

> **If your push is rejected with** *"refusing to allow a Personal Access Token to create or
> update workflow `.github/workflows/build.yml` without `workflow` scope"*:
>
> GitHub requires a separate `workflow` scope to push workflow files, and it rejects the
> whole push if *any* commit in it touches one. Either:
>
> - **Add the scope** — github.com/settings/tokens → your token → tick **`workflow`** →
>   Update. Then push again. (Cleanest.)
> - **Or add the file through the web UI** — your browser session isn't subject to the
>   token's scopes. Repo → **Actions** → **set up a workflow yourself**, paste the contents
>   of `build.yml`, commit. Then `git pull` locally to sync.
>
> This only bites once, when bootstrapping the repo. Anyone who *forks* it gets the
> workflow already in place.

### 2.3 Check the package is public

Your image is now at `ghcr.io/YOUR_USERNAME/mastarr:latest` (lowercase — GHCR lowercases
usernames).

**If your repo is public, the package inherits that and you're done.** Verify without
needing any credentials:

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  "https://ghcr.io/v2/YOUR_USERNAME/mastarr/manifests/latest" \
  -H "Authorization: Bearer $(curl -s 'https://ghcr.io/token?scope=repository:YOUR_USERNAME/mastarr:pull&service=ghcr.io' | sed -E 's/.*"token":"([^"]+)".*/\1/')"
```

`200` means anyone — including your NAS — can pull it. Anything else means it's private.

**If it's private** (usual when the repo is private), either flip it:
**GitHub profile → Packages → mastarr → Package settings → Danger Zone → Change visibility
→ Public**, or keep it private and add credentials on the NAS under
**Apps → Manage Container Images → Add**, using a token with `read:packages` scope.

A private package is the usual cause of a `403` / `denied` when TrueNAS tries to pull.

---

## Part 3 — Install on TrueNAS

### 3.1 Gather your values

You need four things. Write them down before you start.

| # | Value | How to find it |
|---|---|---|
| 1 | **Your dataset path** | Where app config lives, e.g. `/mnt/tank/apps/mastarr`. Look at how your existing apps are laid out and match it. |
| 2 | **The uid:gid owning it** | `ls -ln /mnt/tank/apps` over SSH. TrueNAS's `apps` user is usually `568:568`; a normal user is often `1000:1000`. |
| 3 | **Your *arr host IP** | The LAN IP of whatever runs Sonarr/Radarr — usually the NAS itself, e.g. `192.168.1.10`. Not `localhost`. |
| 4 | **Two generated secrets** | See 3.3. |

### 3.2 Create the data directory

Either in the UI (**Datasets → your pool → Add Dataset**, then **Edit Permissions** to set
the owner), or over SSH:

```bash
mkdir -p /mnt/YOURPOOL/apps/mastarr
chown -R 1000:1000 /mnt/YOURPOOL/apps/mastarr    # use YOUR uid:gid
```

This directory holds the SQLite database and generated secrets — **it is the entire state
of your install.** Put it somewhere your snapshots cover.

### 3.3 Generate the two secrets

Run these on any machine with Python and openssl (your desktop is fine):

```bash
# MASTARR_SECRET_KEY — encrypts stored *arr API keys at rest
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# MASTARR_JWT_SECRET — signs login sessions
openssl rand -base64 48
```

Save both somewhere safe, like a password manager.

> **Why you must set these explicitly.** If you leave them unset, Mastarr generates them
> into `/data` on first run, which works fine — right up until you reinstall the app or
> recreate the dataset. At that point every stored *arr API key becomes permanently
> unreadable and everyone is logged out. Setting them by hand makes the install
> reproducible.

### 3.4 Create the app

**Apps → Discover Apps → Custom App** (top-right) **→ Install via YAML.**

Paste the contents of [`deploy/truenas-custom-app.yaml`](../deploy/truenas-custom-app.yaml).
It is heavily commented and every line you must change is marked `<<< CHANGE ME >>>`.
There are five:

1. `image:` — your GitHub username
2. `MASTARR_SECRET_KEY` — from 3.3
3. `MASTARR_JWT_SECRET` — from 3.3
4. `volumes:` — your dataset path from 3.1
5. `user:` — your uid:gid from 3.1

Everything else has a working default. Press **Install**.

### 3.5 First run

Browse to **`http://YOUR_NAS_IP:8770`**.

1. **Create the admin account immediately.** That screen is open to anyone who can reach
   the page until a user exists — it locks itself permanently once one does.
2. Go to **Services**, type your *arr host IP into the scan box, press **Scan**. Sonarr,
   Radarr and Prowlarr should appear *without* any credentials — Mastarr finds them via
   their unauthenticated `/ping` endpoint.
3. Paste each service's API key into its row and press **Add**. Find keys in each
   service's own UI under **Settings → General → Security → API Key**.

Cards flip from **Needs API key** to **Online**, showing version, health warnings and disk
usage.

### 3.6 Add your friends (optional)

**Users → Create user**, role **Requester**. They get a stripped-down UI with no access to
your stack configuration, queues, services, or other users' data — the admin routes are not
merely hidden from them, they aren't served at all.

---

## Updating

```bash
git pull                      # or make your changes
git push                      # CI rebuilds and republishes automatically
```

Then on the NAS: **Apps → mastarr → ⋮ → Pull image**, or just **Restart**. Your `/data`
volume persists, so services, users and settings survive the update.

---

## Reverse proxy (optional)

To reach Mastarr over TLS, point your proxy (Nginx Proxy Manager, Traefik, Caddy) at
`YOUR_NAS_IP:8770`.

The session cookie is deliberately **not** marked `Secure`, because that would silently
break plain-HTTP LAN access — the common case for a homelab. Terminate TLS at the proxy;
nothing in Mastarr needs changing.

---

## Troubleshooting

**App won't start — logs show `The data directory /data is not writable`**
Ownership mismatch, the most common failure. The error tells you the exact uid Mastarr is
running as. Either `chown -R <that uid>:<that gid> /mnt/YOURPOOL/apps/mastarr`, or change
`user:` in the YAML to match whoever already owns the directory.

**`Failed 'up' action` → `invalid reference format: repository name must be lowercase`**
Your `image:` line has capital letters. Docker image names must be **entirely lowercase**,
even though GitHub usernames often aren't. GHCR lowercases them for you, so a user named
`BanishedBumHunter` publishes to `ghcr.io/banishedbumhunter/mastarr:latest`. Lowercase the
whole line and reinstall.

**`denied` / `403` / `manifest unknown` when pulling the image**
The GHCR package is private — see 2.3. (If your repo is public, it won't be.) Or the
username in `image:` is misspelled.

**Anything else, on TrueNAS specifically**
The real error is in the app lifecycle log, which the UI truncates to
`[EFAULT] Failed 'up' action`. Read it over SSH:
```bash
tail -20 /var/log/app_lifecycle.log
```
It names the actual cause — bad image reference, missing device, unreadable path.

**`image not found` and you used the manual `docker save` route**
`pull_policy: never` is set but the image was never loaded onto the NAS. Check with
`docker images | grep mastarr` over SSH.

**Everything shows "Unreachable"**
Mastarr can't reach your *arr services. Test from the NAS itself:
```bash
curl -s http://YOUR_ARR_IP:8989/ping     # expect {"status":"OK"}
```
If that fails, the URL is wrong or the service isn't exposed. Remember each TrueNAS app is
its own compose project — use IP addresses, **not** container names like `http://sonarr:8989`.

**Services show "Needs API key" even after adding one**
Look at the card's error text. *"No API key configured"* means it didn't save; *"API key
was rejected"* means the key is wrong — recopy it from the service's settings page.

**Logged out after an update, or API keys stopped working**
`MASTARR_JWT_SECRET` / `MASTARR_SECRET_KEY` changed between deployments. Set them
explicitly in the YAML (3.3) so they survive.

**Port 8770 already in use**
Change the *left* number only: `"8771:8000"`. The right side is inside the container and
must stay `8000`.

---

## Alternative: install without GitHub

If you'd rather not publish anything, transfer the image directly over SSH:

```bash
docker build -f backend/Dockerfile -t mastarr:latest .
docker save mastarr:latest | ssh USER@YOUR_NAS 'docker load'
```

Then in the YAML, replace the `image:` line with these two:

```yaml
    image: mastarr:latest
    pull_policy: never
```

Everything else is identical. The trade-off is that each update means repeating the
`save | load` by hand.
