# CLASSES_MODIFICATION.md — Multi-Year Classes / Enrollment / Rollover

> **Companion to [`SICAPEL_IMPLEMENTATION_PLAN.md`](./SICAPEL_IMPLEMENTATION_PLAN.md).**
> The high-level contracts (domain rules, schema, service signatures) live in
> the main plan: §1.9, §2.3, §2.4, §2.13, §8.6, §8.7, §13.7, §13.8, §14.1.
> This document holds the **migration, file-by-file change list, UI design,
> test matrix and task breakdown** needed to implement it.
>
> **Status:** IMPLEMENTED — all CM1–CM7 tasks green; `uv run pytest -n auto`
> (223 tests) and `uv run ruff check .` clean. PostgreSQL smoke is the only
> remaining pre-production step (§11).

---

## 1. Problem

The base schema treats `students.class_id` and `classes.homeroom_teacher_id`
as timeless facts:

- `students.class_id` was annotated *"current class only (v1 — historical
  enrollments deferred)"* (old §2.4).
- `classes` has no academic-year dimension.

For a school that runs the system **continuously**, this breaks on three
points (see main plan §1.9 for the full rationale):

1. **Grade promotion** — grade 10 → 11 → 12 each year; grade 12 graduates.
2. **Homeroom-teacher rotation** — a different wali kelas per class each year.
3. **Historical reporting** — "which class / which wali kelas was this student
   under in academic year Y" must stay answerable after rollover.

Disciplinary data is already year-stamped (`violation_records.academic_year_id`
etc.) and points accumulate continuously (§1.3). Only **placement** was
missing a history dimension.

---

## 2. Confirmed decisions

| # | Decision |
|---|---|
| D-C1 | **Full placement history** via a new `class_enrollments` junction table (Option B). |
| D-C2 | **Automated rollover** — admin "start new academic year" action (`promote_academic_year`). |
| D-C3 | **Wali kelas sees only their current class** (including its full disciplinary history). Existing scoping logic (`scope_students_to_role`) is unchanged. |
| D-C4 | **Mid-year homeroom-teacher change = overwrite** the current-year enrollment's `homeroom_teacher_id` (+ cache). Within-year tenure splits are NOT tracked (v1). |
| D-C5 | **Target classes must pre-exist.** Rollover maps students into existing classes; it does not auto-create. |
| D-C6 | **Caches stay.** `students.class_id` and `classes.homeroom_teacher_id` are kept as "current" caches, maintained by the services. This keeps every existing R12 join valid (zero changes to `scope_students_to_role`, dashboard/violations/students scoping). |
| D-C7 | **No snapshot columns on `violation_records`.** The class/teacher *as of a violation* is resolved by joining `(student_id, academic_year_id)` → `class_enrollments`. |

---

## 3. Target data model

### 3.1 New table `class_enrollments`

```
class_enrollments
  id                  PK
  student_id          FK → students          (indexed)
  class_id            FK → classes
  academic_year_id    FK → academic_years    (indexed)
  homeroom_teacher_id FK → users             (wali kelas AS OF that year)
  is_active           bool    default false
  created_at          timestamp

  UNIQUE (student_id, academic_year_id)        -- one placement per student per year
  INDEX  (class_id, academic_year_id)          -- "who was in class X in year Y"
  INDEX  (homeroom_teacher_id)                 -- wali-kelas history
```

Source of truth for *who was in which class* and *who was the wali kelas* in
any given year. `is_active=true` marks the student's **current** placement
(exactly one per student — the row whose `academic_year_id` is the active
year).

### 3.2 Cache columns (unchanged schema, new semantics)

| Column | Semantics after this change |
|---|---|
| `students.class_id` | **cache** — equals `class_enrollments.class_id` for the active year. |
| `classes.homeroom_teacher_id` | **cache** — equals the current-year `class_enrollments.homeroom_teacher_id` for that class. |

Both are written by `enroll_student` / `promote_academic_year`; verified by
`recompute_current_placement`.

### 3.3 Invariants

