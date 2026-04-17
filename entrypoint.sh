#!/bin/sh
set -e

# Wait for DB + apply migrations before handing control to uvicorn.
# compose's depends_on already waits for the pg_isready healthcheck,
# so a single attempt here is normally enough.
alembic upgrade head

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
