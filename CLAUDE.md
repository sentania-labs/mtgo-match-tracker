# CLAUDE.md — MTGO Match Tracker (Tamiyo)

Track Magic: The Gathering Online match results, analyze matchups, and improve your game with data.

## Project Overview

Docker-hosted web app (FastAPI + PostgreSQL + HTMX) with a companion Windows agent that auto-captures MTGO match results from game logs. Supports manual entry for paper events. Integrates external metagame data (TopDeck.gg, MTG Top 8, MTG Goldfish) for archetype classification and meta context.

## Hard Rules

1. **No Moxfield integration.** Their ToS explicitly prohibits scraping. Do not add Moxfield API calls, scraping, or imports.
2. **Never store credentials in code.** API keys, DB passwords, and secrets go in `.env` (gitignored) or environment variables only. Never commit `.env`.
3. **Card names are canonical.** Use official Oracle names from Scryfall. Don't invent card names or accept unvalidated user input as card references without validation.
4. **Archetype classification is probabilistic.** Always allow manual override. Never present auto-classified archetypes as certain without user confirmation.
5. **Multi-agent safe.** Multiple MTGO agents may send data for the same player from different PCs. Dedup matches by `mtgo_match_id`. Never assume one agent = one player.
6. **SSL on all endpoints. Non-negotiable.** The FastAPI server and the agent communication channel must support TLS. Design for this from day 1 — not bolted on later. No HTTP-only production paths.
7. **Data model is user-scoped from day 1.** All tables that hold match/game/deck/draft data must have a `user_id` FK. No single-user assumptions in schema or API. The multi-user UI can come later; the schema cannot be retrofitted.

## Tech Stack

| Component | Choice |
|-----------|--------|
| Backend | FastAPI (Python 3.12+) |
| Database | PostgreSQL 16 |
| ORM / Migrations | SQLAlchemy 2.0 (async) + Alembic |
| Frontend | Jinja2 templates + HTMX + Chart.js |
| CSS | Pico CSS |
| Reverse Proxy / TLS | Caddy 2 (terminates TLS; proxies to uvicorn) |
| MTGO Agent | Python (watchdog + httpx + pystray), packaged via PyInstaller — **tray service** (see below) |
| Container | Docker Compose (caddy + app + db) |

## TLS Architecture

TLS terminates at Caddy, not uvicorn directly. Three deployment modes:

| Mode | When | How |
|------|------|-----|
| `manual` | Lab/internal | Drop in cert + key (internal CA). Caddy serves them; no ACME involved. |
| `auto` | Public internet | Caddy ACME with Let's Encrypt. Domain required. Port 80/443 must be reachable. |
| `off` | Dev/test only | HTTP-only. Never in production. |

### Internal CA (lab deployment)

Use the lab's internal CA to issue a cert for the tracker's hostname (e.g., `mtgo.int.sentania.net`). Drop the cert/key pair into a Docker named volume (e.g., `tamiyo-certs/`) and point Caddy's manual config at `/certs/cert.pem` and `/certs/key.pem`. Windows agents that need to trust the server must have the internal CA root installed in the Windows trust store (or explicitly trusted in httpx).

Navani (sentania-lab-toolkit) does not yet document internal CA issuance procedures — that's a gap to fill separately. When cert infra exists, reference it here.

### Let's Encrypt (public deployment)

Caddy handles ACME automatically when `tls_mode: auto` and a valid `tls_domain` are set. No manual cert management needed. Caddy stores ACME state in its data volume. The only prerequisite: port 80 and 443 routable from the internet.

Pattern borrowed from ScarGuard (`workspaces/scarguard/`) which uses a Caddy container as the TLS-terminating reverse proxy with a generated Caddyfile (from a template + Python config parsing at entrypoint). ScarGuard config reference: `services/caddy/`, `config/caddy-entrypoint.sh`, `CONFIG_REFERENCE.md` tls section.

### Agent-to-server TLS

The Windows agent (httpx client) posts to the server's HTTPS endpoint. In lab mode, the agent must trust the internal CA root — configure httpx with `verify=<ca_bundle_path>` or install the CA into the Windows system trust store. In public LE mode, the CA is already trusted by default.

## MTGO Agent — Tray Service Architecture

The Windows agent is a **system tray resident service** (Discord-style), not a CLI tool:

- Always running in the background after Windows login
- System tray icon with right-click context menu (Start/Stop monitoring, Open dashboard, About, Quit)
- Monitors MTGO log directory via watchdog
- Posts match results to the server via httpx (HTTPS)
- **Self-updates** from GitHub Releases (see below)
- Packaged via PyInstaller as a single-file executable with a Windows installer

