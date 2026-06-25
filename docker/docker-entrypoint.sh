#!/bin/bash
set -e

# ── SQLite support ──────────────────────────────────────────────────────────
# If using SQLite, ensure the parent directory for the database file exists.
if [[ "$DATABASE_URL" == sqlite* ]]; then
    DB_PATH="${DATABASE_URL#sqlite:///}"
    mkdir -p "$(dirname "$DB_PATH")"
fi

# ── Migrations ──────────────────────────────────────────────────────────────
echo "→ Running database migrations..."
uv run flask db upgrade

# ── Seed (first-run only) ───────────────────────────────────────────────────
# If the users table is empty, seed baseline data.
echo "→ Checking if seed data is needed..."
if uv run python -c "
from app import create_app
from app.models import User
app = create_app()
with app.app_context():
    exit(0 if User.query.count() == 0 else 1)
"; then
    echo "→ Seeding baseline data..."
    uv run flask seed
else
    echo "→ Database already contains data, skipping seed."
fi

# ── Start ───────────────────────────────────────────────────────────────────
echo "→ Starting gunicorn..."
exec "$@"
