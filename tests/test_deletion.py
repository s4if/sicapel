"""Hybrid delete (hard-delete when safe, soft-delete as fallback).

Covers the 5 admin-maintained entities: students, classes, users, academic
years, violation types. See DELETION_IMPLEMENTATION_PLAN.md for the invariants
(I1-I6) each section enforces.
"""

from datetime import date, time

from app import db
from app.models import AcademicYear, Class, Student, User, ViolationType
from app.services import record_violation
from tests.conftest import login

_INCIDENT = date(2026, 9, 1)


def _record(setup, *, vt, student=None, points=None):
    return record_violation(
        student_id=(student or setup.student).id,
        violation_type_id=vt.id,
        points=points if points is not None else vt.default_points,
        chronology="kronologi tes",
        location="halaman",
        incident_date=_INCIDENT,
        incident_time=time(8, 0),
        academic_year_id=setup.ay.id,
        semester="1",
        recorded_by=setup.guru_bk.id,
        session=db.session,
    )


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------
def test_delete_hard_when_no_related(client, admin, violation_setup):
    from tests.conftest import make_student

    s = make_student(violation_setup.student.class_id, "7777", name="Hapus Saya")
    login(client, "admin@example.com")

    resp = client.post(f"/siswa/{s.id}/delete")
    assert resp.status_code == 200
    assert b"secara permanen" in resp.data
    assert db.session.get(Student, s.id) is None


def test_delete_then_gone_from_db(client, admin, violation_setup):
    from tests.conftest import make_student

    s = make_student(violation_setup.student.class_id, "7778", name="Sementara")
    login(client, "admin@example.com")
    client.post(f"/siswa/{s.id}/delete")
    assert db.session.get(Student, s.id) is None


def test_delete_soft_when_related(client, admin, violation_setup):
    _record(setup=violation_setup, vt=violation_setup.vt_ringan, points=5)
    db.session.commit()

    s = violation_setup.student
    login(client, "admin@example.com")
    resp = client.post(f"/siswa/{s.id}/delete")

    assert resp.status_code == 200
    assert b"ditandai sebagai dihapus" in resp.data
    assert b"pelanggaran: 1" in resp.data
    assert db.session.get(Student, s.id) is not None
    assert db.session.get(Student, s.id).is_deleted is True


def test_delete_counts_voided_dependents(client, admin, violation_setup):
    # I6: a voided dependent still counts -> soft delete, never orphans a FK.
    result = _record(setup=violation_setup, vt=violation_setup.vt_ringan, points=5)
    db.session.commit()
    result["violation"].is_void = True
    db.session.commit()

    s = violation_setup.student
    login(client, "admin@example.com")
    resp = client.post(f"/siswa/{s.id}/delete")
    assert b"ditandai sebagai dihapus" in resp.data
    assert b"pelanggaran: 1" in resp.data
    assert db.session.get(Student, s.id).is_deleted is True


def test_restore_sets_flag_false(client, admin, violation_setup):
    from tests.conftest import make_student

    s = make_student(violation_setup.student.class_id, "7779", name="Pulih")
    login(client, "admin@example.com")
    client.post(f"/siswa/{s.id}/delete")  # hard delete (no related)

    # Soft-delete path instead, to exercise restore:
    s2 = make_student(violation_setup.student.class_id, "7780", name="Pulih2")
    _record(setup=violation_setup, vt=violation_setup.vt_ringan, student=s2, points=5)
    db.session.commit()
    client.post(f"/siswa/{s2.id}/delete")
    assert db.session.get(Student, s2.id).is_deleted is True

    resp = client.post(f"/siswa/{s2.id}/restore")
    assert resp.status_code == 200
    assert b"berhasil dipulihkan" in resp.data
    assert db.session.get(Student, s2.id).is_deleted is False


