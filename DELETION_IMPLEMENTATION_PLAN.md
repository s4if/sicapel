# Hybrid Delete Implementation Plan

## Overview

Add hybrid delete (hard-delete when safe, soft-delete as fallback) to the 5
admin-maintained entities: **Students, Classes, Users, Academic Years, and
Violation Types**.

This is a **plan only**. It documents every change required before any code is
written, including invariants, read-path filters, session invalidation, and a
concrete test matrix.

---

## Core Logic

When **"Hapus"** is clicked:

1. Run the entity's pre-delete **guards** (§"Invariants"). Reject if any guard
   fails (e.g. deleting the active academic year, deleting self).
2. Check for related records referencing this entity. **Related-record counts
   include ALL physical rows** — voided / inactive / soft-deleted dependents
   still count, because referential integrity is physical, not logical.
3. **No related records** → hard-delete (permanent removal, clean data).
4. **Related records exist** → soft-delete (set `is_deleted = True`).

When **"Pulihkan"** is clicked:

1. Set `is_deleted = False`.

### Notification messages

Messages use a per-entity **display accessor** and **label** (see §"Per-entity
spec") so they never hit `AttributeError` (e.g. `AcademicYear` exposes `year`,
not `name`). The display value is captured **before** any DB mutation and is
passed through `sanitize()` when rendered in HTML.

- Hard-delete: *"{label} {display} berhasil dihapus secara permanen."*
- Soft-delete: *"{label} {display} ditandai sebagai dihapus ({detail})."*
- Restore: *"{label} {display} berhasil dipulihkan."*

where `detail` is a comma-joined list of `{relation_label}: {count}` for counts
`> 0`, e.g. `"pelanggaran: 3, surat peringatan: 1"`.

---

## Invariants (cross-cutting rules)

These must hold at all times. Each route/guard below exists to enforce one.

| # | Invariant | Enforced by |
|---|---|---|
| I1 | `is_deleted` is the **only** "retired from master data" flag. It is independent of every other flag (`Student.status`, `ViolationType.is_active`, `AcademicYear.is_active`, `ViolationRecord.is_void`, …). Deleting an entity **never** mutates any other flag, and vice-versa. | Model + delete routes |
| I2 | A soft-deleted entity is **excluded from every live read path**: dropdowns/choice queries, dashboard stats, rankings, point aggregation, and `by_class` lookups. Historical FK references (e.g. an old `ViolationRecord.recorded_by`) are **left untouched**. | §"Read-path audit" |
| I3 | The **currently-active `AcademicYear`** (`is_active=True`) cannot be deleted (hard or soft). It must first be deactivated / superseded. | `academic_years.delete` guard |
| I4 | An admin **cannot delete their own account** (`current_user.id`) and **cannot delete the last remaining admin**. | `users.delete` guard |
| I5 | A soft-deleted **User** loses access **immediately**, not at next login. Every authenticated request re-checks the flag. | §"Session invalidation" |
| I6 | Related-record checks count **all physical rows** pointing at the entity, regardless of those rows' own void/active/deleted state. This preserves referential integrity (hard-delete never orphans a FK). | §"Related-record checks" |

### `Student.status` vs `Student.is_deleted` (clarification of I1)

`Student.status` (`active/expelled/graduated/transferred`) describes the
**academic lifecycle** and is used by existing filters (`by_class` filters
`status="active"`, `_student_choices` excludes `expelled`). `is_deleted`
describes **master-data retirement**. They are orthogonal:

- A deleted student keeps its `status` unchanged.
- Dropdowns/queries add `is_deleted=False` **on top of** existing `status`
  filters — they do not replace them.

---

## Database Changes

### Model (`app/models.py`)

