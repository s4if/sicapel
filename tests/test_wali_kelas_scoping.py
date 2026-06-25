"""Regression tests for the wali-kelas query bug (FIX_PLAN.md).

The bug shipped because no test logged in as ``wali_kelas`` against the
affected endpoints. Every wali-kelas-scoped read in ``students.py`` and
``violations.py`` filtered through ``Student.class_.homeroom_teacher_id`` —
an expression that does not compile under SQLAlchemy 2.x and raised
``AttributeError`` (a 500) at request time. These tests seed two classes
(the wali-kelas's own and another teacher's) and assert each fixed route
returns 200 / 404 rather than 500, and that scoping hides the other class.

The five sites map directly to the FIX_PLAN.md Phase 1 table.
"""

import datetime

from tests.conftest import login, make_class, make_student


def _own_class_for(wk):
    """Give the wali_kelas their own class + student; return both.

    Relies on ``violation_setup`` having created guru_bk's class (the
    'other' class whose student the wali-kelas must NOT see).
    """
    cls = make_class(wk.id, "X WK", grade_level=10)
    stu = make_student(cls.id, "WK-1", name="Milik Saya")
    return cls, stu


def test_wali_kelas_students_data_is_scoped(client, wali_kelas, violation_setup):
    """Site 1 (_base_query): /siswa/data returns 200 and only the
    wali_kelas's own student."""
    _own_class_for(wali_kelas)
    login(client, wali_kelas.email)
    resp = client.get("/siswa/data")
    assert resp.status_code == 200
    nis_set = {r["nis"] for r in resp.get_json()["data"]}
    assert "WK-1" in nis_set
    assert violation_setup.student.nis not in nis_set  # guru_bk's class


def test_wali_kelas_student_detail_other_class_404(client, wali_kelas, violation_setup):
    """Site 2 (detail): another class's student is 404, not 500."""
    login(client, wali_kelas.email)
    resp = client.get(f"/siswa/{violation_setup.student.id}")
    assert resp.status_code == 404


def test_wali_kelas_violations_data_does_not_500(client, wali_kelas, violation_setup):
    """Site 4 (data): the ViolationRecord->Student->Class query must not
    raise AttributeError (was a 500)."""
    _own_class_for(wali_kelas)  # ensure wali_kelas has a class at all
    login(client, wali_kelas.email)
    resp = client.get("/pelanggaran/data")
    assert resp.status_code == 200
    assert resp.get_json()["data"] == []  # no violations in their class yet


def test_wali_kelas_violation_detail_other_class_404(
    client, wali_kelas, violation_setup
):
    """Site 5 (detail): a violation in another class is 404."""
    from app import db
    from app.models import ViolationRecord

    vt = violation_setup.vt_ringan
    other_v = ViolationRecord(
        student_id=violation_setup.student.id,  # guru_bk's class
        violation_type_id=vt.id,
        category_id=vt.category_id,
        points=vt.default_points,
        record_number="OTHER-1",
        incident_date=datetime.date.today(),
        academic_year_id=violation_setup.ay.id,
        semester="1",
        recorded_by=violation_setup.guru_bk.id,
        is_void=False,
    )
    db.session.add(other_v)
    db.session.commit()

    login(client, wali_kelas.email)
    resp = client.get(f"/pelanggaran/{other_v.id}")
    assert resp.status_code == 404


def test_wali_kelas_violation_form_loads(client, wali_kelas, violation_setup):
    """Site 3 (_student_choices): the Catat Pelanggaran form renders for
    wali_kelas (was a 500 via _student_choices)."""
    _own_class_for(wali_kelas)
    login(client, wali_kelas.email)
    resp = client.get("/pelanggaran/tambah")
    assert resp.status_code == 200