def test_restore_idempotent(client, admin, violation_setup):
    from tests.conftest import make_student

    s = make_student(violation_setup.student.class_id, "7781", name="Idempotent")
    login(client, "admin@example.com")
    # Not deleted -> restore should refuse without mutating.
    resp = client.post(f"/siswa/{s.id}/restore")
    assert b"belum dihapus" in resp.data
    assert db.session.get(Student, s.id).is_deleted is False


def test_delete_already_deleted_returns_error(client, admin, violation_setup):
    from tests.conftest import make_student

    s = make_student(violation_setup.student.class_id, "7782", name="Double")
    _record(setup=violation_setup, vt=violation_setup.vt_ringan, student=s, points=5)
    db.session.commit()
    login(client, "admin@example.com")
    client.post(f"/siswa/{s.id}/delete")  # soft delete

    resp = client.post(f"/siswa/{s.id}/delete")
    assert b"sudah dihapus sebelumnya" in resp.data


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------
def test_class_delete_hard_when_no_students(client, admin, guru_bk):
    from tests.conftest import make_class

    cls = make_class(guru_bk.id, "X KOSONG")
    login(client, "admin@example.com")
    resp = client.post(f"/kelas/{cls.id}/delete")
    assert b"secara permanen" in resp.data
    assert db.session.get(Class, cls.id) is None


def test_class_delete_soft_when_has_students(client, admin, violation_setup):
    # violation_setup already seeded a class with one student.
    cls = violation_setup.student.class_
    login(client, "admin@example.com")
    resp = client.post(f"/kelas/{cls.id}/delete")
    assert b"ditandai sebagai dihapus" in resp.data
    assert b"siswa: 1" in resp.data
    assert db.session.get(Class, cls.id).is_deleted is True


# ---------------------------------------------------------------------------
# Users (guards I4)
# ---------------------------------------------------------------------------
def test_cannot_delete_self(client, admin, app):
    from tests.conftest import make_user

    make_user("admin", "admin2@example.com", name="Admin Dua")  # so not last
    login(client, "admin@example.com")
    resp = client.post(f"/pengguna/{admin.id}/delete")
    assert b"akun sendiri" in resp.data
    assert db.session.get(User, admin.id).is_deleted is False


def test_cannot_delete_last_admin(client, admin):
    login(client, "admin@example.com")
    resp = client.post(f"/pengguna/{admin.id}/delete")
    assert b"admin terakhir" in resp.data
    assert db.session.get(User, admin.id).is_deleted is False


def test_can_delete_second_admin_when_two_exist(client, admin, app):
    from tests.conftest import make_user

    other = make_user("admin", "admin2@example.com", name="Admin Dua")
    login(client, "admin@example.com")
    resp = client.post(f"/pengguna/{other.id}/delete")
    assert b"secara permanen" in resp.data
    assert db.session.get(User, other.id) is None


def test_user_soft_delete_when_has_related(client, admin, violation_setup):
    # guru_bk recorded a violation -> related count > 0 -> soft delete.
    login(client, "admin@example.com")
    resp = client.post(f"/pengguna/{violation_setup.guru_bk.id}/delete")
    assert b"ditandai sebagai dihapus" in resp.data
    assert db.session.get(User, violation_setup.guru_bk.id).is_deleted is True


# ---------------------------------------------------------------------------
# Academic Years (guard I3) + display accessor
# ---------------------------------------------------------------------------
def test_cannot_delete_active_academic_year(client, admin, violation_setup):
    ay = violation_setup.ay  # active
    login(client, "admin@example.com")
    resp = client.post(f"/tahun-ajaran/{ay.id}/delete")
    assert b"tidak dapat dihapus" in resp.data
    assert db.session.get(AcademicYear, ay.id).is_deleted is False


def test_academic_year_delete_hard_when_inactive_no_related(client, admin):
    from tests.conftest import make_academic_year

    ay = make_academic_year("2024/2025", active=False)
    login(client, "admin@example.com")
    resp = client.post(f"/tahun-ajaran/{ay.id}/delete")
    assert b"secara permanen" in resp.data
    assert db.session.get(AcademicYear, ay.id) is None