1. **One active enrollment per student.** Enrolling a student flips their
   prior `is_active=true` rows to `false`.
2. **Cache ⇄ active enrollment agreement.** For the active academic year,
   `students.class_id` and `classes.homeroom_teacher_id` MUST match the
   `is_active=true` enrollment row.
3. **Graduated / transferred students** keep their last `class_id` cache (no
   new enrollment on rollover); `class_enrollments` preserves the history.
4. **No deletion.** Enrollment rows are never hard-deleted; corrections are
   in-place updates (mid-year edit path) so the UNIQUE constraint holds.

---

## 4. Service contracts

All in `app/services.py`. Each accepts an explicit `session` and **does not
commit** (caller commits — D10).

### 4.1 `enroll_student`  (main plan §8.6)

```python
def enroll_student(*, student_id, class_id, academic_year_id,
                   homeroom_teacher_id, session) -> ClassEnrollment:
```

Behavior:
- Upsert on `(student_id, academic_year_id)`: if a row exists, overwrite its
  `class_id` / `homeroom_teacher_id` (the mid-year edit path, D-C4); else
  insert.
- Set this row `is_active=True`; set the same student's other-year rows
  `is_active=False`.
- If `academic_year_id` is the active year → update caches
  (`students.class_id = class_id`; `classes.homeroom_teacher_id =
  homeroom_teacher_id` for that class).

### 4.2 `promote_academic_year`  (main plan §8.7)

```python
def promote_academic_year(*, source_year_id, target_year_id, class_map,
                          graduate_grade=12, session) -> dict:
    # class_map: {source_class_id: (target_class_id, new_homeroom_teacher_id)}
    # returns:  {'graduated': [...], 'promoted': [...], 'skipped': [...]}
```

Per source-class cohort, for each student whose **active** enrollment is in
`source_year_id` and whose `status == 'active'`:
- `source_class.grade_level == graduate_grade` → `student.status='graduated'`
  (no new enrollment).
- else → create `ClassEnrollment(student_id, class_id=target_class_id,
  academic_year_id=target_year_id, homeroom_teacher_id=new_teacher,
  is_active=True)`; flip the prior enrollment `is_active=False`; update
  `students.class_id` cache; update the target `classes.homeroom_teacher_id`
  cache.

Then `target_year.is_active=True`, `source_year.is_active=False`.

**Guards (raise):**
- `target_year_id != source_year_id`.
- target academic year exists.
- target year has **no** existing enrollments (idempotency).
- every `source_class_id` in `class_map` maps to a pre-existing
  `target_class_id` (D-C5).

### 4.3 `recompute_current_placement(student_id, session)`

Backstop: re-derives `students.class_id` and `classes.homeroom_teacher_id`
from the active-year `class_enrollments` row. Mirrors `recompute_summary()`
(§2.11/§8.4). Used after manual data fixes / voids.

---

## 5. Migration & backfill

Single Alembic migration produced by `uv run flask db migrate -m "add
class_enrollments"`, then hand-edit `upgrade()` to add the backfill (Autogenerate
cannot invent it):

```python
def upgrade():
    # 1. op.create_table('class_enrollments', ...) with all columns/constraints
    # 2. op.create_unique_constraint('uq_enrollment_student_year',
    #       'class_enrollments', ['student_id', 'academic_year_id'])
    # 3. op.create_index('ix_enrollment_class_year',
    #       'class_enrollments', ['class_id', 'academic_year_id'])
    # 4. op.create_index('ix_enrollment_teacher',
    #       'class_enrollments', ['homeroom_teacher_id'])
    #
    # 5. BACKFILL (one row per existing student, active year):
    op.execute("""
        INSERT INTO class_enrollments
            (student_id, class_id, academic_year_id,
             homeroom_teacher_id, is_active, created_at)
        SELECT s.id, s.class_id, ay.id,
               c.homeroom_teacher_id, 1, CURRENT_TIMESTAMP
        FROM students s
        JOIN classes c ON c.id = s.class_id
        CROSS JOIN (SELECT id FROM academic_years WHERE is_active = TRUE LIMIT 1) ay
        WHERE s.is_deleted = FALSE
          AND s.class_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM class_enrollments ce
              WHERE ce.student_id = s.id AND ce.academic_year_id = ay.id
          );
    """)
    # caches already match by construction — no further sync needed.


def downgrade():
    op.drop_index('ix_enrollment_teacher', table_name='class_enrollments')
    op.drop_index('ix_enrollment_class_year', table_name='class_enrollments')
    op.drop_constraint('uq_enrollment_student_year', 'class_enrollments', type_='unique')
    op.drop_table('class_enrollments')
```