Add a dedicated `is_deleted` column to **all 5** models. **Do not reuse
`ViolationType.is_active`** — that flag already means "admin deactivated this
type for use" and is editable via `ViolationTypeForm` (`forms.py:142`).
Reusing it would conflate "deactivated" with "deleted" and cause `restore` to
silently flip a deliberately-deactivated type back to active (see §"Why not
reuse `is_active`").

| Model | Column | Type | Default | Nullable |
|---|---|---|---|---|
| `Student` | `is_deleted` | `db.Boolean` | `False` | `False` |
| `Class` | `is_deleted` | `db.Boolean` | `False` | `False` |
| `User` | `is_deleted` | `db.Boolean` | `False` | `False` |
| `AcademicYear` | `is_deleted` | `db.Boolean` | `False` | `False` |
| `ViolationType` | `is_deleted` | `db.Boolean` | `False` | `False` |

`AcademicYear.is_active` ("current year") and `ViolationType.is_active`
("active for use") remain unchanged and semantically distinct from
`is_deleted`.

#### Why not reuse `is_active` for ViolationType

`ViolationType.is_active` is a **form-editable** field. If "delete" also wrote
`is_active=False`, then:

- a deactivated type and a deleted type would be indistinguishable, and
- `restore` (set `is_active=True`) would override a **deliberate** deactivation.

A dedicated `is_deleted` keeps one boolean = one meaning, and makes all 5
entities uniform. Choice queries for `ViolationType` keep the existing
`is_active=True` filter **and** add `is_deleted=False`.

### Migration

`flask_migrate.Migrate` is already wired in `create_app` (`app/__init__.py:54`),
but Alembic has never been initialized (no `migrations/` dir, no `alembic.ini`).
So the migration is a **two-step prerequisite**:

```bash
# Prerequisite (run once, ever — initializes migrations/ + alembic.ini)
flask db init

# The actual schema change for this feature
flask db migrate -m "add is_deleted to students, classes, users, academic_years, violation_types"
flask db upgrade
```

The model change alone is sufficient for the test suite, because
`tests/conftest.py:144` uses `db.create_all()` (which reads the models
directly and never touches Alembic). Production deployment must run the
upgrade.

---

## Per-entity spec

Used by delete/restore messages and `_row_actions` data attributes.

| Entity | Blueprint | Label (ID) | Display accessor | Guards (besides related-check) |
|---|---|---|---|---|
| Student | `students` | "Siswa" | `student.name` | none |
| Class | `classes` | "Kelas" | `cls.name` | none |
| User | `users` | "Pengguna" | `user.name` | I4: not self, not last admin |
| AcademicYear | `academic_years` | "Tahun ajaran" | `ay.year` | I3: not the active year |
| ViolationType | `violation_types` | "Jenis pelanggaran" | `vt.name` | none |

---

## Related-record checks (per delete route)

Each check returns a `dict[str, int]` of `{relation_label: count}`. Counts
include void / inactive / soft-deleted rows (invariant I6).

| Entity | Check these for related records |
|---|---|
| **Student** | `ViolationRecord.student_id`, `WarningLetter.student_id`, `ExpulsionRecommendation.student_id`, `PointAmnesty.student_id`, `StudentPointSummary.student_id` |
| **Class** | `Student.class_id` |
| **User** | `Class.homeroom_teacher_id`, `ViolationRecord.recorded_by`, `ViolationType.created_by`, `WarningLetter.issued_by`, `ExpulsionRecommendation.issued_by`, `PointAmnesty.recorded_by`, `Document.uploaded_by` |
| **AcademicYear** | `ViolationRecord.academic_year_id`, `WarningLetter.academic_year_id`, `ExpulsionRecommendation.academic_year_id`, `PointAmnesty.academic_year_id` |
| **ViolationType** | `ViolationRecord.violation_type_id` |

Example for Student (returns labels for the detail message):

```python
def _related_counts(student_id):
    from ..models import (
        ViolationRecord, WarningLetter, ExpulsionRecommendation,
        PointAmnesty, StudentPointSummary,
    )
    return {
        "pelanggaran": ViolationRecord.query.filter_by(student_id=student_id).count(),
        "surat peringatan": WarningLetter.query.filter_by(student_id=student_id).count(),
        "rekomendasi ekspulsi": ExpulsionRecommendation.query.filter_by(student_id=student_id).count(),
        "pemutihan": PointAmnesty.query.filter_by(student_id=student_id).count(),
        "ringkasan poin": StudentPointSummary.query.filter_by(student_id=student_id).count(),
    }
```

---

## Read-path audit (invariant I2)

Every query that **reads** these entities for live operation must exclude
`is_deleted=True`. Historical FK columns (e.g. `ViolationRecord.recorded_by`
pointing at a since-deleted user) are **not** filtered — they preserve the
audit trail.

Known sites (verified against current source):

| File:line | Query | Add filter |
|---|---|---|
| `app/blueprints/violations.py:24` | `_student_choices()` (`status != "expelled"`) | `+ Student.is_deleted.is_(False)` |
| `app/blueprints/violations.py:30` | `_violation_type_choices()` (`is_active=True`) | `+ ViolationType.is_deleted.is_(False)` |
| `app/blueprints/violations.py:39` | `_class_choices()` | `+ Class.is_deleted.is_(False)` |
| `app/blueprints/students.py:11` | `_class_choices()` | `+ Class.is_deleted.is_(False)` |
| `app/blueprints/students.py:178` | `by_class()` (`status="active"`) | `+ Student.is_deleted.is_(False)` |
| `app/blueprints/classes.py:11` | `_teacher_choices()` (`role == "wali_kelas"`) | `+ User.is_deleted.is_(False)` |
| `app/blueprints/dashboard.py:31` | `_scope_students()` (total/expelled counts) | `+ Student.is_deleted.is_(False)` |
| `app/blueprints/dashboard.py:40` | `_scope_summaries()` (SP/alert ranking) | join already present; add `Student.is_deleted.is_(False)` |
| Any `AcademicYear` dropdown builder (in violation/warning/amnesty/expulsion forms) | year choices | `+ AcademicYear.is_deleted.is_(False)` |

**Audit procedure before merging:** `grep` each model name across `app/` and
classify every hit as *historical FK* (leave alone) or *live selection /
aggregation* (add the filter). The table above is the verified starting set;
re-run the grep after implementation to catch anything added meanwhile.

> Note on `scope_students_to_role` (`helper.py:68`): the `is_deleted` filter is
> **additional to** the existing `wali_kelas` join scoping, not a replacement.

---

## Route Changes (5 blueprints)

Each blueprint gains a `delete` and `restore` route, an updated `_row_actions`,
and a filtered `data()`.

### 1. `/<int:id>/delete` (POST)

```python
@bp.route("/<int:id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete(id):
    from .. import db

    obj = db.get_or_404(Model, id)

    # --- Entity-specific guards (see §"Per-entity spec") ---
    # AcademicYear:  if obj.is_active:  -> reject (I3)
    # User:          if obj.id == current_user.id  -> reject (I4)
    #                if obj.role == "admin" and <2 admins remain> -> reject (I4)

    if obj.is_deleted:
        return hx_render("model/index.html",
            error="Data sudah dihapus sebelumnya.")

    display = _display(obj)          # capture BEFORE any mutation
    related = _related_counts(obj.id)
    related_count = sum(related.values())

    if related_count == 0:
        # Hard delete
        db.session.delete(obj)
        db.session.commit()
        return hx_render("model/index.html",
            push_url="model.index",
            success=f"{LABEL} {display} berhasil dihapus secara permanen.")
    else:
        # Soft delete
        obj.is_deleted = True
        db.session.commit()
        detail = ", ".join(f"{k}: {v}" for k, v in related.items() if v > 0)
        return hx_render("model/index.html",
            push_url="model.index",
            success=f"{LABEL} {display} ditandai sebagai dihapus ({detail}).")
```

Notes:

- `push_url="model.index"` is included for URL correctness on success, matching
  the existing `tambah`/`edit` routes (the original draft omitted it, which
  would leave the browser on a dead `…/<id>/delete` URL).
- `display` is captured before `db.session.delete` / the soft-delete write, so
  the message is correct in both branches and never accesses a detached/
  mutated object.

### 2. `/<int:id>/restore` (POST)

```python
@bp.route("/<int:id>/restore", methods=["POST"])
@login_required
@role_required("admin")
def restore(id):
    from .. import db

    obj = db.get_or_404(Model, id)
    if not obj.is_deleted:
        return hx_render("model/index.html", error="Data belum dihapus.")

    # AcademicYear restore guard: if restoring would create a second active
    # year, it does NOT — is_deleted is independent of is_active (I1).
    # No extra logic needed; document this so it isn't "fixed" later.

    obj.is_deleted = False
    db.session.commit()
    return hx_render("model/index.html",
        push_url="model.index",
        success=f"{LABEL} {_display(obj)} berhasil dipulihkan.")
```

### 3. `_row_actions()` — conditional actions

Non-deleted rows show view + edit + delete; soft-deleted rows show restore only.
The delete/restore buttons carry the `data-url` and `data-nama` attributes the
JS reads. Display values go through `sanitize()` (XSS hygiene; see
`tests/test_output_encoding.py`).

```python
def _row_actions(obj):
    delete_url = f"{obj.id}/delete"
    restore_url = f"{obj.id}/restore"
    nama = sanitize(_display(obj))

    if obj.is_deleted:
        return (
            f'<div class="btn-group btn-group-sm">'
            f'<button class="btn btn-outline-success" '
            f'onclick="pulihkan_data(this)" '
            f'data-url="{restore_url}" data-nama="{nama}">'
            f'<i class="bi bi-arrow-counterclockwise"></i></button>'
            f'</div>'
        )

    edit_url = f"{obj.id}/edit"
    detail_url = f"{obj.id}"
    return (
        f'<div class="btn-group btn-group-sm">'
        f'<a class="btn btn-outline-info" href="{detail_url}" '
        f'hx-get="{detail_url}" hx-target="#hx_content" hx-swap="innerHTML">'
        f'<i class="bi bi-eye"></i></a>'
        f'<a class="btn btn-outline-primary" href="{edit_url}" '
        f'hx-get="{edit_url}" hx-target="#hx_content" hx-swap="innerHTML">'
        f'<i class="bi bi-pencil"></i></a>'
        f'<button class="btn btn-outline-danger" onclick="hapus_data(this)" '
        f'data-url="{delete_url}" data-nama="{nama}">'
        f'<i class="bi bi-trash"></i></button>'
        f'</div>'
    )
```

### 4. `data()` — show all rows, flag deleted ones

The query returns **all** rows (no `is_deleted` filter) so admins can see and
restore deleted records. Each JSON row carries `"is_deleted": obj.is_deleted`;
the DataTables `createdRow` callback (§"Template Changes") styles it. This
mirrors the existing `alert` boolean + `createdRow` technique already used in
`dashboard.py:141`.

```python
rows.append({
    ...,
    "is_deleted": obj.is_deleted,
    "actions": _row_actions(obj),
})
```

For `students.data()` specifically, keep the existing `_base_query()` role
scoping; `is_deleted` visibility is **on top of** it (a `wali_kelas` still only
sees their own class's students, deleted or not).

---

## Session invalidation (invariant I5)

The login guard alone is insufficient: a soft-deleted user who is currently
logged in keeps a fully-privileged session until logout. Add an app-level
`before_request` check in `create_app` (`app/__init__.py`) so **every**
authenticated request re-validates the flag:

```python
from flask_login import current_user, logout_user

@app.before_request
def _reject_deleted_users():
    if current_user.is_authenticated and getattr(current_user, "is_deleted", False):
        logout_user()
        return hx_render("errors/403.html"), 403
```

Place this **after** `login_manager.init_app(app)`. It covers routes protected
only by `@login_required` (e.g. `auth.logout`, `auth.change_password`) that
`role_required` does not gate. Whitelist `/auth/*` and static if needed during
testing.

---

## Template Changes (5 index files)

Each `*/index.html` needs: a confirmation modal, the two JS confirm functions,
and a DataTables `createdRow` callback for deleted-row styling.

### Confirmation modal

Same idiom as the existing `modalVoid` in `warnings/index.html:41`, reusing the
shared `setConfirmBody` helper.

```html
<div class="modal fade" id="modalHapus" tabindex="-1">
  <div class="modal-dialog"><div class="modal-content">
    <div class="modal-header">
      <h5 class="modal-title">Konfirmasi</h5>
      <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
    </div>
    <div class="modal-body" id="modalHapusBody"></div>
    <div class="modal-footer">
      <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Batal</button>
      <form id="modalHapusForm" method="POST"
            onsubmit="bootstrap.Modal.getInstance(document.getElementById('modalHapus')).hide()"
            style="display:inline"
            hx-target="#hx_content" hx-swap="innerHTML">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
        <button type="submit" class="btn btn-danger" id="modalHapusBtn">Hapus</button>
      </form>
    </div>
  </div></div>
</div>
```

### JavaScript functions

```html
<script>
var hapus_data = (el) => {
    var url = el.dataset.url;
    var form = document.getElementById('modalHapusForm');
    form.action = url;
    form.setAttribute('hx-post', url);
    htmx.process(form);
    setConfirmBody('modalHapusBody', 'Yakin menghapus ', el.dataset.nama, '?');
    var btn = document.getElementById('modalHapusBtn');
    btn.textContent = 'Hapus';
    btn.className = 'btn btn-danger';
    new bootstrap.Modal(document.getElementById('modalHapus')).show();
};

var pulihkan_data = (el) => {
    var url = el.dataset.url;
    var form = document.getElementById('modalHapusForm');
    form.action = url;
    form.setAttribute('hx-post', url);
    htmx.process(form);
    setConfirmBody('modalHapusBody', 'Yakin memulihkan ', el.dataset.nama, '?');
    var btn = document.getElementById('modalHapusBtn');
    btn.textContent = 'Pulihkan';
    btn.className = 'btn btn-success';
    new bootstrap.Modal(document.getElementById('modalHapus')).show();
};
</script>
```

### DataTables row styling for deleted rows

Add `is_deleted` to the JSON payload (§"data()") and a `createdRow` callback.
This is the same pattern `dashboard.py`/`dashboard/index.html` already use for
the `alert` flag.

```js
$('#studentsTable').DataTable({
    ajax: { url: '{{ url_for("students.data") }}', dataSrc: 'data' },
    columns: [
        /* ... existing columns ... */
        { data: 'actions', orderable: false, searchable: false }
    ],
    createdRow: function (row, data) {
        if (data.is_deleted) {
            row.classList.add('table-danger');
        }
    },
    order: [[0, 'asc']]
});
```

Optional: also strike through the name cell via `columns.render` returning an
escaped `<span class="text-muted text-decoration-line-through">…</span>`.

---

## User Login Guard

In `app/blueprints/auth.py` `login()`, after the password check succeeds but
before `login_user`, block deleted accounts:

```python
user = User.query.filter_by(email=form.email.data).first()
if user is None or not verify_password(form.password.data, user.password_hash):
    return hx_render("auth/login.html", form=form,
        error="Email atau password salah.")
if user.is_deleted:
    return hx_render("auth/login.html", form=form,
        error="Akun telah dinonaktifkan. Hubungi admin.")
login_user(user)
```

This is the second layer of defense on top of the `before_request` session
guard (§"Session invalidation") — the login guard stops *new* sessions, the
`before_request` guard kills *existing* ones.

---

## Files to Modify

| # | File | Changes |
|---|---|---|
| 1 | `app/models.py` | Add `is_deleted` to **all 5** models (incl. `ViolationType`) |
| 2 | `migrations/` (new) + `alembic.ini` (new) | `flask db init` (prerequisite), then one migration for the 5 columns |
| 3 | `app/__init__.py` | `before_request` deleted-user session guard (I5) |
| 4 | `app/blueprints/students.py` | +delete, +restore; `_row_actions`; `data()` `is_deleted` flag; `_class_choices` filter |
| 5 | `app/blueprints/classes.py` | +delete, +restore; `_row_actions`; `data()` flag; `_teacher_choices` filter |
| 6 | `app/blueprints/users.py` | +delete (+self/last-admin guards I4), +restore; `_row_actions`; `data()` flag |
| 7 | `app/blueprints/academic_years.py` | +delete (+active-year guard I3), +restore; `_row_actions`; `data()` flag |
| 8 | `app/blueprints/violation_types.py` | +delete, +restore; `_row_actions`; `data()` flag |
| 9 | `app/blueprints/violations.py` | filter `_student_choices`, `_violation_type_choices`, `_class_choices` (read-path audit) |
| 10 | `app/blueprints/dashboard.py` | filter `_scope_students`, `_scope_summaries` (read-path audit) |
| 11 | `app/blueprints/auth.py` | login `is_deleted` check |
| 12–16 | `app/templates/{students,classes,users,academic_years,violation_types}/index.html` | +modal, +`hapus_data`/`pulihkan_data`, +`createdRow` styling |

---

## Test Plan

The repo has strong test conventions (`tests/test_*.py`, fixtures in
`conftest.py`: `admin`, `guru_bk`, `violation_setup`). Add a
`tests/test_deletion.py` covering, per entity where applicable:

**Hard-delete path**

- `test_delete_hard_when_no_related` — row removed; success message contains
  "secara permanen".
- `test_delete_then_gone_from_db` — `Model.query.get(id)` is `None`.

**Soft-delete path**

- `test_delete_soft_when_related` — row kept, `is_deleted=True`; message lists
  the related counts.
- `test_delete_counts_voided_dependents` — a voided/inactive dependent still
  triggers soft-delete (invariant I6).

**Restore**

- `test_restore_sets_flag_false` — `is_deleted` flipped, success message.
- `test_restore_idempotent` — restoring a non-deleted row returns the "belum
  dihapus" error and does not mutate.
- `test_delete_already_deleted_returns_error` — double-delete is rejected.

**Guards (invariants I3 / I4)**

- `test_cannot_delete_active_academic_year`.
- `test_cannot_delete_self` (admin deleting own id).
- `test_cannot_delete_last_admin`.
- `test_can_delete_second_admin_when_two_exist`.

**Session invalidation (I5)**

- `test_deleted_user_session_killed` — logged-in user becomes 403 on next
  request after being soft-deleted.
- `test_login_blocked_for_deleted_user`.

**Read-path filtering (I2)**

- `test_student_choices_exclude_deleted`.
- `test_violation_type_choices_exclude_deleted` (and still exclude
  `is_active=False`).
- `test_dashboard_excludes_deleted_student` — deleted student absent from
  stats/ranking.
- `test_by_class_excludes_deleted`.

**Display correctness**

- `test_academic_year_message_uses_year` — message for `AcademicYear` uses
  `.year`, not `.name` (regression for the accessor bug).

Run with the project's long-timeout parallel convention:

```bash
uv run pytest -n auto
```

---

## Verification

1. `flask db init && flask db migrate -m "..." && flask db upgrade` succeeds.
2. `uv run pytest -n auto` is green, including the new `test_deletion.py`.
3. Manual: delete an entity with no related records (hard-delete), delete one
   with related records (soft-delete + styled row), restore it, and confirm a
   deleted user is kicked out of an active session immediately.