def test_academic_year_message_uses_year(client, admin):
    from tests.conftest import make_academic_year

    ay = make_academic_year("2023/2024", active=False)
    login(client, "admin@example.com")
    resp = client.post(f"/tahun-ajaran/{ay.id}/delete")
    # Display accessor is .year, not .name (regression for AttributeError).
    assert b"2023/2024" in resp.data
    assert b"secara permanen" in resp.data


# ---------------------------------------------------------------------------
# Violation Types (I1: is_deleted independent of is_active)
# ---------------------------------------------------------------------------
def test_violation_type_delete_hard_when_no_related(client, admin, violation_setup):
    from tests.conftest import make_violation_type

    vt = make_violation_type(
        violation_setup.categories["ringan"], "Tipe Kosong", 10, admin.id
    )
    login(client, "admin@example.com")
    resp = client.post(f"/jenis-pelanggaran/{vt.id}/delete")
    assert b"secara permanen" in resp.data
    assert db.session.get(ViolationType, vt.id) is None


def test_violation_type_soft_delete_keeps_is_active(client, admin, violation_setup):
    # I1: deleting flips is_deleted only; is_active is untouched.
    vt = violation_setup.vt_ringan
    _record(setup=violation_setup, vt=vt, points=5)
    db.session.commit()
    login(client, "admin@example.com")
    client.post(f"/jenis-pelanggaran/{vt.id}/delete")
    fresh = db.session.get(ViolationType, vt.id)
    assert fresh.is_deleted is True
    assert fresh.is_active is True  # unchanged


# ---------------------------------------------------------------------------
# Session invalidation (I5)
# ---------------------------------------------------------------------------
def test_login_blocked_for_deleted_user(client, admin):
    admin.is_deleted = True
    db.session.commit()

    resp = client.post(
        "/auth/login",
        data={"email": "admin@example.com", "password": "password"},
    )
    assert b"dinonaktifkan" in resp.data


def test_deleted_user_session_killed(client, admin):
    from tests.conftest import make_user

    # Add a second admin so the lone-admin invariant stays intact.
    make_user("admin", "admin2@example.com", name="Admin Dua")
    login(client, "admin@example.com")

    db.session.get(User, admin.id).is_deleted = True
    db.session.commit()

    # Next authenticated request must reject the now-deleted session.
    resp = client.get("/dashboard/")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Read-path filtering (I2)
# ---------------------------------------------------------------------------
def test_student_choices_exclude_deleted(client, admin, violation_setup):
    from tests.conftest import make_student

    s = make_student(violation_setup.student.class_id, "9001", name="Pilihan Siswa")
    login(client, "admin@example.com")
    body_before = client.get("/pelanggaran/tambah").get_data(as_text=True)
    assert "Pilihan Siswa" in body_before

    s.is_deleted = True
    db.session.commit()
    body_after = client.get("/pelanggaran/tambah").get_data(as_text=True)
    assert "Pilihan Siswa" not in body_after


def test_violation_type_choices_exclude_deleted(client, admin, violation_setup):
    from tests.conftest import make_violation_type

    make_violation_type(
        violation_setup.categories["ringan"], "Aktif Pilihan", 10, admin.id
    )
    vt_deleted = make_violation_type(
        violation_setup.categories["ringan"], "Dihapus Pilihan", 10, admin.id
    )
    vt_inactive = make_violation_type(
        violation_setup.categories["ringan"], "Nonaktif Pilihan", 10, admin.id
    )
    vt_inactive.is_active = False
    vt_deleted.is_deleted = True
    db.session.commit()

    login(client, "admin@example.com")
    body = client.get("/pelanggaran/tambah").get_data(as_text=True)
    assert "Aktif Pilihan" in body
    assert "Dihapus Pilihan" not in body  # excluded by is_deleted
    assert "Nonaktif Pilihan" not in body  # still excluded by is_active=False