**Notes:**
- `CROSS JOIN ... LIMIT 1` assumes exactly one active academic year (§2.1). If
  none is active, the backfill is a no-op and enrollments are created on first
  student edit / rollover.
- SQLite (dev) and PostgreSQL (prod) both accept the SQL above; `CURRENT_TIMESTAMP`
  is portable.
- Smoke-test the upgrade against an empty PostgreSQL before deploying (§15
  enum-migration risk mitigation).

---

## 6. File-by-file change list

Legend: ➕ add, ✏️ edit, (no change) = explicitly verified unchanged.

### `app/models.py`  (✏️)
- ➕ `class ClassEnrollment(db.Model)` with columns/constraints in §3.1.
- ➕ relationships: `Student.enrollments`, `Class.enrollments`,
  `AcademicYear.enrollments`, and backrefs on `User`.
- ➕ convenience: `Student.current_enrollment` hybrid/property → the
  `is_active=True` row (or the active-year row).
- (no change) to `Class` / `Student` columns — they stay as caches.
- Document cache semantics in docstrings.

### `app/services.py`  (✏️)
- ➕ `enroll_student(...)` (§4.1).
- ➕ `promote_academic_year(...)` (§4.2).
- ➕ `recompute_current_placement(student_id, session)` (§4.3).

### `app/forms.py`  (✏️)
- (no change) to `StudentForm.class_id` (`SelectField`) — still writes the
  cache; the route now also calls `enroll_student`.
- (no change) to `ClassForm.homeroom_teacher_id`.
- ➕ `RolloverForm` (or a plain FieldList of `RolloverClassRowForm`) — one row
  per source class: `source_class_id` (hidden), `target_class_id` (Select),
  `new_homeroom_teacher_id` (Select). See §7.

### `app/blueprints/students.py`  (✏️)
- ✏️ `tambah` / `edit`: after writing `student.class_id` cache, call
  `enroll_student(student_id=..., class_id=form.class_id.data,
  academic_year_id=current_academic_year().id,
  homeroom_teacher_id=<looked up from the chosen class's
  homeroom_teacher_id>, session=db.session)` inside the same transaction,
  then `db.session.commit()`.
- (no change) to scoping (`scope_students_to_role`) — reads caches.

### `app/blueprints/classes.py`  (✏️)
- ✏️ `tambah` / `edit`: when `homeroom_teacher_id` changes, update the
  current-year enrollments of that class's students + the
  `classes.homeroom_teacher_id` cache (the mid-year-edit path, D-C4). Use
  `enroll_student` per student OR a bulk `UPDATE class_enrollments ... WHERE
  class_id=? AND academic_year_id=?`.
- (no change) to list / delete / restore.

### `app/blueprints/academic_years.py`  (✏️)
- ➕ `GET /tahun-ajaran/rollover` — render `academic_years/rollover.html` with
  a `RolloverForm` pre-populated from the current active year (one row per
  source class; target class defaulted by `grade_level+1` + same suffix;
  teacher blank). See §7.
- ➕ `POST /tahun-ajaran/rollover` — validate, call `promote_academic_year`,
  commit, re-render with a result summary (`graduated` / `promoted` /
  `skipped` counts). `@role_required("admin")`.

