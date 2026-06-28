"""Tests for academic-year rollover / cohort promotion
(CLASSES_MODIFICATION §8.2).

Covers ``promote_academic_year`` (§4.2): graduation, promotion, cache
agreement, active-year flip, and the idempotency / pre-existence guards.
"""

import pytest

from app import db
from app.models import ClassEnrollment, Student
from app.services import (
    enroll_student,
    promote_academic_year,
    recompute_current_placement,
)
from tests.conftest import login, make_academic_year, make_class, make_user


def _seed_cohort(violation_setup, *, grade_level, class_name, nis_root, n=1):
    """Create a class (grade_level) + n active students enrolled in the
    active academic year, returning (cls, [students], wk)."""
    wk = make_user("wali_kelas", f"wk_{nis_root}@example.com")
    cls = make_class(wk.id, class_name, grade_level=grade_level)
    students = []
    for i in range(n):
        s = Student(
            nis=f"{nis_root}{i}",
            name=f"Siswa {nis_root}{i}",
            gender="L",
            class_id=cls.id,
            status="active",
        )
        db.session.add(s)
        db.session.flush()
        enroll_student(
            student_id=s.id,
            class_id=cls.id,
            academic_year_id=violation_setup.ay.id,
            homeroom_teacher_id=wk.id,
            session=db.session,
        )
        students.append(s)
    db.session.commit()
    return cls, students, wk


# ---------------------------------------------------------------------------
# 1. grade 12 → status='graduated', no new enrollment.
# ---------------------------------------------------------------------------
def test_grade12_graduates_no_new_enrollment(violation_setup):
    cls12, students, wk = _seed_cohort(violation_setup, grade_level=12, class_name="XII IPA 1", nis_root="12")
    target = make_academic_year("2027/2028", active=False)

    result = promote_academic_year(
        source_year_id=violation_setup.ay.id,
        target_year_id=target.id,
        class_map={cls12.id: (cls12.id, wk.id)},
        session=db.session,
    )
    db.session.commit()

    db.session.refresh(students[0])
    assert students[0].status == "graduated"
    assert len(result["graduated"]) == 1
    assert len(result["promoted"]) == 0
    assert (
        ClassEnrollment.query.filter_by(
            student_id=students[0].id, academic_year_id=target.id
        ).count()
        == 0
    )


# ---------------------------------------------------------------------------
# 2. grade 10 → 11 and grade 11 → 12: new target-year enrollment
#    (is_active=True); prior enrollment is_active=False.
# ---------------------------------------------------------------------------
def test_promotion_creates_target_enrollment_and_deactivates_prior(violation_setup):
    cls10, s10, wk10 = _seed_cohort(violation_setup, grade_level=10, class_name="X IPA 1", nis_root="10")
    cls11, s11, wk11 = _seed_cohort(violation_setup, grade_level=11, class_name="XI IPA 1", nis_root="11")
    target = make_academic_year("2027/2028", active=False)
    tgt11 = make_class(wk11.id, "XI IPA 1 (new)", grade_level=11)
    tgt12 = make_class(wk10.id, "XII IPA 1 (new)", grade_level=12)

    result = promote_academic_year(
        source_year_id=violation_setup.ay.id,
        target_year_id=target.id,
        class_map={cls10.id: (tgt11.id, wk11.id), cls11.id: (tgt12.id, wk10.id)},
        session=db.session,
    )
    db.session.commit()

    assert len(result["promoted"]) == 2
    for s in (s10[0], s11[0]):
        prior = ClassEnrollment.query.filter_by(
            student_id=s.id, academic_year_id=violation_setup.ay.id
        ).one()
        new = ClassEnrollment.query.filter_by(
            student_id=s.id, academic_year_id=target.id
        ).one()
        assert prior.is_active is False
        assert new.is_active is True


# ---------------------------------------------------------------------------
# 3. Caches (students.class_id, classes.homeroom_teacher_id) reflect the
#    target year after rollover.
# ---------------------------------------------------------------------------
def test_caches_reflect_target_year_after_rollover(violation_setup):
    cls10, s10, wk10 = _seed_cohort(violation_setup, grade_level=10, class_name="X IPA 1", nis_root="10")
    target = make_academic_year("2027/2028", active=False)
    new_wk = make_user("wali_kelas", "newwk@example.com")
    tgt11 = make_class(new_wk.id, "XI IPA 1 (new)", grade_level=11)

    promote_academic_year(
        source_year_id=violation_setup.ay.id,
        target_year_id=target.id,
        class_map={cls10.id: (tgt11.id, new_wk.id)},
        session=db.session,
    )
    db.session.commit()

    db.session.refresh(s10[0])
    assert s10[0].class_id == tgt11.id
    db.session.refresh(tgt11)
    assert tgt11.homeroom_teacher_id == new_wk.id


# ---------------------------------------------------------------------------
# 4. Target year is_active=True, source is_active=False.
# ---------------------------------------------------------------------------
def test_active_year_flips_after_rollover(violation_setup):
    cls10, _, wk10 = _seed_cohort(violation_setup, grade_level=10, class_name="X IPA 1", nis_root="10")
    target = make_academic_year("2027/2028", active=False)
    tgt11 = make_class(wk10.id, "XI IPA 1 (new)", grade_level=11)

    promote_academic_year(
        source_year_id=violation_setup.ay.id,
        target_year_id=target.id,
        class_map={cls10.id: (tgt11.id, wk10.id)},
        session=db.session,
    )
    db.session.commit()

    db.session.refresh(violation_setup.ay)
    db.session.refresh(target)
    assert target.is_active is True
    assert violation_setup.ay.is_active is False