def test_dashboard_excludes_deleted_student(client, admin, violation_setup):
    _record(setup=violation_setup, vt=violation_setup.vt_ringan, points=25)
    db.session.commit()
    login(client, "admin@example.com")

    rows = client.get("/dashboard/data").get_json()["data"]
    assert any(r["name"] == "Siswa" for r in rows)

    violation_setup.student.is_deleted = True
    db.session.commit()
    rows = client.get("/dashboard/data").get_json()["data"]
    assert all(r["name"] != "Siswa" for r in rows)


def test_by_class_excludes_deleted(client, admin, violation_setup):
    from tests.conftest import make_student

    s = make_student(
        violation_setup.student.class_id, "9002", name="ByClass Siswa"
    )
    login(client, "admin@example.com")
    cls_id = s.class_id

    body_before = client.get(f"/siswa/by-class/{cls_id}").get_data(as_text=True)
    assert "ByClass Siswa" in body_before

    s.is_deleted = True
    db.session.commit()
    body_after = client.get(f"/siswa/by-class/{cls_id}").get_data(as_text=True)
    assert "ByClass Siswa" not in body_after


def test_data_table_shows_deleted_rows_with_flag(client, admin, violation_setup):
    # data() returns ALL rows (no is_deleted filter) so admins can restore.
    from tests.conftest import make_student

    s = make_student(violation_setup.student.class_id, "9003", name="Disembunyikan")
    s.is_deleted = True
    db.session.commit()
    login(client, "admin@example.com")
    rows = client.get("/siswa/data").get_json()["data"]
    matched = [r for r in rows if r["name"] == "Disembunyikan"]
    assert matched
    assert matched[0]["is_deleted"] is True


# ---------------------------------------------------------------------------
# Hide soft-deleted entities for non-admins
# ---------------------------------------------------------------------------
def test_admin_data_includes_deleted(client, admin, violation_setup):
    from tests.conftest import make_student

    s = make_student(
        violation_setup.student.class_id, "9101", name="Hanya Admin"
    )
    s.is_deleted = True
    db.session.commit()
    login(client, "admin@example.com")
    rows = client.get("/siswa/data").get_json()["data"]
    assert any(r["name"] == "Hanya Admin" for r in rows)


def test_non_admin_data_excludes_deleted(client, guru_bk, violation_setup):
    from tests.conftest import make_student

    s = make_student(
        violation_setup.student.class_id, "9102", name="Sembunyi Guru"
    )
    s.is_deleted = True
    db.session.commit()
    login(client, "gurubk@example.com")
    rows = client.get("/siswa/data").get_json()["data"]
    assert all(r["name"] != "Sembunyi Guru" for r in rows)


def test_wali_kelas_data_excludes_deleted(client, violation_setup):
    from tests.conftest import make_class, make_student, make_user

    wk = make_user("wali_kelas", "wkhide@example.com", name="Wali Hide")
    cls = make_class(wk.id, "X WK")
    s = make_student(cls.id, "9103", name="Sembunyi Wali")
    s.is_deleted = True
    db.session.commit()
    login(client, "wkhide@example.com")
    rows = client.get("/siswa/data").get_json()["data"]
    assert all(r["name"] != "Sembunyi Wali" for r in rows)


def test_non_admin_student_detail_404_when_deleted(client, guru_bk, violation_setup):
    s = violation_setup.student
    s.is_deleted = True
    db.session.commit()
    login(client, "gurubk@example.com")
    resp = client.get(f"/siswa/{s.id}")
    assert resp.status_code == 404


def test_admin_can_view_deleted_student_detail(client, admin, violation_setup):
    s = violation_setup.student
    s.is_deleted = True
    db.session.commit()
    login(client, "admin@example.com")
    resp = client.get(f"/siswa/{s.id}")
    assert resp.status_code == 200


def test_restore_is_admin_only(client, guru_bk, violation_setup):
    s = violation_setup.student
    s.is_deleted = True
    db.session.commit()
    login(client, "gurubk@example.com")
    resp = client.post(f"/siswa/{s.id}/restore")
    assert resp.status_code == 403
    assert s.is_deleted is True
