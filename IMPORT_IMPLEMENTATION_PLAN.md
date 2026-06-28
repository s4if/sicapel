# SICAPEL — Import (Bulk Load) Implementation Plan

> **Scope of this document:** bulk import of **Students**, **Classes**, and
> **Teachers** from a user-uploaded `.xlsx` file. Excel **reports** (monthly /
> semester / yearly violations & SP issuance) are a separate feature and are
> **not** covered here; they will get their own plan document.
>
> **Relationship to the master plan:** this is a focused addendum to
> `SICAPEL_IMPLEMENTATION_PLAN.md`. It reuses that document's invariants
> verbatim — blueprint-per-entity (D2), `hx_render` for HTML / `send_file` for
> binary (R1 + §6.2 exemptions), auth decorators outermost (D3), `sanitize()`
> for HTML-attribute contexts (R9), caller-commits transactions (D10),
> `uv`-managed tooling (D11), and the §13 testing strategy.

---

## Table of Contents

1. [Confirmed Decisions](#1-confirmed-decisions)
2. [Dependency](#2-dependency)
3. [Module Layout (files to add / edit)](#3-module-layout-files-to-add--edit)
4. [Shared xlsx Template Layout](#4-shared-xlsx-template-layout)
5. [Entity Specs](#5-entity-specs)
   - 5.1 [Students](#51-students)
   - 5.2 [Classes](#52-classes)
   - 5.3 [Teachers](#53-teachers)
6. [Import Service API](#6-import-service-api)
7. [Processing Algorithm (all-or-nothing)](#7-processing-algorithm-all-or-nothing)
8. [Template Generators](#8-template-generators)
9. [Routes & RBAC](#9-routes--rbac)
10. [Upload Form & UI](#10-upload-form--ui)
11. [Testing Plan](#11-testing-plan)
12. [Open Decisions](#12-open-decisions)
13. [Implementation Order](#13-implementation-order)
14. [Verification](#14-verification)

---

## 1. Confirmed Decisions

| # | Decision | Value |
|---|---|---|
| D-1 | Error strategy | **All-or-nothing.** Validate every row first; if any row is invalid, reject the whole file and write nothing. Show a per-row error list. |
| D-2 | Duplicate mode | A **`Mode`** config cell in the file with exactly two values: **`Insert Only`** (existing key → error row) or **`Update`** (upsert: existing key → update fields, else create). |
| D-3 | Row count | A **`Jumlah Baris`** config cell the user fills manually; the importer reads exactly that many data rows. Removes end-of-data guessing. |
| D-4 | Teacher password | Explicit **`Password`** column in the teachers template; hashed via `hash_password` on write. |
| D-5 | Homeroom-teacher resolution | **By ID** in the classes template (`Wali Kelas` = a user `id`). A pre-filled **reference table** of teachers is embedded in the same sheet so the user can look up IDs. |
| D-6 | RBAC | Students import → **admin + guru_bk**. Classes & Teachers import → **admin only** (matches each entity's `tambah`). |

---

## 2. Dependency

Add `openpyxl` (read + write `.xlsx`):

```sh
uv add openpyxl
```

Commit the updated `pyproject.toml` **and** `uv.lock`. (This is the dependency
already anticipated by `SICAPEL_IMPLEMENTATION_PLAN.md` §16 Open Items.)

**No model changes, no migration.** All imports write to existing tables
(`students`, `classes`, `users`); `student_point_summaries` rows are not
created by import (a brand-new student has zero points and no summary row,
which the rest of the app already treats as "0 / no SP").

---

## 3. Module Layout (files to add / edit)

```
app/
├── imports.py                       # NEW — parsing/validation/upsert + template builders
├── forms.py                         # EDIT — add ImportForm
├── blueprints/
│   ├── students.py                  # EDIT — add impor + impor_template routes
│   ├── classes.py                   # EDIT — add impor + impor_template routes
│   └── users.py                     # EDIT — add impor + impor_template routes
└── templates/
    ├── students/{index,impor}.html  # EDIT index (Impor button) + NEW impor.html
    ├── classes/{index,impor}.html   # EDIT index (Impor button) + NEW impor.html
    └── users/{index,impor}.html     # EDIT index (Impor button) + NEW impor.html
tests/
└── test_imports.py                  # NEW
```

`app/imports.py` is a peer of `services.py`: it holds the domain logic for
parsing an xlsx into validated model rows and applying them. Routes stay thin.

---

## 4. Shared xlsx Template Layout

Every template (students / classes / teachers) uses the **same header anatomy**
so the parser has one shape to learn:

```
     A                 B
1    Mode              <Insert Only | Update>
2    Jumlah Baris      <positive integer — number of data rows>
3    (blank separator)
4    <col header 1>    <col header 2>   ...        ← header row
5    <data row 1>
6    <data row 2>
…                       (exactly Jumlah Baris rows are read, starting at row 5)
```

**Config cells**

- `B1` — **Mode**. Two legal values only: `Insert Only`, `Update`.
  Anything else → a single top-level error ("Mode tidak valid").
- `B2` — **Jumlah Baris**. Must be a positive integer. The parser reads exactly
  this many rows beginning at row 5 (the first data row). Rationale: makes the
  import deterministic — no trailing-blank-row detection, no "forgot to clear
  the example rows" surprises. If a row within `1..N` is entirely blank, it is
  reported as an error (`baris kosong`). The user must set this to the exact
  number of data rows.

**Why a manual count instead of "read until blank"?** The user asked for it
because it makes the implementation simpler and the contract explicit. The
trade-off (user can miscount) is acceptable and surfaced clearly in the UI:
the result summary reports `created`/`updated` counts so a miscount is obvious.

---

## 5. Entity Specs

Required fields are marked `*`. "Key" = the natural key used for the
Insert-Only vs Update decision.

### 5.1 Students

**Header row (row 4), data from row 5:**

| Col | Header | Required | Notes |
|---|---|---|---|
| A | `NIS` | yes | **Key.** Must be unique among non-deleted students. |
| B | `NISN` | no | |
| C | `Nama` | yes | |
| D | `JK` | yes | `L` or `P` only. |
| E | `Tempat Lahir` | no | |
| F | `Tanggal Lahir` | no | `YYYY-MM-DD`. |
| G | `Alamat` | no | |
| H | `Kelas` | yes | A `classes.id` (**resolved by ID**, mirroring D-5). Must reference an existing, non-deleted class. |
| I | `Nama Orang Tua` | no | |
| J | `No. Telepon Orang Tua` | no | |
| K | `Status` | no (default `active`) | One of `active/expelled/graduated/transferred`. |
| L | `Tanggal Masuk` | no | `YYYY-MM-DD`. |

**Reference table (not imported) — starts at column O:**

The students data block spans A–L. Columns M–N are left blank as a visual
gutter. From column O the template embeds a lookup table, **pre-filled at
download time** from the live DB, so the user can copy the right `Kelas` ID
into column H:

```
O4 = "Daftar Kelas (referensi — tidak diimpor)"
O5 = "ID"   P5 = "Nama Kelas"   Q5 = "Tingkat"   R5 = "Wali Kelas"
O6 = 3      P6 = "X IPA 1"      Q6 = 10          R6 = "Budi"
O7 = 4      P7 = "XI IPA 1"     Q7 = 11          R7 = "Siti"
…
```

Source query: `Class` where `is_deleted = False`, ordered by `grade_level`
then `name` (same filter as `students._class_choices()`).

The parser **ignores columns O onward**; it only reads the A–L data block
(rows 5..5+N-1). The reference table exists purely for ID lookup — it is the
same pattern used by the classes template's `Daftar Wali Kelas`.

> Workflow note: a brand-new class must be added/imported **before** it can be
> referenced here. Re-download the template to refresh the list.

- Mode behaviour:
  - `Insert Only`: a `NIS` that already exists (non-deleted) → error row.
  - `Update`: existing `NIS` → update fields B–L (except `created_at`); else insert.

### 5.2 Classes

**Data columns (A–C), header row 4, data from row 5:**

| Col | Header | Required | Notes |
|---|---|---|---|
| A | `Nama Kelas` | yes | **Key.** See O-2 for composite-key nuance. |
| B | `Tingkat` | yes | Integer `10`, `11`, or `12`. |
| C | `Wali Kelas` | yes | A `users.id` (**resolved by ID** per D-5). Must reference an existing, non-deleted user with `role = wali_kelas`. |

**Reference table (not imported) — starts at column F:**

Columns D–E are left blank as a visual gutter. From column F the template
embeds a lookup table, **pre-filled at download time** from the live DB:

```
F4 = "Daftar Wali Kelas (referensi — tidak diimpor)"
F5 = "ID"   G5 = "Nama"   H5 = "Email"   I5 = "NIP"
F6 = 12     G6 = "Budi"   H6 = "budi@…"  I6 = "198…"
F7 = 14     G7 = "Siti"   H7 = "siti@…"  I7 = "197…"
…
```

The parser **ignores columns F onward**; it only reads the A–C data block
(rows 5..5+N-1). The reference table exists purely so the user can copy the
right `Wali Kelas` ID into column C.

> Workflow note: a brand-new teacher must be added/imported **before** it can be
> referenced here. Re-download the template to refresh the list.

- Mode behaviour (key = `Nama Kelas`; see O-2):
  - `Insert Only`: a class with that name already exists → error row.
  - `Update`: existing class → update `Tingkat` and `Wali Kelas`; else insert.

### 5.3 Teachers

A "teacher" is a `User` row (any role, but typically `wali_kelas`/`guru_bk`).

**Header row 4, data from row 5:**

| Col | Header | Required | Notes |
|---|---|---|---|
| A | `Nama` | yes | |
| B | `Email` | yes | **Key.** Unique among non-deleted users; must pass `Email` validation. |
| C | `Password` | cond. | Required in `Insert Only`. In `Update`: blank → keep existing; non-blank → re-hash & overwrite. |
| D | `Peran` | yes | `admin`, `guru_bk`, or `wali_kelas`. |
| E | `NIP` | no | |
| F | `No. Telepon` | no | |

- The `admin`-last protection from `users.delete` is **not** relevant to import
  (import never deletes). No special-casing needed beyond role enum validation.
- Mode behaviour:
  - `Insert Only`: existing `Email` → error row.
  - `Update`: existing `Email` → update `Nama`/`Peran`/`NIP`/`No. Telepon` and
    (if non-blank) `Password`; else insert.

---

## 6. Import Service API

`app/imports.py` exposes one function per entity plus one template builder per
entity. Each `import_*` function reads `Mode` and `Jumlah Baris` **from the
workbook itself** (so the route only hands it the uploaded file).

```python
# app/imports.py
from dataclasses import dataclass, field


@dataclass
class ImportResult:
    ok: bool                       # True iff every row validated and was applied
    created: int = 0
    updated: int = 0
    errors: list[tuple[int, str]] = field(default_factory=list)  # (row_no, msg)
    mode: str = ""                 # echoed back for the UI
    row_count: int = 0             # echoed back (Jumlah Baris)


def import_students(file_storage) -> ImportResult: ...
def import_classes(file_storage) -> ImportResult: ...
def import_teachers(file_storage) -> ImportResult: ...


def build_students_template() -> bytes: ...
def build_classes_template() -> bytes: ...   # pre-fills Daftar Wali Kelas
def build_teachers_template() -> bytes: ...
```

**Contract (D10):** `import_*` does all DB work inside the caller's session and
**commits once** only when `ok` — but because of all-or-nothing it actually
validates *all* rows first (no writes), then applies them in a single pass and
commits. On any error it touches nothing. The route does **not** commit again
(function owns the commit so it can roll back cleanly); this is a deliberate,
documented exception to the "caller commits" rule, justified by the
validate-then-apply shape. (Alternative: function returns the plan, route
commits — either is fine; pick one during implementation and keep it
consistent across all three entities.)

---

## 7. Processing Algorithm (all-or-nothing)

Applies identically to all three entities; only the per-row validator and the
key/upsert differ.

```text
def import_<entity>(file_storage) -> ImportResult:
    wb   = openpyxl.load_workbook(file_storage, read_only=True, data_only=True)
    ws   = wb.active
    mode = ws["B1"].value              # "Insert Only" | "Update"
    n    = ws["B2"].value              # Jumlah Baris (int)
    header_row = 4
    first_data = 5

    result = ImportResult(ok=False, mode=mode, row_count=n)
    errors = []

    # --- 0. validate config cells -------------------------------------
    if mode not in ("Insert Only", "Update"):
        errors.append((0, "Mode tidak valid (harus 'Insert Only' atau 'Update')."))
        result.errors = errors; return result
    if not isinstance(n, int) or n <= 0:
        errors.append((0, "Jumlah Baris tidak valid (harus bilangan bulat > 0)."))
        result.errors = errors; return result

    # --- 1. parse + validate every row (NO db writes yet) -------------
    plans = []                        # list of ("insert"|"update", model_obj)
    for i in range(n):
        row_no = first_data + i
        cells = [ws.cell(row=row_no, column=c).value for c in range(1, ncols+1)]
        if all(blank(c) for c in cells):
            errors.append((row_no, "Baris kosong.")); continue
        try:
            obj, action = _validate_<entity>(cells, mode)   # raises RowError(msg)
        except RowError as e:
            errors.append((row_no, str(e))); continue
        plans.append((action, obj))

    if errors:
        result.errors = errors; return result           # all-or-nothing: stop

    # --- 2. apply within one transaction ------------------------------
    for action, obj in plans:
        if action == "insert":
            db.session.add(obj); result.created += 1
        else:
            # update path already applied field assignments in _validate_*;
            # obj is the tracked existing instance.
            result.updated += 1
    db.session.commit()               # single commit (or rollback on raise)
    result.ok = True
    return result
```

`_validate_<entity>(cells, mode)` is responsible for:

1. Type/format checks (required present, enum in allowed set, date parseable,
   email well-formed, integer where expected).
2. Cross-table resolution (`Kelas` → `class_id`, `Wali Kelas` → `User` row).
3. **Key lookup** against the live DB to decide `insert` vs `update`:
   - `Insert Only` + key exists → `RowError("… sudah ada (Mode: Insert Only).")`
   - `Update` + key exists → load the existing row, copy editable fields onto
     it, return `("update", existing_instance)`.
   - key absent → build a new model instance, return `("insert", new_instance)`.
4. Raising `RowError(message)` on any problem (the loop converts that to a
   `(row_no, message)` entry).

**Encoding (R9):** user strings are stored **raw**; do not `sanitize()` on
write. Existing display paths (DataTables `/data` endpoints) already `sanitize()`
on output.

---

## 8. Template Generators

`build_*_template()` returns the `.xlsx` bytes for the download route. Each:

1. Creates a workbook, writes the two config cells (`A1/B1`, `A2/B2`) with a
   sensible default (`B1 = "Insert Only"`, `B2 = 0`).
2. Writes the header row at row 4, bold + frozen.
3. Sets sensible column widths and adds a short inline note row (e.g. row 3 in
   column A: `"* wajib diisi"`) — cosmetic.
4. For **classes**: queries `User` where `role = 'wali_kelas'`,
   `is_deleted = False`, order by name; writes the `Daftar Wali Kelas`
   reference block starting at column F (header at F5, data F6+). Styles it
   grey to signal "reference only".
5. For **students**: queries `Class` where `is_deleted = False`, order by
   `grade_level` then `name` (same filter as `students._class_choices()`);
   writes the `Daftar Kelas` reference block starting at column O (header at
   O5, data O6+) with columns `ID | Nama Kelas | Tingkat | Wali Kelas`. Same
   grey "reference only" styling.
6. Returns `BytesIO` bytes.

The download route wraps the bytes in `send_file(..., as_attachment=True,
download_name="template_siswa.xlsx")` — a §6.2-style R1 exemption (binary, not
HTML), exactly like the existing PDF endpoints.

---

## 9. Routes & RBAC

Two new routes per blueprint. Auth decorator stays outermost; the binary
template download returns `send_file` (R1-exempt).

### students (`app/blueprints/students.py`)

```python
@bp.route("/impor/template")
@login_required
@role_required("admin", "guru_bk")
def impor_template():
    return send_file(BytesIO(build_students_template()),
                     mimetype=...)  # as_attachment, download_name="template_siswa.xlsx"

@bp.route("/impor", methods=["GET", "POST"])
@login_required
@role_required("admin", "guru_bk")
def impor():
    form = ImportForm()
    if request.method == "GET":
        return hx_render("students/impor.html", form=form, result=None)
    if not form.validate_on_submit():
        return hx_render("students/impor.html", form=form, result=None,
                         error="File tidak terbaca.")
    result = import_students(form.file.data)
    if not result.ok:
        return hx_render("students/impor.html", form=form, result=result)
    return hx_render("students/index.html", push_url="students.index",
                     success=f"Impor siswa selesai: {result.created} baru, "
                             f"{result.updated} diperbarui.")
```

### classes (`app/blueprints/classes.py`) — `role_required("admin")` only.
### users (`app/blueprints/users.py`)  — `role_required("admin")` only.

Same shape; each calls its own `import_<entity>` and renders its own
`<entity>/impor.html`.

---

## 10. Upload Form & UI

**`ImportForm`** (`app/forms.py`) — one shared class:

```python
class ImportForm(FlaskForm):
    file = FileField("File Excel (.xlsx)", validators=[FileRequired()])
    submit = SubmitField("Impor")
```

MIME is **not** pre-validated by WTForms; `import_*` will surface a clean error
if `openpyxl` cannot parse the file (wrap `load_workbook` in a try/except →
top-level error "File bukan Excel yang valid").

**`<entity>/impor.html`** (dual-mode header per §10.1, R3):

- A row of buttons: **"Unduh Template"** (link to `…_template`) and a back link
  to the index.
- The upload form (POST + `hx-post`, R5/R6).
- When `result` is present and `not result.ok`: a scrollable error table
  (`No. Baris | Pesan`) rendered from `result.errors`, plus a summary line
  showing `result.mode` and `result.row_count`.
- Inline guidance: explain `Mode` (`Insert Only` vs `Update`) and that
  `Jumlah Baris` must equal the exact number of data rows.

**Index pages** (`students/index.html`, `classes/index.html`, `users/index.html`):
add an **"Impor"** button next to the existing "Tambah" button, gated by the
same role check as `tambah`.

---

## 11. Testing Plan

New file `tests/test_imports.py`. Build in-memory workbooks with `openpyxl`,
POST to each route via the `client` fixture (CSRF already disabled in
`conftest.py`), log in via the existing `login()` helper.

**Per entity, cover:**

1. Template download → 200, content-type is xlsx, `openpyxl.load_workbook`
   parses it, header row matches spec. Reference tables are present and
   pre-filled: classes template contains the seeded `wali_kelas` users;
   students template contains the seeded non-deleted classes.
2. `Insert Only` with all-new rows → `created == N`, `updated == 0`, rows
   present in DB.
3. `Update` re-import of the same keys → `updated == N`, `created == 0`,
   fields changed.
4. `Insert Only` with a duplicate key → `ok == False`, error list names the
   row, **nothing** written (all-or-nothing).
5. All-or-nothing: one bad row among good ones → whole file rejected, zero
   rows written, error list includes the bad row number.
6. Invalid `Mode` cell and invalid/missing `Jumlah Baris` → top-level error,
   nothing imported.
7. Cross-table resolution failure (unknown `Wali Kelas` id / unknown `Kelas`)
   → row error, whole file rejected.
8. RBAC: `wali_kelas` → 403 on classes/users import routes; unauthenticated →
   redirect to login. Students import allowed for `guru_bk` but not
   `wali_kelas`.

Use the existing `conftest.py` factories (`make_user`, `make_class`,
`make_student`) to seed pre-existing rows for the duplicate/update cases.

---

## 12. Open Decisions

These need a ruling before/during implementation. Defaults below are what the
plan currently assumes.

- **O-1 — Students' `Kelas` resolution.** ✅ **RESOLVED: by ID.** The `Kelas`
  column holds a `classes.id` (mirrors D-5), and the students template embeds a
  pre-filled `Daftar Kelas` reference block (see §5.1). Chosen over name-based
  lookup because `Class.name` is not unique in the schema (`models.py:69`).

- **O-2 — Classes natural key for `Update`.** Currently planned as
  **`Nama Kelas` alone**. If duplicate class names are allowed to exist, an
  `Update` against an ambiguous name is rejected with a row error
  ("nama kelas dipakai lebih dari satu kelas"). Alternative: use the composite
  `(Nama Kelas, Tingkat)` as the key. → *Lean composite; confirm.*

- **O-3 — Who commits.** Either the service function commits (validate-then-
  apply with a single commit/rollback) **or** it returns a plan and the route
  commits (strict D10). Pick one and keep it uniform across all three
  entities. → *Lean: service commits (simpler rollback).*

- **O-4 — `Peran` allowed values on teacher import.** Allow any of
  `admin/guru_bk/wali_kelas` (route stays admin-only regardless). Confirm.

---

## 13. Implementation Order

1. `uv add openpyxl` (update `pyproject.toml` + `uv.lock`).
2. `app/imports.py`: `ImportResult` + `build_*_template()` (template generation
   first — lets you hand-craft test files visually).
3. `ImportForm` in `app/forms.py`.
4. Per entity, in this order: **teachers → classes → students** (teachers first
   because classes reference them; classes before students because students
   reference classes):
   - `import_<entity>()` + `_validate_<entity>()`.
   - Routes (`impor_template`, `impor`) + `<entity>/impor.html`.
   - "Impor" button on `<entity>/index.html`.
5. `tests/test_imports.py` — implement cases in §11 as each entity lands.
6. Lint + full test run (§14).

---

## 14. Verification

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -n auto          # long timeout per AGENTS.md
```

Manual smoke (`uv run flask run --debug`, log in as admin):

1. Download each template; confirm config cells, headers, and (for classes) the
   `Daftar Wali Kelas` reference block.
2. Fill a students template, set `Mode = Insert Only`, `Jumlah Baris = <N>`,
   upload → success, counts match.
3. Re-upload with `Mode = Update`, tweak a row → `updated` count matches.
4. Re-upload with `Mode = Insert Only` → whole file rejected with per-row
   "sudah ada" errors; verify DB unchanged.
5. Repeat the equivalent for classes (with real `Wali Kelas` ids from the
   reference block) and teachers.

---

*This document covers imports only. Excel reports will be specified in a
separate plan.*