### Tray implementation

Use **pystray** for tray icon + menu. Pair with a `threading.Thread` for the watchdog loop so the tray event loop stays responsive. PIL/Pillow required for the tray icon image.

### Self-update mechanism

**GitHub Releases** is the chosen approach (simpler; no server-side hosting required):

1. Agent checks the GitHub Releases API at startup and once per day
2. If a newer version tag is available, it downloads the asset, verifies a SHA256 checksum, replaces itself, and restarts via `subprocess` + `sys.exit()`
3. The tray menu exposes "Check for updates" manually
4. Update channel configurable (stable releases only vs. pre-releases)

Server-hosted updates (polling a `/api/v1/agent/version` endpoint) is a future option if tighter control is needed — design the update interface to be swappable.

### Agent registration and multi-desktop pairing

A single user may run agents on multiple PCs (desktop + laptop). Each agent instance registers with the server on first run, receiving an `agent_id` and storing it locally. Registration is bound to the user account, not the machine:

- `POST /api/v1/agent/register` — accepts `{user_id, machine_name, platform}`, returns `{agent_id, api_token}`
- Each agent carries its own `agent_id` in every upload payload
- Match dedup is by `mtgo_match_id` — same match from two agents is idempotent
- The server tracks which agent submitted each match (useful for debugging, not required for correctness)

Agent tokens are per-agent-instance. Revoking one agent does not revoke others for the same user.

## Project Structure

```
mtgo-match-tracker/
├── app/                  # FastAPI application
│   ├── api/              # Route modules
│   ├── models/           # SQLAlchemy models
│   ├── schemas/          # Pydantic request/response schemas
│   ├── services/         # Business logic (stats, archetype matching)
│   ├── templates/        # Jinja2 + HTMX templates
│   ├── static/           # CSS, JS (Chart.js), images
│   └── main.py           # FastAPI app entry point
├── agent/                # MTGO log agent (separate deployable)
│   ├── tray.py           # pystray tray icon + menu + thread orchestration
│   ├── watcher.py        # Filesystem watcher (watchdog)
│   ├── parser.py         # .dat / plaintext log parser (stub with extension points)
│   ├── sender.py         # API client (httpx, HTTPS, bearer auth)
│   ├── updater.py        # Self-update via GitHub Releases
│   ├── config.py         # Config load/save (%APPDATA%\MTGOMatchTracker\config.toml)
│   ├── assets/           # icon.ico for PyInstaller + tray
│   ├── requirements.txt  # pystray, Pillow, watchdog, httpx, semver, pyinstaller
│   └── main.py           # Agent entry point
├── alembic/              # Database migrations
├── tests/                # pytest tests
├── services/
│   └── caddy/            # Caddy reverse proxy (TLS termination)
│       ├── Dockerfile
│       ├── entrypoint.sh
│       └── Caddyfile.template
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── requirements.txt
└── CLAUDE.md
```

## Data Model (8 tables)

All tables holding user data carry a `user_id` FK to the `users` table.

- **users** — user accounts (id, username, email, hashed_password, created_at)
- **agent_registrations** — registered agent instances (id, user_id, agent_id UUID, machine_name, platform, api_token_hash, last_seen)
- **archetypes** — reference table synced from external sources (name, aliases, format, colors, key_cards, source) — not user-scoped
- **matches** — match results (user_id FK, format, match_type, opponent, archetypes, result, event info, submitted_by_agent_id)
- **games** — per-game within a match (match_id FK, on_play, mulligans, turn_count, winner)
- **plays** — turn-by-turn card actions (game_id FK, turn, caster, action_type, card_name, targets)
- **decklists** — tracked deck lists (user_id FK, maindeck/sideboard as JSONB)
- **drafts** — draft session metadata (user_id FK)
- **picks** — individual draft picks (draft_id FK, card, alternatives, pack, pick)

## External Data Sources

| Source | Type | Use | Frequency |
|--------|------|-----|-----------|
| TopDeck.gg | Official API v2 | Archetypes, tournaments | Daily |
| MTG Top 8 | Scrape | Historical archetypes | Weekly |
| MTG Goldfish | Scrape (light) | Metagame share % | Weekly |
| Scryfall | Official API | Card name validation | On demand |
| Moxfield | **PROHIBITED** | — | Never |

## API Base

`/api/v1` — OpenAPI docs auto-generated at `/docs`

