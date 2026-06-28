"""Tests for placement history / multi-year enrollment
(CLASSES_MODIFICATION §8.1).

Covers ``enroll_student`` (§4.1), the ``(student_id, academic_year_id)``
UNIQUE backstop, the cache-agreement invariant (D-C6), and the blueprint
wiring that keeps ``students.class_id`` + ``class_enrollments`` in sync on
student create/edit.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import ClassEnrollment, Student
from app.services import enroll_student, recompute_current_placement
from tests.conftest import login, make_class, make_enrollment, make_user


# ---------------------------------------------------------------------------
# 1. enroll_student creates one active enrollment; students.class_id cache
#    matches (D-C6 / invariant 2).
# ---------------------------------------------------------------------------
def test_enroll_creates_active_enrollment_and_updates_cache(violation_setup):
    ay = violation_setup.ay
    student = violation_setup.student
    wk = make_user("wali_kelas", "wk@example.com")
    target = make_class(wk.id, "XI IPA 1", grade_level=11)

    enroll_student(
        student_id=student.id,
        class_id=target.id,
        academic_year_id=ay.id,
        homeroom_teacher_id=wk.id,
        session=db.session,
    )
    db.session.commit()

    enrollments = ClassEnrollment.query.filter_by(student_id=student.id).all()
    assert len(enrollments) == 1
    assert enrollments[0].is_active is True
    assert enrollments[0].class_id == target.id
    # cache agreement (invariant 2): active year enrollment drives the cache
    assert db.session.get(Student, student.id).class_id == target.id


# ---------------------------------------------------------------------------
# 2. Re-enrolling the same (student_id, academic_year_id) updates in place —
#    no duplicate, no IntegrityError (the mid-year edit path, D-C4).
# ---------------------------------------------------------------------------
def test_reenroll_same_year_updates_in_place(violation_setup):
    ay = violation_setup.ay
    student = violation_setup.student
    wk = make_user("wali_kelas", "wk@example.com")
    first = make_class(wk.id, "X IPA 1", grade_level=10)
    second = make_class(wk.id, "XI IPA 1", grade_level=11)

    enroll_student(
        student_id=student.id,
        class_id=first.id,
        academic_year_id=ay.id,
        homeroom_teacher_id=wk.id,
        session=db.session,
    )
    db.session.commit()

    # Re-enroll in a different class for the SAME year — must overwrite, not
    # create a second row.
    enroll_student(
        student_id=student.id,
        class_id=second.id,
        academic_year_id=ay.id,
        homeroom_teacher_id=wk.id,
        session=db.session,
    )
    db.session.commit()

    rows = ClassEnrollment.query.filter_by(
        student_id=student.id, academic_year_id=ay.id
    ).all()
    assert len(rows) == 1
    assert rows[0].class_id == second.id
    assert db.session.get(Student, student.id).class_id == second.id


# ---------------------------------------------------------------------------
# 3. Backstop: a second row for the same (student_id, academic_year_id)
#    cannot persist — verifies the UNIQUE constraint (mirrors
#    test_letter_numbering case 5).
# ---------------------------------------------------------------------------
def test_duplicate_student_year_raises_integrity_error(violation_setup):
    ay = violation_setup.ay
    student = violation_setup.student

    make_enrollment(student.id, student.class_id, ay.id, violation_setup.guru_bk.id)

    with pytest.raises(IntegrityError):
        db.session.add(
            ClassEnrollment(
                student_id=student.id,
                class_id=student.class_id,
                academic_year_id=ay.id,
                homeroom_teacher_id=violation_setup.guru_bk.id,
                is_active=True,
            )
        )
        db.session.flush()
    db.session.rollback()


# ---------------------------------------------------------------------------
# 4. Editing a student's class via the students blueprint keeps cache +
#    enrollment in sync (CM3 wiring).
# ---------------------------------------------------------------------------
def test_edit_student_class_syncs_enrollment(client, admin, violation_setup):
    ay = violation_setup.ay
    student = violation_setup.student
    wk = make_user("wali_kelas", "wk@example.com")
    target = make_class(wk.id, "XI IPA 1", grade_level=11)

    login(client, admin.email)
    resp = client.post(
        f"/siswa/{student.id}/edit",
        data={
            "nis": student.nis,
            "name": student.name,
            "gender": student.gender,
            "class_id": target.id,
            "status": student.status,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200

    # Cache column follows the form choice...
    assert db.session.get(Student, student.id).class_id == target.id
    # ...and so does the active-year enrollment (class + wali kelas).
    ce = ClassEnrollment.query.filter_by(
        student_id=student.id, academic_year_id=ay.id
    ).one()
    assert ce.class_id == target.id
    assert ce.homeroom_teacher_id == wk.id
    assert ce.is_active is True


# ---------------------------------------------------------------------------
# 5. Enrolling in a new year flips the prior year's row is_active=False —
#    exactly one active enrollment per student (invariant 1).
# ---------------------------------------------------------------------------
def test_enroll_new_year_deactivates_prior(violation_setup):
    from tests.conftest import make_academic_year

    student = violation_setup.student
    ay_active = violation_setup.ay  # is_active=True
    ay_next = make_academic_year("2027/2028", active=False)
    wk = make_user("wali_kelas", "wk@example.com")
    next_class = make_class(wk.id, "XI IPA 1", grade_level=11)

    # Seed an active placement in the current year.
    enroll_student(
        student_id=student.id,
        class_id=student.class_id,
        academic_year_id=ay_active.id,
        homeroom_teacher_id=violation_setup.guru_bk.id,
        session=db.session,
    )
    db.session.commit()
    prior = ClassEnrollment.query.filter_by(
        student_id=student.id, academic_year_id=ay_active.id
    ).one()
    assert prior.is_active is True

    # Roll into next year: the new row becomes active, the prior flips False.
    enroll_student(
        student_id=student.id,
        class_id=next_class.id,
        academic_year_id=ay_next.id,
        homeroom_teacher_id=wk.id,
        session=db.session,
    )
    db.session.commit()

    active_rows = (
        ClassEnrollment.query.filter_by(student_id=student.id, is_active=True).all()
    )
    assert len(active_rows) == 1
    assert active_rows[0].academic_year_id == ay_next.id

    db.session.refresh(prior)
    assert prior.is_active is False


# ---------------------------------------------------------------------------
# 6. recompute_current_placement restores a deliberately-desynced cache
#    (§4.3 backstop).
# ---------------------------------------------------------------------------
def test_recompute_current_placement_restores_cache(violation_setup):
    ay = violation_setup.ay
    student = violation_setup.student
    wk = make_user("wali_kelas", "wk@example.com")
    target = make_class(wk.id, "XI IPA 1", grade_level=11)

    enroll_student(
        student_id=student.id,
        class_id=target.id,
        academic_year_id=ay.id,
        homeroom_teacher_id=wk.id,
        session=db.session,
    )
    db.session.commit()

    # Sabotage the cache directly, then let the backstop repair it.
    drifted = make_class(wk.id, "X OTHER", grade_level=10)
    db.session.get(Student, student.id).class_id = drifted.id
    db.session.commit()

    recompute_current_placement(student.id, db.session)
    db.session.commit()

    assert db.session.get(Student, student.id).class_id == target.id
