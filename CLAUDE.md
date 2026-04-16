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

## Tech Stack

| Component | Choice |
|-----------|--------|
| Backend | FastAPI (Python 3.12+) |
| Database | PostgreSQL 16 |
| ORM / Migrations | SQLAlchemy 2.0 (async) + Alembic |
| Frontend | Jinja2 templates + HTMX + Chart.js |
| CSS | Pico CSS |
| MTGO Agent | Python (watchdog + httpx), packaged via PyInstaller |
| Container | Docker Compose (app + db) |

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
│   ├── watcher.py        # Filesystem watcher (watchdog)
│   ├── parser.py         # Binary .dat file parser
│   ├── sender.py         # API client (httpx)
│   └── main.py           # Agent entry point
├── alembic/              # Database migrations
├── tests/                # pytest tests
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── requirements.txt
└── CLAUDE.md
```

## Data Model (7 tables)

- **archetypes** — reference table synced from external sources (name, aliases, format, colors, key_cards, source)
- **matches** — match results from MTGO logs or manual entry (format, match_type, opponent, archetypes, result, event info)
- **games** — per-game within a match (on_play, mulligans, turn_count, winner)
- **plays** — turn-by-turn card actions from MTGO logs (turn, caster, action_type, card_name, targets). Critical for key card analysis.
- **decklists** — tracked deck lists with maindeck/sideboard as JSONB
- **drafts** — draft session metadata
- **picks** — individual draft picks with alternatives

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