Key endpoint groups: `/matches`, `/games`, `/decklists`, `/archetypes`, `/drafts`, `/stats/*`, `/agent/*`

Agent endpoints:
- `POST /agent/register` — user/pass auth; creates an `AgentRegistration` row, returns a cleartext bearer token once (hashed with SHA-256 at rest).
- `POST /agent/heartbeat` — bearer auth; bumps `last_seen`. MVP liveness signal.
- `POST /agent/upload` — bearer auth; bumps `last_seen`, acknowledges payload with 202. Match persistence is post-MVP.

All other `/agent/*` routes require Bearer auth via `get_current_agent`, which looks the SHA-256-hashed token up in `agent_registrations` and rejects missing/unknown/revoked tokens. User passwords use bcrypt (via the `bcrypt` library directly — passlib is unmaintained and incompatible with bcrypt ≥ 4.1).

### Bootstrap

When the `users` table is empty on app startup, the lifespan hook seeds one user from `ADMIN_USERNAME` / `ADMIN_PASSWORD` / `ADMIN_EMAIL` env vars. No-op once the table has rows. First-boot-only mechanism — there is no signup endpoint in MVP.

## Key Analysis Features

- **Key card win rates**: "Win X% of games where card Y is cast on turn Z"
- **Matchup matrix**: Win rates by my archetype vs opponent archetype
- **Play/draw analysis**: Win rate on play vs on draw
- **Mulligan analysis**: Mulligan rate correlation with wins
- **Trend tracking**: Win rate over time by format/archetype

## Testing Strategy

Philosophy: test the behavior users and agents depend on; mock everything external; don't write tests for the database ORM.

### What gets tested

| Layer | What | How |
|-------|------|-----|
| **API route smoke** | Every endpoint returns a sane status code | `httpx.AsyncClient` + `ASGITransport`, async pytest |
| **API behavior** | Correct response shape, dedup logic, user scoping | Same client; assert on response body |
| **Business logic** | Stats calculations, archetype matching, dedup | Pure unit tests, no I/O |
| **Model constraints** | UniqueConstraint on `(user_id, mtgo_match_id)` | SQLite in-memory via `aiosqlite` |
| **Integration** | Alembic migration runs clean; stack starts healthy | CI compose smoke test |

### What does NOT get tested

- SQLAlchemy ORM itself (trust the library)
- The database's query planner
- Trivial getters/setters with no logic

### Mocking strategy

Tests never touch a real PostgreSQL instance. Use:
- `aiosqlite` in-memory DB for tests that need real SQL behavior (constraints, FKs)
- `monkeypatch` / `unittest.mock` for external services (Scryfall, TopDeck.gg, archetype scrapers)
- Hardcoded dev user fixture replacing `get_current_user` dependency (already in place from scaffold)

### Test layout

```
tests/
├── conftest.py           # async client fixture, in-memory DB engine, dev user override
├── unit/
│   ├── test_dedup.py     # mtgo_match_id dedup logic
│   ├── test_stats.py     # win rate / matchup matrix calculations
│   └── test_archetype.py # archetype classification logic
└── integration/
    ├── test_routes_matches.py    # smoke + behavior for /api/v1/matches
    ├── test_routes_agent.py      # register + upload endpoints
    ├── test_routes_decklists.py
    ├── test_routes_drafts.py
    ├── test_routes_archetypes.py
    └── test_routes_stats.py
```

### Coverage gate

CI fails if overall coverage drops below **70%**. Routes and business logic must be covered; model boilerplate is excluded. Use `pytest-cov` with `--cov=app --cov-fail-under=70`.

### Running tests

```bash
# Local
pip install -r requirements-dev.txt
pytest tests/ -v --cov=app --cov-report=term-missing

# Inside container (mirrors CI)
docker compose exec app pytest tests/ -v
```

## CI/CD

### Runner layout (from ScarGuard pattern)

All runners are self-hosted. Three runner labels in use:

| Label | Runner | Used for |
|-------|--------|----------|
| `[self-hosted, linux, generic]` | Lightweight x86 container | Lint, typecheck, pytest |
| `[self-hosted, linux, docker]` | x86 with Docker socket | Docker builds, Trivy, compose smoke test |

No Jetson/ARM runner needed (no GPU workloads). Multi-arch builds (amd64 + arm64) via QEMU emulation on the docker runner for future ARM deployment flexibility.

### Workflow layout (5 files)

**`ci.yml`** — runs on PR only:
- Lint (ruff — `app/` and `tests/`)
- Type check (mypy — `app/`)
- pytest with coverage gate (≥70%)