# ---------------------------------------------------------------------------
# 5. Idempotency guard refuses if the target year already has enrollments.
# ---------------------------------------------------------------------------
def test_idempotency_guard_target_already_has_enrollments(violation_setup):
    cls10, _, wk10 = _seed_cohort(violation_setup, grade_level=10, class_name="X IPA 1", nis_root="10")
    target = make_academic_year("2027/2028", active=False)
    tgt11 = make_class(wk10.id, "XI IPA 1 (new)", grade_level=11)

    other = Student(nis="pre", name="Pre", gender="L", class_id=tgt11.id, status="active")
    db.session.add(other)
    db.session.flush()
    enroll_student(
        student_id=other.id,
        class_id=tgt11.id,
        academic_year_id=target.id,
        homeroom_teacher_id=wk10.id,
        session=db.session,
    )
    db.session.commit()

    with pytest.raises(ValueError, match="sudah memiliki data kelas"):
        promote_academic_year(
            source_year_id=violation_setup.ay.id,
            target_year_id=target.id,
            class_map={cls10.id: (tgt11.id, wk10.id)},
            session=db.session,
        )
    db.session.rollback()


# ---------------------------------------------------------------------------
# 6. Target classes must pre-exist — missing target raises (no auto-create).
# ---------------------------------------------------------------------------
def test_missing_target_class_raises(violation_setup):
    cls10, _, wk10 = _seed_cohort(violation_setup, grade_level=10, class_name="X IPA 1", nis_root="10")
    target = make_academic_year("2027/2028", active=False)

    with pytest.raises(ValueError, match="Kelas tujuan"):
        promote_academic_year(
            source_year_id=violation_setup.ay.id,
            target_year_id=target.id,
            class_map={cls10.id: (999, wk10.id)},
            session=db.session,
        )
    db.session.rollback()


# ---------------------------------------------------------------------------
# 7. recompute_current_placement restores a deliberately-desynced cache.
# ---------------------------------------------------------------------------
def test_recompute_current_placement_restores_cache_after_rollover(violation_setup):
    cls10, s10, wk10 = _seed_cohort(violation_setup, grade_level=10, class_name="X IPA 1", nis_root="10")
    target = make_academic_year("2027/2028", active=False)
    new_wk = make_user("wali_kelas", "newwk2@example.com")
    tgt11 = make_class(new_wk.id, "XI IPA 1 (new)", grade_level=11)

    promote_academic_year(
        source_year_id=violation_setup.ay.id,
        target_year_id=target.id,
        class_map={cls10.id: (tgt11.id, new_wk.id)},
        session=db.session,
    )
    db.session.commit()

    drifted = make_class(new_wk.id, "DRIFT", grade_level=9)
    db.session.get(Student, s10[0].id).class_id = drifted.id
    db.session.commit()

    recompute_current_placement(s10[0].id, db.session)
    db.session.commit()

    assert db.session.get(Student, s10[0].id).class_id == tgt11.id


# ---------------------------------------------------------------------------
# 8–10. Route-level regression (§8.3): rollover endpoint is admin-only.
# ---------------------------------------------------------------------------
def test_rollover_get_admin_ok(client, admin, violation_setup):
    login(client, admin.email)
    resp = client.get("/tahun-ajaran/rollover")
    assert resp.status_code == 200


def test_rollover_forbidden_for_guru_bk(client, guru_bk, violation_setup):
    login(client, guru_bk.email)
    resp = client.get("/tahun-ajaran/rollover")
    assert resp.status_code == 403


def test_rollover_forbidden_for_wali_kelas(client, wali_kelas, violation_setup):
    login(client, wali_kelas.email)
    resp = client.get("/tahun-ajaran/rollover")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 11. End-to-end route POST promotes the cohort and flips the active year.
# ---------------------------------------------------------------------------
def test_rollover_post_promotes_via_route(client, admin, violation_setup):
    # Enroll the seeded student in the active year so they form a cohort.
    enroll_student(
        student_id=violation_setup.student.id,
        class_id=violation_setup.student.class_id,
        academic_year_id=violation_setup.ay.id,
        homeroom_teacher_id=violation_setup.guru_bk.id,
        session=db.session,
    )
    db.session.commit()
    source_class_id = violation_setup.student.class_id

    new_wk = make_user("wali_kelas", "routewk@example.com")
    target = make_academic_year("2027/2028", active=False)
    tgt11 = make_class(new_wk.id, "XI IPA 1 (new)", grade_level=11)

    login(client, admin.email)
    resp = client.post(
        "/tahun-ajaran/rollover",
        data={
            "target_year_id": target.id,
            f"target-{source_class_id}": tgt11.id,
            f"teacher-{source_class_id}": new_wk.id,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200

    # Cohort promoted; cache + active year reflect the new year.
    db.session.refresh(violation_setup.student)
    assert violation_setup.student.class_id == tgt11.id
    db.session.refresh(target)
    assert target.is_active is True
    new_enrollment = ClassEnrollment.query.filter_by(
        student_id=violation_setup.student.id, academic_year_id=target.id
    ).one()
    assert new_enrollment.is_active is True
