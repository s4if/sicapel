# Developer Notes — SICAPEL

## Prerequisites

- **Python >= 3.12** (see `.python-version`)
- **uv** (package manager) — install via <https://docs.astral.sh/uv/#installation>
- **System dependencies for WeasyPrint** (PDF generation):

```sh
sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0 libcairo2 gir1.2-rsvg-2.0
```

## Quick Start

```sh
# 1. Clone and enter the project
git clone <repo-url> sicapel
cd sicapel

# 2. Create virtualenv and install all dependencies (including dev)
uv sync

# 3. Copy environment template (edit as needed)
cp .env.example .env

# 4. Create the database & apply migrations
uv run flask db upgrade

# 5. Seed baseline master data (categories, admin user, violation types, academic year)
uv run flask seed

# 6. (Optional) Seed comprehensive dev data — 21 students, 3 classes, teachers,
#    violation records, SP letters, and amnesties
uv run flask seed --dev

# 7. Run the dev server
uv run flask run --debug
```

The app is now available at <http://127.0.0.1:5000>.

## Login Credentials

| Role | Email | Password |
|---|---|---|
| Admin | `admin@sicapel.id` | `admin123` |
| Guru BK | `susi@sicapel.id` | `guru123` |
| Wali Kelas (X IPA 1) | `budi@sicapel.id` | `guru123` |
| Wali Kelas (XI IPA 1) | `siti@sicapel.id` | `guru123` |
| Wali Kelas (XII IPA 1) | `ahmad@sicapel.id` | `guru123` |

> Dev credentials only exist after running `uv run flask seed --dev`.

## Database

### SQLite (default for development)

The dev database lives at `instance/sicapel.sqlite` (gitignored). To reset:

```sh
rm -f instance/sicapel.sqlite
uv run flask db upgrade
uv run flask seed --dev
```

### PostgreSQL (production)

Set `DATABASE_URL` in `.env`:

```
DATABASE_URL=postgresql://user:password@localhost:5432/sicapel
```

## Seed Commands

| Command | What it does |
|---|---|
| `uv run flask seed` | Baseline: 4 categories, 1 admin, 13 violation types, 1 active academic year. Idempotent. |
| `uv run flask seed --dev` | Everything above + 4 teachers, 3 classes, 21 students, 27 violations, 3 SP letters, 5 amnesties. Idempotent. |
| `uv run flask seed --admin-email=... --admin-password=... --year=...` | Custom admin credentials and academic year. |

## Running Tests

```sh
# All tests
uv run pytest

# Specific test files
uv run pytest tests/test_services.py -v
uv run pytest tests/test_letter_numbering.py -v

# With coverage
uv run pytest --cov=app
```

Tests use an in-memory SQLite database and are independent of any seeded data.

## Linting

```sh
uv run ruff check .
uv run ruff format --check .
```

## Migrations

```sh
# After changing models.py:
uv run flask db migrate -m "description of changes"
uv run flask db upgrade

# Check current migration state
uv run flask db current
```

## Project Layout

```
sicapel/
├── app/
│   ├── __init__.py        # create_app() factory
│   ├── models.py          # 12 SQLAlchemy models
│   ├── forms.py           # WTForms
│   ├── services.py        # domain logic (violation recording, amnesty, PDF)
│   ├── seed.py            # CLI seed command
│   ├── helper.py          # hx_render, sanitize, role decorators
│   ├── blueprints/        # 11 Flask blueprints
│   ├── templates/         # Jinja2 templates (Bootstrap 5)
│   └── static/            # CSS, JS
├── instance/              # gitignored — dev SQLite, uploads, config.py
├── migrations/            # Alembic
├── tests/                 # pytest suite
├── pyproject.toml         # dependencies & tool config
├── .flaskenv              # FLASK_APP=app
├── .env.example           # template for .env
└── .python-version        # Python 3.12
```

## Common Tasks

### Reset everything to a clean state

```sh
rm -rf instance/ migrations/versions/
uv run flask db init
uv run flask db migrate -m "initial"
uv run flask db upgrade
uv run flask seed --dev
```

### Add a new Python dependency

```sh
uv add <package-name>       # runtime dependency
uv add --group dev <pkg>    # dev-only dependency
```

Commit both `pyproject.toml` and `uv.lock`.