**`build.yml`** — runs on PR and main-push:
- PR: multi-arch build + load for test + in-container pytest + Trivy CVE scan (CRITICAL/HIGH) + compose smoke test
- main-push: multi-arch build only (warms GHA cache; tests already passed on the PR)

**`release.yml`** — runs on `v*.*.*` tag push:
- `release-app` / `release-caddy` jobs build and push multi-arch images to GHCR (`ghcr.io/sentania-labs/tamiyo-*`); tags: semver + latest
- `build-agent-release` job builds the Windows agent exe on `windows-latest` and uploads it as a workflow artifact
- `create-release` job (needs all three above) downloads the Windows artifact and creates the GitHub Release with auto-generated notes + exe + sha256 attached atomically

**`windows-agent-build.yml`** — PR only:
- `windows-latest` GitHub-hosted runner (no self-hosted needed for agent builds)
- Builds the exe via PyInstaller as a sanity check and uploads as workflow artifact (30-day retention)
- Tag-path agent build now lives inside `release.yml` (see above) — this workflow deliberately has no tag trigger so there is no race with the release job

**`cleanup.yml`** — weekly Sunday 03:00 UTC:
- `docker system prune -f` + `docker builder prune --keep-storage 5GB` on each runner

### Token scoping (CodeQL-safe)

Default `permissions: contents: read` at workflow level. Per-job blocks elevate only where needed:
- `packages: write` for image push jobs
- `contents: write` for release creation

### Build caching

GHA cache (`type=gha`) scoped per image (`scope=app`, `scope=caddy`). On main-push, build warms cache even though tests are skipped.

### Trivy scanning

Fail on CRITICAL and HIGH CVEs with known fixes. Use `ignore-unfixed: true` to suppress noise from unfixable base-image CVEs. Run Trivy before in-container tests (fail fast).

### Compose smoke test

Runs after all image builds pass. Seeds minimal `.env` (TLS_MODE=off), starts the stack, polls `/healthz` until healthy, tears down. Tests run in DinD (Docker-in-Docker) — use `docker create + cp` not bind mounts for injecting test files.

## MTGO Agent — Phase 2 Detail

### File layout

```
agent/
├── main.py          # Entry point: init config, start tray
├── tray.py          # pystray tray icon + menu + thread orchestration
├── watcher.py       # watchdog filesystem monitor on MTGO log dir
├── parser.py        # .dat / plaintext log parser (stub; see below)
├── sender.py        # httpx async client, bearer auth, TLS
├── updater.py       # GitHub Releases self-update
├── config.py        # Config load/save to %APPDATA%\MTGOMatchTracker\config.toml
└── requirements.txt # pystray, Pillow, watchdog, httpx, tomli/tomllib, semver, pyinstaller
```

### Config file

Location: `%APPDATA%\MTGOMatchTracker\config.toml`

```toml
[server]
url = "https://mtgo.int.sentania.net"   # server base URL
tls_verify = true                        # set false for self-signed lab cert

[agent]
agent_id = ""          # UUID assigned at registration; empty = not yet registered
api_token = ""         # bearer token; empty = not yet registered
machine_name = ""      # human-readable label for this desktop

[mtgo]
log_dir = "C:\\Users\\<user>\\AppData\\Local\\Apps\\2.0\\<mtgo>\\GamingAudioInterop"
# ^ default MTGO log directory; user can override

[updates]
check_interval_hours = 1
include_prereleases = false
github_token = ""      # optional; needed if repo is private
```

Config is loaded at startup and written atomically (write to `.tmp`, rename). Never store user passwords in config — only the registration token issued by the server.

### Windows startup

