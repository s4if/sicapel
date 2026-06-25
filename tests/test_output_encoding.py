"""Regression tests for output encoding & business-rule hardening.

Covers the four guarantees reintroduced by FIX_PLAN.md:

* V1 (Phase 1) — confirm-modal action cells never interpolate a user value
  into a JS string literal; the value rides in a ``data-*`` attribute and is
  written via ``textContent``.
* V2 (Phase 2) — storing raw + sanitizing once on read means ``A & B`` is
  emitted single-escaped (``A &amp; B``), never double-escaped
  (``A &amp;amp; B``).
* V3 (Phase 3) — wali_kelas cannot list another class's students nor preview
  another class's student points.
* V4 (Phase 4) — ``ViolationTypeForm.default_points`` is bound to its
  category window; ``AcademicYearForm`` requires ``end_date > start_date``.
"""

import datetime

from tests.conftest import login


# --------------------------------------------------------------------------- #
# V1 — XSS hardening (Phase 1)                                                #
# --------------------------------------------------------------------------- #
def test_actions_cell_does_not_emit_inline_js_string(
    client, guru_bk, violation_setup
):
    """A student name carrying an XSS payload must ride in a data-*
    attribute, never inside an onclick JS string literal."""
    from app import db
    from app.models import Student, ViolationRecord

    evil = "');alert(1);//<img src=x onerror=alert(1)>"
    stu = Student.query.first()
    stu.name = evil
    vt = violation_setup.vt_ringan

    v = ViolationRecord(
        student_id=stu.id,
        violation_type_id=vt.id,
        category_id=vt.category_id,
        points=vt.default_points,
        record_number="X",
        incident_date=datetime.date.today(),
        academic_year_id=violation_setup.ay.id,
        semester="1",
        recorded_by=guru_bk.id,
        is_void=False,
    )
    db.session.add(v)
    db.session.commit()

    login(client, guru_bk.email)
    resp = client.get("/pelanggaran/data")
    payload = resp.get_json()["data"][0]["actions"]

    # Safe caller: the button passes itself; no value is interpolated.
    assert 'onclick="hapus_violation(this)"' in payload
    # The user value is carried in an attribute (attribute-escaped), and the
    # raw payload never appears verbatim in the cell.
    assert "data-nama=" in payload
    assert evil not in payload


# --------------------------------------------------------------------------- #
# V2 — no double-escape (Phase 2)                                             #
# --------------------------------------------------------------------------- #
def test_name_with_ampersand_renders_once(client, admin, violation_setup):
    """'A & B' must surface single-escaped in /siswa/data, not double."""
    from app import db
    from app.models import Student

    db.session.add(
        Student(
            nis="X1",
            name="A & B",
            gender="L",
            class_id=violation_setup.student.class_id,
            status="active",
        )
    )
    db.session.commit()

    login(client, admin.email)
    rows = client.get("/siswa/data").get_json()["data"]
    row = next(r for r in rows if r["nis"] == "X1")

    # Stored raw, sanitized once on read by the /data endpoint.
    assert row["name"] == "A &amp; B"
    assert "&amp;amp;" not in row["name"]


# --------------------------------------------------------------------------- #
# V3 — wali-kelas scoping (Phase 3)                                           #
# --------------------------------------------------------------------------- #
def test_wali_kelas_cannot_list_other_class_students(
    client, wali_kelas, violation_setup
):
    """wali_kelas hitting /siswa/by-class/<other_class> -> 403."""
    from app.models import Class

    other = Class.query.filter(
        Class.homeroom_teacher_id != wali_kelas.id
    ).first()
    login(client, wali_kelas.email)
    resp = client.get(f"/siswa/by-class/{other.id}")
    assert resp.status_code == 403


def test_wali_kelas_cannot_preview_other_class_points(
    client, wali_kelas, violation_setup
):
    """wali_kelas previewing points for another class's student -> 403."""
    from app.models import Class, Student

    # Explicit join — ``Student.class_.homeroom_teacher_id`` is not a valid
    # filter expression under SQLAlchemy 2.x (see dashboard._scope_students).
    other_stu = (
        Student.query.join(Class, Student.class_id == Class.id)
        .filter(Class.homeroom_teacher_id != wali_kelas.id)
        .first()
    )
    vt = violation_setup.vt_ringan
    login(client, wali_kelas.email)
    resp = client.get(
        f"/pelanggaran/preview-points?violation_type_id={vt.id}"
        f"&student_id={other_stu.id}"
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# V4 — form validators (Phase 4)                                              #
# --------------------------------------------------------------------------- #
def test_violation_type_points_must_match_category(violation_setup):
    from app.forms import ViolationTypeForm

    ringan = violation_setup.categories["ringan"]  # window 5..25
    form = ViolationTypeForm(
        category_id=str(ringan.id),
        name="Tes",
        default_points=200,  # outside the ringan window
        is_active="y",
    )
    form.category_id.choices = [(ringan.id, "ringan")]
    assert not form.validate()
    assert any("antara" in e for e in form.default_points.errors)


def test_academic_year_end_after_start(app):
    from app.forms import AcademicYearForm

    form = AcademicYearForm(
        year="2026/2027",
        start_date="2026-07-01",
        end_date="2026-06-30",
        is_active="y",
    )
    assert not form.validate()
    assert form.end_date.errors
