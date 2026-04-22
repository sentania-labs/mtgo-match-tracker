# Manalog — deploy guide

MVP stack: Caddy + FastAPI + Postgres + a Windows tray agent that
heartbeats back. No match ingest yet; this deploy validates the wire.

## Prereqs

- Docker + Docker Compose
- A hostname (`mtgo.int.sentania.net` or similar) resolving to the host
- An internal-CA cert + key for that hostname (lab mode) **or** ports
  80/443 routable from the internet (public / Let's Encrypt mode)

## 1. Clone + env

```sh
git clone https://github.com/sentania-labs/mtgo-match-tracker.git
cd mtgo-match-tracker
cp .env.example .env
```

Edit `.env`:

```
DB_PASSWORD=<something-long-and-random>
SECRET_KEY=<32+ random bytes; openssl rand -hex 32>
TLS_MODE=manual                      # or "auto" for Let's Encrypt
TLS_DOMAIN=mtgo.int.sentania.net     # the hostname you chose
ADMIN_USERNAME=scott
ADMIN_PASSWORD=<pick a password>
ADMIN_EMAIL=scott@sentania.net
HTTP_PORT=80                         # bump if 80/443 are taken
HTTPS_PORT=443
```

`ADMIN_USERNAME` / `ADMIN_PASSWORD` seed the first user on boot when
the `users` table is empty. Safe to remove from `.env` after the user
exists — bootstrap is a no-op on subsequent startups.

`TEST_USERNAME` / `TEST_PASSWORD` / `TEST_EMAIL` seed a second
non-admin user on first boot, with the same semantics as the ADMIN
block: only seeded when the `users` table is empty, and skipped (with
a warning) if the env vars aren't set. Use this for the agent so it
doesn't register as admin.

## 2. Drop the cert (manual TLS only)

```sh
docker volume create manalog-certs
docker run --rm -v manalog-certs:/certs -v "$PWD":/in alpine \
  sh -c 'cp /in/cert.pem /certs/cert.pem && cp /in/key.pem /certs/key.pem'
```

Skip this step for `TLS_MODE=auto` — Caddy's ACME handler populates
`caddy-data` on first connection.

## 3. Bring it up

```sh
docker compose up -d
docker compose logs -f app          # watch alembic migrate + uvicorn start
```

The `app` container's entrypoint runs `alembic upgrade head` before
starting uvicorn, so no manual migration step is needed.

## 4. Verify

From the host:

```sh
curl -fsS https://mtgo.int.sentania.net/healthz
# → {"status":"ok","db":"ok"}
```

If `TLS_MODE=manual` with an internal CA, add `--cacert` or set up
the CA bundle on the client.

Check the admin user exists:

```sh
docker compose exec db psql -U mtgo mtgo_tracker -c \
  "SELECT username, email, created_at FROM users;"
```

## 5. Agent

Grab the latest `Manalog.exe` from GitHub Releases on a
Windows box. On first launch the tray icon prompts for server URL,
username, password. Config lives in
`%APPDATA%\Manalog\config.toml`.

Verify the heartbeat is landing:

```sh
docker compose exec db psql -U mtgo mtgo_tracker -c \
  "SELECT machine_name, platform, last_seen FROM agent_registrations;"
```

`last_seen` should advance roughly every 60s (configurable via the
`[heartbeat]` section in the agent's `config.toml`).

## Installing the Windows agent

The Manalog Windows agent monitors your MTGO log directory and uploads match
results to the server automatically.

### Download

Download `Manalog.msi` (and `Manalog.msi.sha256`) from the [latest GitHub Release](https://github.com/sentania-labs/manalog/releases/latest).

Verify the checksum before installing:
```powershell
(Get-FileHash Manalog.msi -Algorithm SHA256).Hash.ToLower()
# Compare against the contents of Manalog.msi.sha256
```

### Install

Double-click `Manalog.msi`. The installer:
- Installs `Manalog.exe` to `C:\Program Files\Manalog\`
- Creates `%PROGRAMDATA%\Manalog\` for config and logs
- Adds a Startup folder shortcut so the agent starts at login

**SmartScreen warning (beta):** The MSI is currently unsigned. Click "More info → Run anyway" to proceed. This warning will be resolved when the release is code-signed.

### First launch

On first run, a dialog prompts for your server URL and credentials. Enter
the URL of your Manalog server (e.g. `https://mtgo.int.sentania.net`) and
your Manalog username and password. The agent registers itself and stores
only the bearer token — your password is never saved locally.

### Uninstall

Use Windows Settings → Apps → Manalog → Uninstall, or `msiexec /x Manalog.msi`.
The `%PROGRAMDATA%\Manalog\` directory (config, logs) is preserved on uninstall.

### Three items awaiting Scott's decision

1. **Code-signing certificate** — unsigned MSI triggers SmartScreen. Acquiring an EV code-signing cert removes the warning for end users. Ballpark cost: ~$300–500/year.
2. **Service vs. startup shortcut** — the current installer uses a Startup folder shortcut (per CLAUDE.md). If a Windows Service (headless, starts before login) is preferred, the `agent/windows-service-wrapper` branch adds `agent/service.py`; the installer would need a `ServiceInstall` element and elevated privilege grant. Revisit after beta.
3. **WiX toolchain in CI** — WiX v4 is installed via `dotnet tool install --global wix` on `windows-latest`. If the team prefers a vendored/pinned version, lock with `--version <x.y.z>`.

## Game-log archive

Phase A of the agent ships every `.dat` / `.log` it sees to the server
verbatim — no parsing. Parsing happens later, against the archive. The
rationale is that parser improvements can reprocess any historical match
without asking the user to re-export logs.

### Server-side layout

Files land on disk under `GAMELOG_ARCHIVE_ROOT` (env var, default
`/data/manalog/gamelogs`):

```
/data/manalog/gamelogs/
└── <manalog-username>/
    └── <YYYY-MM>/
        └── <sha256>.dat        # or .log
```

One row per unique sha256 in the `game_log_archive` table. The bytes
themselves are on disk, not in Postgres. The DB row records who
uploaded it, when it was captured (file mtime), file size, type, and
the relative stored_path.

### Endpoint

```
POST /api/v1/agent/gamelogs/upload
```

Multipart form: `file` (bytes) + `metadata` (JSON string with
`original_name`, `file_type` ∈ {`dat`, `log`}, `captured_at` ISO8601,
`size`, `sha256`). Requires the same bearer token as the existing
agent endpoints. Returns `201 Created` on first-upload, `200 OK` on a
sha-dedup hit; in both cases the body carries `upload_id`, `sha256`,
`stored_path`, and `created` (boolean).

### Configuration

```
GAMELOG_ARCHIVE_ROOT=/data/manalog/gamelogs
```

Add to `.env`. The app container must have write access to this path.
For Docker deployments, mount a host directory or named volume at the
configured path — e.g. a `manalog-gamelogs` named volume in
`docker-compose.yml` (or a bind mount onto a NAS-backed directory).

### Backup

Everything the server retains for archival purposes lives under this
one directory. `rsync -a --delete /data/manalog/gamelogs/ backup-host:/…`
is sufficient. Pair with a nightly `pg_dump` of Postgres — that covers
the index row referencing each stored file.

### Agent state DB

The Phase A shipper keeps its own local sqlite at:

- Windows: `%APPDATA%\Manalog\upload_state.db`
- Linux (dev): `~/.config/manalog/upload_state.db`

Schema:

```sql
CREATE TABLE uploaded_files (
  sha256           TEXT PRIMARY KEY,
  original_path    TEXT NOT NULL,
  uploaded_at      TEXT NOT NULL,
  server_upload_id INTEGER,
  status           TEXT NOT NULL  -- 'uploaded' | 'pending' | 'failed'
);
```

Inspect via `sqlite3 upload_state.db 'SELECT * FROM uploaded_files;'`.
Safe to delete: the server will dedup on sha256, so worst-case the
agent re-uploads everything on next run and the server returns 200s.

### Single-instance guard

When both the Windows service and the tray shortcut are installed,
only one is allowed to run. The first to acquire
`%LOCALAPPDATA%\Manalog\instance.lock` (PID file with stale detection)
wins; the second logs and exits cleanly. The service starts before
login and normally holds the lock.

## Troubleshooting

- **Healthz returns 503 with `db: unreachable`**: the app can't reach
  Postgres. `docker compose logs db` and verify the healthcheck
  is passing.
- **Agent registration 401 from a known-good password**: users table
  empty on first boot because `ADMIN_USERNAME` wasn't set. Restart the
  app container after adding it to `.env`, OR create a user
  manually with `docker compose exec app python -c '...'` (bcrypt +
  insert).
- **Caddy fails to start in manual mode**: cert/key not readable at
  `/certs/cert.pem` + `/certs/key.pem`. `docker compose logs caddy`.
- **Windows agent trusts no certs in lab mode**: either install the
  internal CA root in the Windows trust store, or set
  `tls_verify = "C:\\path\\to\\ca.pem"` in the agent's config.toml.

## What's NOT in this MVP

- Match ingest — the upload endpoint accepts payloads but does not
  persist them yet.
- Stats / matchup API — routes exist, bodies 501.
- Web UI — no user-facing pages beyond `/docs`.
- Agent self-update download + apply — the agent checks GitHub
  Releases and notifies, but does not download or restart.
- Multi-user signup — there is only the bootstrap user. No signup
  page, no password reset.

## Rolling updates

```sh
git pull
docker compose build app caddy
docker compose up -d
```

Agent updates are manual for MVP: download the new `.exe` from the
Release and replace the installed copy.

## Upgrading from v0.2.0 (tamiyo-named volumes)

v0.3.0+ renamed the Docker project and named volumes from `tamiyo-*`
to `manalog-*`. Fresh deployments pick up the new names automatically
— no action needed. Operators upgrading an existing v0.2.0 deployment
in place must copy the volume contents before `docker compose up` on
the new release, or the stack will start against empty volumes.

```sh
docker volume create manalog-db
docker run --rm -v tamiyo-db:/src -v manalog-db:/dst alpine cp -a /src/. /dst/
# repeat for certs, caddy-data, caddy-config
docker volume create manalog-certs
docker run --rm -v tamiyo-certs:/src -v manalog-certs:/dst alpine cp -a /src/. /dst/
docker volume create manalog-caddy-data
docker run --rm -v tamiyo-caddy-data:/src -v manalog-caddy-data:/dst alpine cp -a /src/. /dst/
docker volume create manalog-caddy-config
docker run --rm -v tamiyo-caddy-config:/src -v manalog-caddy-config:/dst alpine cp -a /src/. /dst/
```

Once verified, the old `tamiyo-*` volumes can be removed with
`docker volume rm`.
