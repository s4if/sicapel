# SICAPEL — Implementation Plan (Sole Source of Truth)

> **This is the only authoritative document for SICAPEL implementation.**
> All earlier planning drafts (V1/V2/V3) and the rendering-pattern reference have
> been consolidated and de-conflicted here. Where prior drafts disagreed, the
> decision recorded in this document wins.
>
> **Scope:** A traditional server-rendered Flask webapp for recording student
> disciplinary violations on a point system, with automated warning-letter
> (SP1/SP2/SP3) and expulsion-recommendation issuance, point amnesty, and a
> monitoring dashboard.
>
> **How to read this document:** top to bottom. Section order mirrors dependency
> order — domain → data → stack → architecture → patterns → tasks.

---

## Table of Contents

1. [Domain & Business Rules](#1-domain--business-rules)
2. [Database Design (12 tables)](#2-database-design-12-tables)
3. [Tech Stack (Final)](#3-tech-stack-final)
4. [Architecture Decisions](#4-architecture-decisions)
5. [Project Structure](#5-project-structure)
6. [Rendering Pattern — Core Rules (R1–R11)](#6-rendering-pattern--core-rules-r1r11)
7. [App Factory & Helper Layer](#7-app-factory--helper-layer)
8. [Service Layer Contract](#8-service-layer-contract)
9. [Blueprint Pattern](#9-blueprint-pattern)
10. [Template Conventions](#10-template-conventions)
11. [PDF Generation](#11-pdf-generation)
12. [File Uploads](#12-file-uploads)
13. [Testing Strategy](#13-testing-strategy)
14. [Implementation Order (T1–T20)](#14-implementation-order-t1t20)
15. [Risks & Mitigations](#15-risks--mitigations)
16. [Open Items](#16-open-items)

---

## 1. Domain & Business Rules

### 1.1 Actors

- **Admin** — manages master data & users.
- **Guru BK** (counseling teacher) — inputs violations, prints letters, inputs amnesties; full data access.
- **Wali Kelas** (homeroom teacher) — inputs violations **only for students in their class**.

The principal (kepala sekolah) is **not** a system user; their name is recorded as a string on amnesty letters.

### 1.2 Violation Categories & Points

| Category | Point Range | Example |
|---|---|---|
| Ringan (light) | 5–25 | Late, unkempt haircut |
| Menengah (medium) | 25–50 | Gadget misuse, skipping class |
| Berat (heavy) | 51–75 | Smoking, fighting |
| Sangat Berat (very heavy) | 200 (fixed) | Drugs → **immediate expulsion** |

### 1.3 Point Accumulation Rules

- Points accumulate **continuously** while a student is enrolled (no per-year/semester reset).
- Points **may go negative** (e.g. a student with many achievements receives large amnesties).
- **No upper bound** — points > 200 do **not** automatically trigger expulsion; they only surface as a dashboard alert.
- Correction of mistaken input uses soft-delete (`is_void=true`); voided records are excluded from point totals.

### 1.4 Warning Letter (SP) Escalation

A student's SP level progresses `null → SP1 → SP2 → SP3`. On a new violation:

| Category | Condition | Action |
|---|---|---|
| sangat_berat | (always) | Issue **expulsion recommendation** + set `student.status = expelled` |
| berat | current level `null` | Issue SP1 |
| berat | current level `1`/`2` | Escalate to SP2/SP3 |
| berat | current level `3` | Issue **expulsion recommendation** |
| menengah | already has SP | Escalate SP (same as berat) |
| menengah | no prior SP **and** total > 100 | Issue SP1 |
| menengah | no prior SP **and** total ≤ 100 | Points only |
| ringan | (always) | Points only |

After SP3, any further menengah/berat violation triggers expulsion.

### 1.5 Expulsion Triggers

Expulsion is triggered **only** by:
1. A sangat_berat violation (immediate), **or**
2. A menengah/berat violation committed after SP3.

Point accumulation alone (>200) **never** triggers expulsion.

### 1.6 Point Amnesty (Pemutihan)

- Granted by the principal, **input by Guru BK** on the principal's behalf.
- Reasons: achievement, good behavior, community service, etc.
- **A signed scanned letter is mandatory** (NOT NULL document reference).
- **No limit** on reduction amount — points may go negative.
- **Optional SP reset** via flag `sp_reset`:
  - `true` → `current_sp_level` reset to null (student is "clean" of active SP).
  - `false` → only points reduced; SP level unchanged.
  - Historical SP records in `warning_letters` are never deleted.

### 1.7 Letter Numbering

Format: `{seq:03d}/<TYPE>/BK/{year}` (e.g. `001/SP1/BK/2026`).
`letter_seq` resets per academic year. Allocation uses the optimistic
MAX+1 pattern with the `UNIQUE(academic_year_id, letter_seq)` constraint
as the concurrency backstop (see §8.3).

### 1.8 Dashboard Monitoring

Students with `total_points > 200` are highlighted on the Guru BK dashboard. This is a **display-only** alert; no automatic action.

---

## 2. Database Design (12 tables)

RDBMS: **PostgreSQL in production** (psycopg v3), **SQLite in dev/test** (via instance folder). Enum types render as native `ENUM` in PostgreSQL and `VARCHAR + CHECK` in SQLite — **validation always lives in WTForms/Python**, never rely on DB-level enum enforcement.

### 2.1 `academic_years`

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| year | string | e.g. "2026/2027" |
| start_date | date | |
| end_date | date | |
| is_active | bool | exactly one active row expected |
| created_at | timestamp | |

### 2.2 `users`

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| name | string | |
| email | string | UNIQUE |
| password_hash | string | bcrypt via passlib |
| role | enum | `admin` \| `guru_bk` \| `wali_kelas` |
| nip | string | |
| phone | string | |
| created_at, updated_at | timestamp | |

### 2.3 `classes`

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| name | string | e.g. "XI IPA 2" |
| grade_level | int | 10 \| 11 \| 12 |
| homeroom_teacher_id | FK → users | wali kelas |
| created_at | timestamp | |

### 2.4 `students`

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| nis | string | UNIQUE |
| nisn | string | |
| name | string | |
| gender | enum | `L` \| `P` |
| birth_place | string | |
| birth_date | date | |
| address | text | |
| photo_path | string | |
| class_id | FK → classes | current class only (v1 — historical enrollments deferred) |
| parent_name | string | |
| parent_phone | string | |
| status | enum | `active` \| `expelled` \| `graduated` \| `transferred` |
| enrolled_at | date | |
| created_at, updated_at | timestamp | |

### 2.5 `violation_categories`

Master data (seeded).

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| name | enum | `ringan` \| `menengah` \| `berat` \| `sangat_berat` |
| min_points | int | |
| max_points | int | |
| is_direct_expulsion | bool | true only for sangat_berat |
| description | text | |

Seed rows: ringan(5–25), menengah(25–50), berat(51–75), sangat_berat(200, is_direct_expulsion=true).

### 2.6 `violation_types`

Master list of violation kinds; admin-created.

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| category_id | FK → violation_categories | |
| name | string | e.g. "Terlambat", "Merokok" |
| default_points | int | suggestion, overridable at entry |
| description | text | |
| is_active | bool | |
| created_by | FK → users | |
| created_at, updated_at | timestamp | |

### 2.7 `violation_records` (core table)

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| record_number | string | auto-generated |
| student_id | FK → students | |
| violation_type_id | FK → violation_types | |
| category_id | FK → violation_categories | denormalized for fast filtering |
| points | int | actual value |
| chronology | text | sanitized |
| location | string | sanitized |
| incident_date | date | |
| incident_time | time | |
| academic_year_id | FK → academic_years | for reporting |
| semester | enum | `1` \| `2` |
| recorded_by | FK → users | guru BK / wali kelas |
| is_void | bool | default false — soft-delete for corrections |
| created_at, updated_at | timestamp | |

### 2.8 `documents`

Single table for all files (evidence + signed letter scans).

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| violation_record_id | FK → violation_records | nullable |
| warning_letter_id | FK → warning_letters | nullable |
| file_name | string | |
| file_path | string | absolute path under `UPLOAD_FOLDER` |
| mime_type | string | |
| file_size | int | bytes |
| document_type | enum | `evidence_photo` \| `evidence_video` \| `signed_warning_letter` \| `signed_statement_letter` \| `signed_amnesty_letter` |
| uploaded_by | FK → users | |
| created_at | timestamp | |

### 2.9 `warning_letters`

SP1/SP2/SP3 letters.

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| letter_number | string | e.g. "001/SP1/BK/2026" |
| letter_seq | int | per-academic-year sequence |
| student_id | FK → students | |
| level | enum | `SP1` \| `SP2` \| `SP3` |
| trigger_violation_record_id | FK → violation_records | violation that triggered |
| total_points_at_issue | int | point snapshot at print time |
| reason | text | |
| issued_by | FK → users | |
| issue_date | date | |
| academic_year_id | FK → academic_years | |
| signed_warning_doc_id | FK → documents | scan of signed SP letter, nullable |
| signed_statement_doc_id | FK → documents | scan of signed statement, nullable |
| status | enum | `issued` \| `signed_returned` \| `void` |
| created_at, updated_at | timestamp | |

### 2.10 `expulsion_recommendations`

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| letter_number | string | |
| letter_seq | int | per-academic-year sequence |
| student_id | FK → students | |
| trigger_violation_record_id | FK → violation_records | for sangat_berat trigger, nullable |
| trigger_warning_letter_id | FK → warning_letters | for post-SP3 trigger, nullable |
| reason | text | |
| total_points_at_issue | int | |
| issued_by | FK → users | |
| issue_date | date | |
| academic_year_id | FK → academic_years | |
| status | enum | `issued` \| `void` |
| created_at | timestamp | |

### 2.11 `student_point_summaries`

Cache/derived table for dashboard performance and SP-logic checks.

| Column | Type | Notes |
|---|---|---|
| student_id | PK, FK → students | |
| total_points | int | may be negative |
| current_sp_level | enum \| null | `null` \| `1` \| `2` \| `3` |
| last_sp_date | date \| null | |
| is_expelled | bool | default false |
| updated_at | timestamp | |

**Formula:** `total_points = SUM(violation_records.points WHERE is_void=false) − SUM(point_amnesties.points_reduced WHERE status != void)`.

Maintained in the same transaction as `record_violation` / `apply_amnesty`. A `recompute_summary(student_id)` helper is the source-of-truth backstop used after void/recover operations.

### 2.12 `point_amnesties`

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| letter_number | string | |
| letter_seq | int | per-academic-year sequence |
| student_id | FK → students | |
| points_reduced | int | positive integer (amount of reduction) |
| reason_category | enum | `prestasi` \| `perilaku_baik` \| `kerja_bakti` \| `lainnya` |
| reason | text | detail |
| sp_reset | bool | default false |
| principal_name | string | signing principal's name |
| recorded_by | FK → users | Guru BK who entered it |
| issue_date | date | |
| academic_year_id | FK → academic_years | |
| signed_document_id | FK → documents | NOT NULL — proof scan mandatory |
| status | enum | `issued` \| `void` |
| created_at, updated_at | timestamp | |

### 2.13 Indexes (mandatory)

```
violation_records:        (student_id), (academic_year_id), (created_at), (category_id)
warning_letters:          (student_id), (academic_year_id, letter_seq) UNIQUE
expulsion_recommendations:(student_id), (academic_year_id, letter_seq) UNIQUE
point_amnesties:          (student_id), (academic_year_id, letter_seq) UNIQUE
student_point_summaries:  (total_points)   -- for ranking/dashboard
students:                 (nis) UNIQUE, (class_id), (status)
```

Composite UNIQUE constraints on `(academic_year_id, letter_seq)` per letter table are enforced via `db.UniqueConstraint` in `__table_args__`.

---

## 3. Tech Stack (Final)

| Concern | Choice | Notes |
|---|---|---|
| Framework | **Flask** | server-rendered, no SPA |
| ORM | **Flask-SQLAlchemy** | |
| Migrations | **Flask-Migrate** (Alembic) | |
| Auth | **Flask-Login** | session/cookie + email/password |
| Password hashing | **passlib** (bcrypt) | |
| Forms + CSRF | **Flask-WTF** + **WTForms** | server-side validation, the only place enums are enforced |
| Email validation | **email-validator** | WTForms `EmailField` dependency |
| HTMX integration | **flask-htmx** | provides the `is_htmx` instance used by `hx_render` |
| PDF | **WeasyPrint** | Jinja2 HTML+CSS → PDF |
| Image handling | **Pillow** | thumbnails + evidence-photo validation |
| MIME sniffing | **python-magic** | upload validation |
| UI | **Jinja2 + Bootstrap 5** (CDN/static) | |
| Lists | **jQuery DataTables** | fed by `/data` JSON endpoints |
| Interactivity | **HTMX** | cascading selects, point preview, soft-delete modal, dashboard refresh |
| Config/env | **python-dotenv** | `.flaskenv` + `.env` |
| Package manager | **uv** | sole manager + runner; `pyproject.toml` + committed `uv.lock` |
| Lint/format | **ruff** | dev dependency |
| Testing | **pytest** + **pytest-flask** + **factory-boy** | dev dependency |
| Dev DB | **SQLite** | zero-config, in `instance/` folder |
| Prod DB | **PostgreSQL** via `psycopg[binary]` (v3) | env var `DATABASE_URL` |
| Prod server | **gunicorn** + nginx | |

**System dependencies for WeasyPrint** (install at OS level, not via pip):
`libpango-1.0-0 libpangoft2-1.0-0 libcairo2 gir1.2-rsvg-2.0`.

---

## 4. Architecture Decisions

| # | Aspect | Decision |
|---|---|---|
| D1 | HTMX scope | **Full Pattern1** — `hx-boost` on `<body>`, render-to-destination for all in-content mutations, dual-mode headers on every page. Graceful no-JS fallback. |
| D2 | Route organization | **Blueprint per entity** with `url_prefix`, registered in `create_app()`. |
| D3 | Auth | **Flask-Login** + Pattern1-style decorators wrapping it: `@role_required(...)`, `@class_owned_required`. Auth decorators always sit **outermost**. |
| D4 | List rendering | **jQuery DataTables** with per-blueprint `/data` JSON endpoint + destroy-guard IIFE on every list page. Bootstrap-Flask helpers are **not** used for lists. |
| D5 | Form rendering | **Inline Bootstrap markup** (`is-invalid` + `invalid-feedback` idiom), **not** Bootstrap-Flask `render_form`. |
| D6 | Notifications | `render_notif` macro via `hx_render(error=, success=, info=)` kwargs. **Do not use `flash()`.** |
| D7 | PDF | WeasyPrint from standalone templates in `templates/pdf/` — **not** dual-mode, does **not** extend `base.html`. Endpoint returns binary via `send_file`, exempt from R1. |
| D8 | File uploads | Werkzeug `secure_filename` + path strategy `<UPLOAD_FOLDER>/<document_type>/<yyyy>/<mm>/<uuid>.<ext>` + MIME whitelist + `MAX_CONTENT_LENGTH` + Pillow thumbnail for evidence photos. `UPLOAD_FOLDER` defaults to `instance/uploads`; overridden in prod via env var to a mounted volume. |
| D9 | DB & instance folder | Flask **instance folder** pattern (`instance_relative_config=True`) holds gitignored local artifacts: dev SQLite, `config.py` (dev secrets), `uploads/`, `cache/`. Test config passes in-memory SQLite. Prod secrets via env vars. |
| D10 | Transactions | `record_violation` & `apply_amnesty` are atomic. The **caller (route) commits**, not the service. Services accept an explicit `session` argument. |
| D11 | Tooling & runtime | **uv** is the sole package manager & runner. Runtime deps in `pyproject.toml`; dev deps (pytest, factory-boy, ruff) in `[dependency-groups] dev`; `uv.lock` **must be committed**. App packaged as `app/` with factory `app:create_app`. All commands prefixed `uv run` (e.g. `uv run flask run --debug`, `uv run flask db ...`, `uv run flask seed`, `uv run pytest`, `uv run gunicorn "app:create_app()"`). `.flaskenv` contains `FLASK_APP=app`. Python version pinned in `.python-version`. **No `run.py`, no `requirements.txt`, no global/manual `pip install`.** |

---

## 5. Project Structure

```
sicapel/                         # project root
├── app/                         # application package (factory: app:create_app)
│   ├── __init__.py              # create_app() factory + extension init
│   ├── helper.py                # htmx instance, hx_render, sanitize, role decorators
│   ├── models.py                # 12 SQLAlchemy models
│   ├── forms.py                 # all WTForms
│   ├── services.py              # domain logic + letter numbering + PDF + recompute_summary
│   ├── seed.py                  # Flask CLI command `uv run flask seed`
│   ├── blueprints/
│   │   ├── __init__.py
│   │   ├── auth.py              # login / logout
│   │   ├── dashboard.py         # Guru BK & Wali Kelas home + HTMX auto-refresh 60s
│   │   ├── students.py          # admin CRUD + guru_bk/wali_kelas list/detail
│   │   ├── classes.py           # admin CRUD
│   │   ├── violations.py        # input + list + detail + void + cascading + preview
│   │   ├── warnings.py          # list + detail + PDF + upload signed-scan
│   │   ├── amnesties.py         # list + form + PDF + sp_reset checkbox
│   │   ├── expulsion.py         # list + detail + PDF
│   │   ├── users.py             # admin CRUD
│   │   ├── violation_types.py   # admin CRUD
│   │   └── academic_years.py    # admin CRUD
│   ├── templates/
│   │   ├── base.html            # <html><head><body hx-boost> + #hx_content
│   │   ├── macros.html          # render_notif, render_field
│   │   ├── errors/{403,404,500}.html
│   │   ├── auth/login.html
│   │   ├── dashboard/index.html
│   │   ├── students/{index,form,detail}.html
│   │   ├── classes/{index,form}.html
│   │   ├── violations/{index,form,detail}.html
│   │   ├── warnings/{index,detail}.html
│   │   ├── amnesties/{index,form}.html
│   │   ├── expulsion/{index,detail}.html
│   │   ├── users/{index,form}.html
│   │   ├── violation_types/{index,form}.html
│   │   ├── academic_years/{index,form}.html
│   │   └── pdf/                 # standalone WeasyPrint, NOT dual-mode
│   │       ├── warning_letter_sp.html
│   │       ├── expulsion_recommendation.html
│   │       └── amnesty_letter.html
│   └── static/
│       ├── css/style.css
│       ├── js/{jquery.min,bootstrap.bundle.min,datatables.min,htmx.min}.js
│       └── js/app.js
├── instance/                    # gitignored — local artifacts
│   ├── sicapel.sqlite           #   dev DB
│   ├── config.py                #   dev secrets (SECRET_KEY etc.), gitignored
│   ├── uploads/                 #   upload root (D8), gitignored
│   └── cache/                   #   caches, gitignored
├── migrations/                  # Alembic (`uv run flask db init`)
├── tests/
│   ├── conftest.py
│   ├── factories.py
│   ├── test_services.py             # CRITICAL: 7 branches of §1.4
│   ├── test_apply_amnesty.py
│   ├── test_letter_numbering.py     # concurrency
│   ├── test_routes.py               # smoke + RBAC
│   └── test_pdfs.py                 # render smoke
├── pyproject.toml               # project metadata + deps (uv-managed)
├── uv.lock                      # lockfile, MUST be committed
├── .python-version              # Python pin (e.g. 3.12)
├── .flaskenv                    # FLASK_APP=app (committed)
├── .env.example
├── .gitignore                   # must ignore: instance/  (covers uploads/db/cache/config.py)
└── README.md
```

**File-extension convention:** templates use `.html` (not `.jinja`).

**`migrations/` and `tests/` live at project root**, not inside the `app/` package.

---

## 6. Rendering Pattern — Core Rules (R1–R11)

These rules are invariants. Apply them verbatim to every route and template or the dual-mode contract breaks.

| # | Rule |
|---|---|
| **R1** | Every HTML route returns `hx_render(template, ...)` — never raw `render_template`, never `redirect` for in-content mutations. |
| **R2** | `hx_render` is the single source of session/auth context. Templates must not read `session` directly; use the injected `current_user` / `is_htmx`. |
| **R3** | Every content template begins with the dual-mode header (see §10.1). |
| **R4** | Notifications passed as `error=` / `success=` / `info=` kwargs and rendered via the `render_notif` macro. No `flash()`. |
| **R5** | On successful mutation, re-render the **list/destination** template with `push_url="<endpoint>"`. On validation failure, re-render the **form** template **without** `push_url`. |
| **R6** | In-content links carry BOTH `href` and `hx-get` pointing at the same URL, plus `hx-target="#hx_content"` + `hx-swap="innerHTML"`. |
| **R7** | `<body>` carries `hx-boost="true"`; navigation links are progressively enhanced, never replaced. |
| **R8** | CSRF token mandatory on every POST form via `{{ form.hidden_tag() }}` (WTForms) or an explicit `<input name="csrf_token" value="{{ csrf_token() }}">`. |
| **R9** | User-supplied strings stored in DB or emitted into HTML/JS literals must pass through `sanitize()` first. |
| **R10** | The body always has exactly one swap target, `id="hx_content"`. |
| **R11** | Page-specific JS (DataTables init, onclick helpers) lives **inside** `{% block content %}`, and every DataTable init is wrapped in a destroy-guard IIFE. |

### 6.1 The `is_htmx` truthiness contract

`hx_render()` passes the **HTMX instance itself** (not a bool) into templates as `is_htmx`. The instance's `__bool__` returns `True` when `HX-Request: true` is in headers. In Jinja, always use `{% if not is_htmx %}` — **never** compare with `== True`.

### 6.2 Endpoints exempt from R1

| Endpoint | Return | Reason |
|---|---|---|
| `/warnings/<id>/pdf`, `/expulsion/<id>/pdf`, `/amnesties/<id>/pdf` | PDF bytes (`send_file`) | binary, not HTML |
| `/pelanggaran/preview-points` | JSON `{points, category, will_trigger_sp, sp_level}` | HTMX point preview |
| `/students/by-class/<int:class_id>` | JSON list | cascading select |
| `<entity>/data` (all lists) | `jsonify(data=[...])` | DataTables feed |
| `/<entity>/<id>/void` | HTML (re-rendered list via `hx_render`) | mutation but uses `hx_render` |

---

## 7. App Factory & Helper Layer

### 7.1 `app/__init__.py` — `create_app()` contract

```python
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import CSRFProtect

from .helper import htmx

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-me"),
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "DATABASE_URL",
            f"sqlite:///{os.path.join(app.instance_path, 'sicapel.sqlite')}"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        UPLOAD_FOLDER=os.environ.get(
            "UPLOAD_FOLDER", os.path.join(app.instance_path, "uploads")),
        CACHE_DIR=os.path.join(app.instance_path, "cache"),
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,
    )
    for sub in ("uploads", "cache"):
        os.makedirs(os.path.join(app.instance_path, sub), exist_ok=True)
    app.config.from_pyfile("config.py", silent=True)
    if test_config:
        app.config.from_mapping(test_config)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    htmx.init_app(app)

    from .blueprints import (auth, dashboard, students, classes, violations,
                             warnings, amnesties, expulsion, users,
                             violation_types, academic_years)
    for bp in (auth.bp, dashboard.bp, students.bp, classes.bp, violations.bp,
               warnings.bp, amnesties.bp, expulsion.bp, users.bp,
               violation_types.bp, academic_years.bp):
        app.register_blueprint(bp)

    from .seed import seed_cli
    app.cli.add_command(seed_cli)

    return app
```

**Consequences:**
- `tests/conftest.py` imports `from app import create_app` and calls `create_app(test_config={"SQLALCHEMY_DATABASE_URI": "sqlite://"})`.
- `.gitignore` must contain `instance/`.
- In prod, `UPLOAD_FOLDER` & `DATABASE_URL` come from env vars; `instance/uploads` is replaced by a mounted volume.

### 7.2 `app/helper.py` — core helpers

```python
import functools
import html
from flask import make_response, render_template, url_for, current_app
from flask_htmx import HTMX
from flask_login import current_user
from werkzeug.utils import secure_filename

htmx = HTMX()  # single shared instance; init_app(app) called in factory


def sanitize(value):
    """HTML-escape user strings before DB write or HTML/JS literal embed (R9)."""
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def hx_render(template, push_url=None, **kwargs):
    """The ONLY function routes use to render HTML (R1, R2).
    Injects current_user + is_htmx. If push_url is given, sets HX-Push-Url."""
    kwargs.setdefault("current_user",
                      current_user if current_user.is_authenticated else None)
    kwargs.setdefault("is_htmx", htmx)
    if push_url:
        resp = make_response(render_template(template, **kwargs))
        resp.headers["HX-Push-Url"] = (
            push_url if push_url.startswith(("/", "http"))
            else url_for(push_url)
        )
        return resp
    return render_template(template, **kwargs)


def role_required(*roles):
    """Decorator outermost. roles: 'admin' | 'guru_bk' | 'wali_kelas'."""
    def decorator(view):
        @functools.wraps(view)
        def wrapped(**kwargs):
            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()
            if current_user.role not in roles:
                return hx_render("errors/403.html"), 403
            return view(**kwargs)
        return wrapped
    return decorator


def class_owned_required(view):
    """For wali_kelas: target student must be in their class.
    admin & guru_bk bypass."""
    @functools.wraps(view)
    def wrapped(student_id, **kwargs):
        if current_user.role == "wali_kelas":
            from .models import Student
            s = Student.query.get_or_404(student_id)
            if s.class_.homeroom_teacher_id != current_user.id:
                return hx_render("errors/403.html"), 403
        return view(student_id=student_id, **kwargs)
    return wrapped


def current_academic_year():
    """Helper: return the academic_year with is_active=True."""
    from .models import AcademicYear
    return AcademicYear.query.filter_by(is_active=True).first()
```

---

## 8. Service Layer Contract

`app/services.py` contains all domain logic. Functions accept an explicit `session` and **do not commit** — the route caller commits.

### 8.1 `record_violation`

```python
def record_violation(*, student_id, violation_type_id, points, chronology,
                     location, incident_date, incident_time,
                     academic_year_id, semester, recorded_by, session) -> dict:
    """Implements §1.4. Atomic; caller commits.
    Returns:
      {'violation': ViolationRecord,
       'new_warning': WarningLetter | None,
       'new_expulsion': ExpulsionRecommendation | None,
       'summary': StudentPointSummary,
       'student_expelled': bool}

    Branches that MUST be correct (tested exhaustively in test_services.py):
      - ringan -> points only
      - menengah + no prior SP + total <= 100 -> points only
      - menengah + no prior SP + total > 100 -> SP1
      - menengah + prior SP -> escalate SP
      - berat from null -> SP1
      - berat from SP3 -> expulsion
      - sangat_berat -> expulsion + student.status = expelled
      - menengah/berat after SP3 -> expulsion
    """
```

### 8.2 `apply_amnesty`

```python
def apply_amnesty(*, student_id, points_reduced, sp_reset, reason,
                  reason_category, principal_name, issue_date,
                  academic_year_id, recorded_by, signed_document_id,
                  session) -> "PointAmnesty":
    """§1.6. Points may go negative (never clamp). If sp_reset=True,
    set current_sp_level=null and last_sp_date=null."""
```

### 8.3 `next_letter_seq`

```python
def next_letter_seq(model, academic_year_id, session) -> int:
    """Optimistic letter_seq allocation.
    Pattern: COALESCE(MAX(letter_seq), 0) + 1, evaluated within the
    caller's open transaction (no SELECT ... FOR UPDATE, no BEGIN
    IMMEDIATE).

    Concurrency safety comes from the UNIQUE(academic_year_id, letter_seq)
    constraint on every letter table (§2.13), not from row locking. Two
    concurrent allocations that race on the same MAX(seq) will both pick
    the same value; exactly one survives COMMIT and the other raises
    IntegrityError and rolls back. For v1 (a handful of Guru BK users)
    a rare simultaneous collision is acceptable — the transaction simply
    rolls back and the error surfaces to the user, who retries. No
    automatic retry layer is added in v1."""
```

### 8.4 `recompute_summary`

```python
def recompute_summary(student_id, session) -> "StudentPointSummary":
    """Recompute total_points & is_expelled from source
    (non-void violation_records + non-void point_amnesties).
    Used after void/recover as the source of truth."""
```

### 8.5 PDF renderers

```python
def render_warning_letter_pdf(warning_letter) -> bytes: ...
def render_expulsion_pdf(expulsion) -> bytes: ...
def render_amnesty_pdf(amnesty) -> bytes: ...
```

---

## 9. Blueprint Pattern

Each entity blueprint follows the same skeleton. Auth decorator sits **outermost**; mutating routes use the GET → fail-validate → success order.

### 9.1 Canonical skeleton (`blueprints/violations.py` excerpt)

```python
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user

from ..helper import (role_required, class_owned_required, hx_render,
                      sanitize, current_academic_year)
from ..models import db, ViolationRecord, Student, ViolationType
from ..forms import ViolationRecordForm
from ..services import record_violation

bp = Blueprint("violations", __name__, url_prefix="/pelanggaran")


@bp.route("/")
@login_required
@role_required("admin", "guru_bk", "wali_kelas")
def index():
    return hx_render("violations/index.html")


@bp.route("/data")
@login_required
@role_required("admin", "guru_bk", "wali_kelas")
def data():
    q = ViolationRecord.query.filter_by(is_void=False)
    if current_user.role == "wali_kelas":
        q = (q.join(Student)
               .filter(Student.class_.homeroom_teacher_id == current_user.id))
    rows = []
    for i, v in enumerate(q.order_by(ViolationRecord.created_at.desc()).all(), 1):
        rows.append({
            "no": i,
            "student": sanitize(v.student.name),
            "type": sanitize(v.violation_type.name),
            "category": v.category.name,
            "points": v.points,
            "date": v.incident_date.isoformat(),
            "actions": _row_actions(v),  # helper returning pre-rendered HTML
        })
    return jsonify(data=rows)


@bp.route("/tambah", methods=["GET", "POST"])
@login_required
@role_required("admin", "guru_bk", "wali_kelas")
def tambah():
    form = ViolationRecordForm()
    form.student_id.choices = _student_choices()
    form.violation_type_id.choices = _violation_type_choices()

    if request.method == "GET":
        return hx_render("violations/form.html", form=form, record=None)

    if not form.validate_on_submit():                       # R5: fail -> form
        return hx_render("violations/form.html", form=form, record=None)

    result = record_violation(
        student_id=form.student_id.data,
        violation_type_id=form.violation_type_id.data,
        points=form.points.data,
        chronology=sanitize(form.chronology.data),
        location=sanitize(form.location.data),
        incident_date=form.incident_date.data,
        incident_time=form.incident_time.data,
        academic_year_id=current_academic_year().id,
        semester=form.semester.data,
        recorded_by=current_user.id,
        session=db.session,
    )
    db.session.commit()                                     # caller commits (D10)

    notif = {"success": "Pelanggaran dicatat."}
    if result.get("new_warning"):
        notif["info"] = f"SP{result['new_warning'].level} terbit untuk siswa."
    if result.get("student_expelled"):
        notif["error"] = "Siswa dikeluarkan — surat rekomendasi terbit."

    return hx_render("violations/index.html",              # R5: success -> list
                     push_url="violations.index", **notif)
```

Other endpoints in this blueprint: `detail/<int:id>`, `void/<int:id>` (POST, sets `is_void=True` + calls `recompute_summary`), `preview-points` (JSON for HTMX preview), plus private helpers `_student_choices()` (scope by role), `_violation_type_choices()`, `_row_actions(v)`.

The other 10 blueprints (`auth`, `dashboard`, `students`, `classes`, `warnings`, `amnesties`, `expulsion`, `users`, `violation_types`, `academic_years`) follow the same shape.

### 9.2 Blueprint registration (inside `create_app`)

```python
from .blueprints import (auth, dashboard, students, classes, violations,
                         warnings, amnesties, expulsion, users,
                         violation_types, academic_years)
for bp in (auth.bp, dashboard.bp, students.bp, classes.bp, violations.bp,
           warnings.bp, amnesties.bp, expulsion.bp, users.bp,
           violation_types.bp, academic_years.bp):
    app.register_blueprint(bp)
```

---

## 10. Template Conventions

### 10.1 Dual-mode header (R3) — mandatory first lines

Every content template (list, form, detail) starts with:

```jinja
{% if not is_htmx %}
    {% extends "base.html" %}
    {% block title %}<Page Title>{% endblock %}
{% else %}
    <title><Page Title></title>
{% endif %}

{% from "macros.html" import render_notif %}

{% block content %}
{{ render_notif(error, success, info) }}

... page-specific markup ...

{% endblock %}
```

`{% block %}` tags are inert when not extending, so the inner markup renders exactly once in both modes. **Never** put content outside `{% block content %}` (other than the dual-mode header + macro import) — it vanishes in HTMX mode.

### 10.2 `base.html` core

```jinja
<body hx-boost="true" hx-push-url="true">
  <nav hx-target="#hx_content" hx-swap="innerHTML">
    ... links with both href (fallback) and hx-get (partial swap) ...
  </nav>
  <main>
    <div id="hx_content">
      {% block content %}{% endblock %}
    </div>
  </main>
</body>
```

### 10.3 Notification macro (`templates/macros.html`)

```jinja
{% macro render_notif(error, success, info) %}
  {% if error %}<div class="alert alert-warning alert-dismissible fade show" role="alert">
    {{ error }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>{% endif %}
  {% if success %}<div class="alert alert-success alert-dismissible fade show" role="alert">
    {{ success }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>{% endif %}
  {% if info %}<div class="alert alert-primary alert-dismissible fade show" role="alert">
    {{ info }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>{% endif %}
{% endmacro %}
```

Only `error`, `success`, `info` are recognized. The macro renders nothing when all three are falsy.

### 10.4 Field rendering (inline Bootstrap, D5)

```jinja
<div class="mb-3">
    {{ form.name.label(class='form-label') }}
    {{ form.name(class='form-control' + (' is-invalid' if form.name.errors else ''), required=True) }}
    {% if form.name.errors %}
    <div class="invalid-feedback">
        {% for error in form.name.errors %}{{ error }}{% endfor %}
    </div>
    {% endif %}
</div>
```

The `(' is-invalid' if field.errors else '')` idiom wires WTForms errors into Bootstrap 5's invalid-feedback UI. **Always include the `{% if field.errors %}` block** when rendering inline.

### 10.5 Form element (HTMX-enhanced)

```jinja
<form method="POST"
      action="{{ url_for('violations.edit', id=record.id) if record else url_for('violations.tambah') }}"
      hx-post="{{ url_for('violations.edit', id=record.id) if record else url_for('violations.tambah') }}"
      hx-target="#hx_content"
      hx-swap="innerHTML">
    {{ form.hidden_tag() }}
    ...fields...
    <button type="submit" class="btn btn-primary">Simpan</button>
    <a class="btn btn-secondary" href="{{ url_for('violations.index') }}"
       hx-get="{{ url_for('violations.index') }}"
       hx-target="#hx_content" hx-swap="innerHTML">Batal</a>
</form>
```

`method="POST"` + `action` is the no-JS fallback; `hx-post` upgrades to a partial swap when JS is on. Both point at the **same URL**.

### 10.6 List page (DataTables) — canonical block

Every list page places this inside `{% block content %}` so the script re-runs after each HTMX swap:

```jinja
<table id="violationsTable" class="table table-striped table-bordered">
    <thead><tr><th>No</th><th>Siswa</th><th>Jenis</th><th>Kategori</th><th>Poin</th><th>Tanggal</th><th>Aksi</th></tr></thead>
    <tbody></tbody>
</table>

<div class="modal fade" id="modalHapus" tabindex="-1">
  <div class="modal-dialog"><div class="modal-content">
    <div class="modal-body">Yakin membatalkan <strong id="modalHapusNama"></strong>?</div>
    <div class="modal-footer">
      <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Batal</button>
      <form id="modalHapusForm" hx-post="{{ url_for('violations.void') }}"
            onsubmit="bootstrap.Modal.getInstance(document.getElementById('modalHapus')).hide()"
            style="display:inline">
        <input type="hidden" name="id" id="modalHapusId" value=""/>
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
        <button type="submit" class="btn btn-danger">Void</button>
      </form>
    </div>
  </div></div>
</div>

<script>
var hapus_violation = (id, nama) => {
    document.getElementById('modalHapusId').value = id;
    document.getElementById('modalHapusNama').textContent = nama;
    new bootstrap.Modal(document.getElementById('modalHapus')).show();
};
var edit_violation = (id) => {
    var raw_url = "{{ url_for('violations.detail', id=0) }}";
    htmx.ajax("GET", raw_url.slice(0, -1) + id, {target:'#hx_content', swap:'innerHTML'});
};
(function() {                                   // R11: destroy-guard IIFE — MANDATORY
    if ($.fn.DataTable.isDataTable('#violationsTable')) {
        $('#violationsTable').DataTable().destroy();
        $('#violationsTable').empty();
    }
    $('#violationsTable').DataTable({
        ajax: { url: '{{ url_for("violations.data") }}', dataSrc: 'data' },
        columns: [
            { data: 'no' },
            { data: 'student' },
            { data: 'type' },
            { data: 'category' },
            { data: 'points' },
            { data: 'date' },
            { data: 'actions', orderable: false, searchable: false }
        ],
        language: {
            search: 'Cari:', lengthMenu: 'Tampilkan _MENU_ data',
            info: 'Menampilkan _START_ - _END_ dari _TOTAL_ data',
            infoEmpty: 'Belum ada data', emptyTable: 'Belum ada data',
            zeroRecords: 'Tidak ditemukan data yang cocok',
            paginate: { previous: 'Sebelumnya', next: 'Selanjutnya' }
        }
    });
})();
</script>
```

**Key wiring facts:**
- `/data` returns `jsonify(data=[...])` — the `data=` wrapper is mandatory; DataTables reads it via `dataSrc: 'data'`.
- `actions` cells contain **pre-rendered HTML** built server-side; mark them `orderable: false, searchable: false`.
- Every user-controlled value embedded in `onclick="fn('…')"` JS literals must pass through `sanitize()`.
- `edit_<entity>(id)` builds the edit URL via the `id=0` slice trick (`url_for('...', id=0)` emits `.../0`; slice off the `0`, append real id).
- The destroy-guard IIFE is the only thing that prevents `Cannot reinitialise DataTable` after HTMX re-swaps.

---

## 11. PDF Generation

WeasyPrint renders Jinja2 HTML+CSS to PDF. Templates live in `templates/pdf/`, are **standalone** (do **not** extend `base.html`, do **not** use the dual-mode header), and use `@page` CSS + letterhead markup.

PDF endpoints return binary via `send_file` and are therefore exempt from R1:

```
GET /warnings/<id>/pdf      -> send_file(pdf_bytes)
GET /expulsion/<id>/pdf     -> send_file(pdf_bytes)
GET /amnesties/<id>/pdf     -> send_file(pdf_bytes)
```

PDF rendering is invoked from `services.py` (see §8.5). The service loads the template via `render_template(...)` then calls `HTML(string=...).write_pdf()`.

---

## 12. File Uploads

- **Path strategy:** `<UPLOAD_FOLDER>/<document_type>/<yyyy>/<mm>/<uuid>.<ext>` — avoid filename collisions; never store user-supplied filenames as the path.
- `UPLOAD_FOLDER` defaults to `instance/uploads`; overridden in prod via env var to a mounted volume.
- `MAX_CONTENT_LENGTH` = 16 MiB (set in `create_app`).
- **MIME whitelist** via `python-magic` (content sniffing, not extension trust).
- **Evidence photos:** Pillow decode-test + thumbnail generation.
- `documents.file_path` stores the absolute path; `file_size` in bytes; `mime_type` sniffed.

---

## 13. Testing Strategy

All tests via `uv run pytest`. Environment is isolated by uv (dev deps from `[dependency-groups] dev`); DB is SQLite in-memory.

### 13.1 `conftest.py`

Must `from app import create_app` and call `create_app(test_config={"SQLALCHEMY_DATABASE_URI": "sqlite://"})`. Provides fixtures: `app`, `client`, `logged_in_admin`, `logged_in_guru_bk`, `logged_in_wali_kelas`, `active_academic_year`. Uses SQLite in-memory + auto-migrate. factory-boy generates students/users/violation_types.

### 13.2 `test_services.py` — CRITICAL

Must cover **7 branches** of the SP escalation logic (§1.4):

1. `ringan` → no SP.
2. `menengah` + no prior SP + total ≤ 100 → no SP.
3. `menengah` + no prior SP + total > 100 → SP1.
4. `menengah` + prior SP → escalate.
5. `berat` from `null` → SP1.
6. `berat` from SP3 → expulsion.
7. `sangat_berat` → expulsion + `student.status = expelled`.

### 13.3 `test_apply_amnesty.py`

`sp_reset=True/False`, points may go negative.

### 13.4 `test_letter_numbering.py`

Deterministic, single-threaded tests (no `threading` — in-memory SQLite is
per-connection and cannot reliably exercise real concurrency). Cases:

1. First allocation for an academic year returns `1`.
2. Subsequent allocations increment monotonically — no gaps, no duplicates.
3. Sequences are independent per academic year (two years both start at `1`).
4. `letter_number` is formatted `{seq:03d}/<TYPE>/BK/{year}` (§1.7).
5. Backstop proof: directly inserting a row with a duplicate
   `(academic_year_id, letter_seq)` raises `IntegrityError` — this
   deterministically verifies the UNIQUE constraint that makes the
   optimistic strategy in §8.3 safe.

The genuine prod race (PostgreSQL two-writer collision → one IntegrityError)
is covered analytically by case 5; a flaky `threading.Thread` test against
in-memory SQLite is deliberately not attempted.

### 13.5 `test_routes.py`

Per role, assert 200/302/403 at every endpoint; wali_kelas cannot see students outside their class.

### 13.6 `test_pdfs.py`

Render each PDF template with a sample object; assert non-empty bytes + magic header `%PDF`. Gate with `pytest.importorskip("weasyprint")` so tests skip cleanly if system deps are missing.

---

## 14. Implementation Order (T1–T20)

| # | Task | Blocked by |
|---|---|---|
| **T1** | **Scaffold.** `uv init` + create `app/` package + `uv add flask flask-sqlalchemy flask-wtf flask-login flask-htmx python-dotenv weasyprint psycopg[binary] pillow python-magic` + `uv add --group dev pytest factory-boy ruff`. Then `app/__init__.py` factory (`create_app` + instance folder per §7.1), `app/helper.py` (htmx + hx_render + sanitize + role decorators stub), `pyproject.toml` + `uv.lock`, `.flaskenv` (`FLASK_APP=app`), `.env.example`, `.gitignore` (must include `instance/`), `/healthcheck` route. **Verify:** `uv run flask run --debug` starts and `/healthcheck` returns 200. | — |
| **T2** | `models.py` (12 models per §2) + `uv run flask db init/migrate/upgrade`; smoke-test schema on both SQLite and an empty PostgreSQL. | T1 |
| **T3** | `app/seed.py` exposed as Flask CLI command (`seed_cli`, registered in `create_app`): 4 `violation_categories`, 1 admin user, sample `violation_types`, 1 active `academic_year`. Run via `uv run flask seed`. | T2 |
| **T4** | `auth.py` blueprint + Flask-Login wiring + `@role_required` + `@class_owned_required`. | T1, T2 |
| **T5** | `base.html` + `macros.html` + nav partial + dual-mode header convention. | T4 |
| **T6** | **`services.record_violation`** + `test_services.py` (7 cases). | T2 |
| **T7** | `services.apply_amnesty` + `services.recompute_summary` + `test_apply_amnesty.py`. | T6 |
| **T8** | `services.next_letter_seq` + `test_letter_numbering.py`. | T2 |
| **T9** | Blueprint `students` (admin CRUD + list/detail for others) — canonical Pattern1 reference. | T4, T5 |
| **T10** | Blueprints `classes`, `users`, `violation_types`, `academic_years` (admin CRUD, copy T9 pattern). | T9 |
| **T11** | Blueprint `violations` (input + list + detail + void + cascading select + point preview). | T6, T9 |
| **T12** | Blueprint `warnings` (list + detail + PDF + upload signed-scan). | T8, T11 |
| **T13** | Blueprint `expulsion` (list + detail + PDF). | T8 |
| **T14** | Blueprint `amnesties` (form + PDF + `sp_reset` checkbox + scan upload). | T7, T8 |
| **T15** | Blueprint `dashboard` (ranking by `total_points`, highlight `> 200`, HTMX auto-refresh 60s). | T11, T14 |
| **T16** | PDF templates `app/templates/pdf/*.html` + WeasyPrint wiring. | T12, T13, T14 |
| **T17** | Upload hardening: `MAX_CONTENT_LENGTH`, MIME whitelist, Pillow thumbnail for evidence photos. | T11, T14 |
| **T18** | Void/recover flows + recompute summaries. | T11, T14 |
| **T19** | Final audit: `uv run ruff check .`, CSRF on every form, audit `sanitize()` on every DataTables cell. | all |
| **T20** | Deploy: install uv on the server, `uv sync --frozen --no-dev` (from committed `uv.lock`), run `uv run gunicorn "app:create_app()" ...` + nginx, env vars `DATABASE_URL`/`SECRET_KEY`/`UPLOAD_FOLDER` (point `UPLOAD_FOLDER` at a mounted volume), `uv run flask db upgrade` on first deploy. | T19 |

---

## 15. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| WeasyPrint system deps missing | Document `apt-get install libpango-1.0-0 libpangoft2-1.0-0 libcairo2 gir1.2-rsvg-2.0` in README; gate PDF tests with `pytest.importorskip("weasyprint")`. |
| Letter-numbering collision on simultaneous commit | The `UNIQUE(academic_year_id, letter_seq)` constraint (§2.13) makes duplicate seqs impossible to persist — corruption cannot occur. The residual risk is a rare user-visible error on a truly simultaneous commit (two Guru BK issuing letters in the same millisecond), which rolls back the loser's transaction; the user retries. Acceptable for v1's small user set; see §8.3. |
| `Cannot reinitialise DataTable` after HTMX re-swap | Destroy-guard IIFE is mandatory (R11); consider a ruff grep check that every init is guarded. |
| Wali kelas accessing students outside their class | Centralize scoping in `_student_choices()` + `@class_owned_required` decorator; per-endpoint RBAC integration tests. |
| `student_point_summaries` drift from source of truth | `recompute_summary()` helper as backstop; consider a nightly job. |
| Upload abuse (MIME spoofing, large files) | `MAX_CONTENT_LENGTH` + MIME whitelist via `python-magic` + Pillow decode-test for photos + UUID path strategy. |
| Enum migration behavior differs SQLite vs PostgreSQL | Run `uv run flask db upgrade` against an empty PostgreSQL periodically from T2 onward as a smoke test. |
| uv not installed on server/CI runner | Install uv via the official installer (`curl -LsSf https://astral.sh/uv/install.sh \| sh`) in the Dockerfile/CI; deploy **must** use `uv sync --frozen` from the committed `uv.lock` so dev↔prod versions are identical. |

---

## 16. Open Items

- [ ] Sample letterhead / school letterhead (from user) — needed before T16 PDF polish.
- [ ] Initial `violation_types` list beyond the V1 examples (from Guru BK) — needed for a richer T3 seed.
- [ ] Database backup mechanism (cron `pg_dump` vs managed service).
- [ ] Excel/CSV report export per class/semester — add `uv add openpyxl` if approved.
- [ ] Upload storage: local filesystem sufficient for v1; S3/MinIO deferred.

---

*This document supersedes all prior planning drafts. Implementation starts at T1.*
