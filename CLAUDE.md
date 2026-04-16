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
│   ├── tray.py           # pystray tray icon + menu
│   ├── watcher.py        # Filesystem watcher (watchdog)
│   ├── parser.py         # Binary .dat file parser
│   ├── sender.py         # API client (httpx, HTTPS)
│   ├── updater.py        # Self-update via GitHub Releases
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

Agent endpoints (`/agent/*`) require Bearer token auth (token issued at agent registration).

## Key Analysis Features

- **Key card win rates**: "Win X% of games where card Y is cast on turn Z"
- **Matchup matrix**: Win rates by my archetype vs opponent archetype
- **Play/draw analysis**: Win rate on play vs on draw
- **Mulligan analysis**: Mulligan rate correlation with wins
- **Trend tracking**: Win rate over time by format/archetype

## Development

```bash
# Start the stack
docker compose up -d

# Run migrations
docker compose exec app alembic upgrade head

# Run tests
docker compose exec app pytest

# View logs
docker compose logs -f app
```

## Formats Focus

All constructed formats supported. Primary: Vintage, Legacy, Modern. Scott also plays Pioneer, Pauper, Standard on occasion. Paper events (FNM, prereleases, local tournaments) entered manually.