Use a Startup folder shortcut (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`) rather than a registry Run key. Less invasive, user can easily disable by removing the shortcut, and does not require elevated privileges to install.

### Tray menu

```
[icon] MTGO Match Tracker
  ├── Status: Monitoring / Paused / Not registered
  ├── ────────────────────
  ├── Pause Monitoring      (toggles to Resume when paused)
  ├── Open Dashboard        (opens server URL in browser)
  ├── ────────────────────
  ├── Check for Updates
  ├── Settings...           (opens config file in default editor)
  ├── Open Log              (opens current log file in default editor)
  ├── ────────────────────
  └── Quit
```

If not yet registered, "Status" shows "Not registered" and clicking it opens the registration dialog.

### Registration flow

On first launch with no `agent_id` in config:
1. Show a simple `tkinter` dialog (single-file, no extra dep) prompting for server URL + username + password.
2. POST to `{server_url}/api/v1/agent/register` with `{username, password, machine_name, platform: "windows"}`.
3. On success, store `agent_id` and `api_token` in config. Never store password.
4. Subsequent launches skip registration.

Pairing token flow (alternative): server can pre-generate a token; user pastes it into the dialog instead of typing credentials. Both paths call the same endpoint — the server disambiguates by payload shape.

### Parser stub — MTGO log format

The exact `.dat` binary format is not yet reverse-engineered. The parser is a **typed stub** that:
- Defines `ParsedMatch`, `ParsedGame`, `ParsedPlay` dataclasses matching the server's upload schema
- Reads the MTGO `GameLog*.dat` binary file, logs `TODO: reverse-engineer .dat format`, and returns `None`
- Falls back to reading MTGO's plaintext `.log` files in the same directory, extracting a minimal match result (winner/loser lines) as a partial `ParsedMatch`
- Extension point: `parser.py` exports `parse_dat_file(path) -> ParsedMatch | None` and `parse_text_log(path) -> ParsedMatch | None`; `watcher.py` calls both and takes the richer result

**Research brief (2026-04-18):** `docs/research/2026-04-18-mtgo-log-structure.md` — initial format research from public sources.

**Phase 2.5 plan (2026-04-18):** `docs/plans/2026-04-18-phase-2.5-parser-and-quarantine.md` — actionable plan refined against 358 real `.dat` samples. Drops the BigPeet bridge (direct text extraction works), corrects the brief's win/loss claims, adds the dead-letter quarantine workflow (`unparsed_logs` table + `/agent/upload-unparsed` endpoint) so undocumented format edge cases get captured for parser improvement instead of silently dropped.

### Self-update flow

1. On startup and every `check_interval_hours`, fetch `https://api.github.com/repos/sentania-labs/mtgo-match-tracker/releases/latest` (auth header if `github_token` set).
2. Compare latest tag semver against `__version__` (baked in by PyInstaller build).
3. If newer: download the `MTGOMatchTracker.exe` release asset, verify SHA256 against `MTGOMatchTracker.exe.sha256` asset.
4. Write new exe to `%TEMP%\MTGOMatchTracker_update.exe`.
5. Show tray notification "Update available — restart to apply." Tray menu gains "Restart to Update" item.
6. On user confirmation: `subprocess.Popen([new_exe])` then `sys.exit(0)`. The new exe launches, replaces the old file in place.

If checksum fails: discard download, log error, notify user.

### Sender TLS behavior

```python
# TLS_VERIFY from config:
# true  → httpx default (system trust store, or bundled cacert.pem from PyInstaller)
# false → httpx verify=False (lab with self-signed; warns loudly in log)
# "/path/to/ca.pem" → httpx verify=path (custom CA bundle)
```

### PyInstaller build

```bash
pyinstaller \
  --onefile \
  --windowed \          # no console window on Windows
  --name MTGOMatchTracker \
  --icon agent/assets/icon.ico \
  agent/main.py
```

`--windowed` suppresses the console window that would flash on startup. The tray icon IS the UI.

Add `agent/assets/icon.ico` — a placeholder 16x16 / 32x32 multi-res icon (can be programmatically generated with Pillow if no .ico file exists yet).

### Windows agent build workflow

Split across two workflows to eliminate a tag-push race:

- **PR path** — `.github/workflows/windows-agent-build.yml`, trigger `pull_request` to main. Builds the exe on `windows-latest` and uploads as a 30-day workflow artifact. Sanity check only; no release interaction.
- **Release path** — `build-agent-release` job inside `.github/workflows/release.yml`. Triggered on `v*.*.*` tag push. Builds the exe + `certutil -hashfile` checksum on `windows-latest`, uploads as a short-lived workflow artifact. The `create-release` job then downloads the artifact and `softprops/action-gh-release@v2` creates the Release with both files attached atomically — no chance of the Release existing without the exe or vice versa.

## Development

```bash
# Start the stack
docker compose up -d

# Run migrations
docker compose exec app alembic upgrade head

# Run tests locally
pytest tests/ -v --cov=app --cov-report=term-missing

# Lint + type check (mirrors CI)
ruff check app/ tests/
mypy app/ --ignore-missing-imports

# View logs
docker compose logs -f app
```

## Formats Focus

All constructed formats supported. Primary: Vintage, Legacy, Modern. Scott also plays Pioneer, Pauper, Standard on occasion. Paper events (FNM, prereleases, local tournaments) entered manually.