### `app/helper.py`  (no change)
- `scope_students_to_role` (`helper.py:68`) keeps joining
  `Student.class_id → Class.homeroom_teacher_id`. This is correct because
  those are the maintained current caches (D-C6).

### `app/seed.py`  (✏️)
- ✏️ dev-seed class block (`seed.py:293`): after creating classes + students,
  emit one `ClassEnrollment` per student for the active year
  (`homeroom_teacher_id` = the class's teacher). Idempotent (skip if exists).

### Templates  (✏️ / ➕)
- ➕ `app/templates/academic_years/rollover.html` — dual-mode header (R3) +
  the `RolloverForm` table + a confirm button. DataTables not required (small
  form); if a table is used, wrap init in the destroy-guard IIFE (R11).
- (no change) to `classes/index.html`, `students/form.html` — they read caches.

### `migrations/versions/<new>.py`  (➕)
- Hand-edited migration per §5.

### `tests/`  (➕ / ✏️)
- ➕ `tests/test_enrollments.py` (§8.1).
- ➕ `tests/test_rollover.py` (§8.2).
- ✏️ `tests/factories.py` — add a `ClassEnrollmentFactory`; ensure
  `StudentFactory` / `ClassFactory` still produce a consistent active-year
  enrollment when tests need one.

---

## 7. Rollover UI design

Route: `/tahun-ajaran/rollover` (admin only), inside `academic_years` blueprint.

**Step 1 — preconditions (GET):**
- There must be an active academic year (the *source*).
- There must be a candidate *target* academic year (existing, not active, no
  enrollments yet). If none, show a notice linking to "Tambah Tahun Ajaran".
- All *target* classes (e.g. XI IPA 1, XII IPA 1) must already exist (D-C5).
  Missing target classes are listed with a "create them first" notice.

**Step 2 — mapping form (GET renders, POST commits):**

| Source class (active year) | Grade | → Target class | New wali kelas |
|---|---|---|---|
| X IPA 1  (budi)  | 10 | [XI IPA 1 ▾] | [siti ▾] |
| XI IPA 1 (siti)  | 11 | [XII IPA 1 ▾] | [ahmad ▾] |
| XII IPA 1(ahmad) | 12 | (graduates — no target) | — |

Defaults: target class = first class with `grade_level = src.grade+1` and a
matching suffix; teacher = blank (admin must confirm). Grade-12 rows are
display-only (they graduate).

**Step 3 — commit (POST):**
- Validate the form (every non-graduating row has target class + teacher).
- Call `promote_academic_year(...)`, commit.
- Re-render with counts: *"Lulus: 7, Naik kelas: 14, Dilewati: 2"*.
- Idempotency guard surfaces as a validation error if the target year already
  has enrollments.

**Confirm-before-commit:** the POST is a two-step (form re-renders a
confirmation panel on first POST, commits on a `confirm=1` second POST) — or a
single POST guarded by a modal "Yakin?" (pattern already used by delete flows,
see §10.6 list-page modal). Implementer's choice; keep it within R1/R5.

---

## 8. Test matrix

All via `uv run pytest` (in-memory SQLite). Run with `uv run pytest -n auto`
for parallelism (AGENTS.md).

### 8.1 `tests/test_enrollments.py`
1. `enroll_student` creates one active enrollment; `students.class_id` cache
   matches.
2. Re-enrolling same `(student_id, academic_year_id)` updates in place — no
   duplicate, no IntegrityError.
3. **Backstop:** directly inserting a second row for the same
   `(student_id, academic_year_id)` raises `IntegrityError` (verifies UNIQUE;
   mirrors `test_letter_numbering.py` case 5).
4. Editing a student's class via the `students` blueprint keeps cache +
   enrollment in sync.
5. Enrolling in a new year flips the prior year's row `is_active=False`
   (exactly one active enrollment per student).

### 8.2 `tests/test_rollover.py`
1. grade 12 → `status='graduated'`, no new enrollment.
2. grade 10 → 11, grade 11 → 12 → new target-year enrollment
   (`is_active=True`); prior enrollment `is_active=False`.
3. Caches (`students.class_id`, `classes.homeroom_teacher_id`) reflect the
   target year after rollover.
4. Target year `is_active=True`, source `is_active=False`.
5. Idempotency guard refuses if target year already has enrollments.
6. Target classes must pre-exist — missing target raises (no auto-create).
7. `recompute_current_placement` restores a deliberately-desynced cache.

### 8.3 Regression (no new files)
- `test_routes.py`: wali kelas still scoped to current class only; rollover
  endpoint is admin-only (403 for others).
- `test_services.py`: unchanged — points/SP logic unaffected (no snapshot on
  `violation_records`).

---

## 9. Task breakdown (CM1–CM7)

Dependency order. Each task ends with a verification command.

| # | Task | Files | Verify | Blocked by |
|---|---|---|---|---|
| **CM1** | `ClassEnrollment` model + relationships + migration (create table + backfill, §5). | `models.py`, `migrations/` | `uv run flask db upgrade` clean on a fresh dev SQLite; `sqlite3 instance/sicapel.sqlite ".schema class_enrollments"` shows UNIQUE + both indexes; backfilled row count == active students. | — |
| **CM2** | `services.enroll_student` + `services.recompute_current_placement` + tests. | `services.py`, `tests/test_enrollments.py` | `uv run pytest tests/test_enrollments.py -v` green (5 cases). | CM1 |
| **CM3** | Wire `students` create/edit + `classes` homeroom-teacher edit to keep enrollments + caches in sync. | `blueprints/students.py`, `blueprints/classes.py` | `uv run pytest tests/test_enrollments.py tests/test_routes.py -v` green; manual: edit a student's class, confirm `class_enrollments` row updated. | CM2 |
| **CM4** | `services.promote_academic_year` + tests. | `services.py`, `tests/test_rollover.py` | `uv run pytest tests/test_rollover.py -v` green (7 cases). | CM2 |
| **CM5** | Rollover UI (preview → commit) + form + template. | `blueprints/academic_years.py`, `forms.py`, `templates/academic_years/rollover.html` | Manual: create next year + target classes, run rollover, confirm counts + caches; `test_routes.py` green. | CM4 |
| **CM6** | `seed.py` emits enrollments; optional per-class-per-year report view if desired. | `seed.py` | `rm -f instance/sicapel.sqlite && uv run flask db upgrade && uv run flask seed --dev`; enrollments exist for all active students. | CM3 |
| **CM7** | Audit + PostgreSQL smoke. | — | `uv run ruff check .` clean; `uv run flask db upgrade` against an empty PostgreSQL succeeds; `uv run pytest -n auto` full suite green; confirm `scope_students_to_role` (helper.py:68) still reads caches and passes RBAC tests. | CM1–CM6 |

**Definition of done:** all CM tasks green, `CLASSES_MODIFICATION.md` status
flipped to "Implemented", main plan §14.1 marked complete.

---

## 10. Known limitations / out of scope (v1)

- **Mid-year tenure split** (D-C4): if a wali kelas is replaced mid-year, the
  old teacher's tenure for that year is overwritten, not preserved. Accepted.
- **Repeating / transferring students** are handled as manual edits after
  rollover (no bulk path).
- **Class auto-creation** (D-C5): target classes must pre-exist. No silent
  creation from name patterns.
- **Reports per class per year** beyond the existing dashboard are not added
  here; the data model now supports them — a future task can add the views.
- **Soft-delete of enrollments** is not modeled; corrections are in-place
  updates (keeps the UNIQUE constraint clean).

---

## 11. Rollout notes

- Run CM1 migration on dev first (`uv run flask db upgrade`), then against a
  staging PostgreSQL copy of prod data to validate the backfill row count.
- The change is **backward-compatible at the query level**: every existing
  scope/join reads cache columns that remain populated, so deploying the
  schema migration ahead of the services is safe (caches already hold correct
  current values).
- Rollover is a manual admin action — there is no cron/automatic promotion.
- Back up prod (`pg_dump`) before running the migration in production.
