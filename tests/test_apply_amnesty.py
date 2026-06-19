"""Tests for services.apply_amnesty (§1.6) and recompute_summary (§8.4).

Covers the pemutihan rules:
  - points_reduced reduces total_points and MAY drive it negative (§1.3/§1.6);
  - sp_reset=True clears current_sp_level / last_sp_date but never deletes
    historical warning_letters;
  - sp_reset=False leaves the active SP level untouched;
  - amnesty never un-expels a student;
  - recompute_summary is the source-of-truth backstop for total_points AND
    is_expelled (T7 portion of §8.4).
"""

from datetime import date

import pytest

from app import db
from app.models import (
    ExpulsionRecommendation,
    PointAmnesty,
    Student,
    StudentPointSummary,
    WarningLetter,
)
from app.services import apply_amnesty, recompute_summary, record_violation

from conftest import make_document

_ISSUE = date(2026, 10, 1)


def _amnesty(
    setup,
    *,
    points_reduced=50,
    sp_reset=False,
    reason="Prestasi OSN",
    reason_category="prestasi",
    principal_name="Drs. Kepala Sekolah",
    signed_document_id=None,
    issue_date=_ISSUE,
):
    """Call apply_amnesty with sane defaults, commit, and return the row."""
    if signed_document_id is None:
        doc = make_document(setup.guru_bk.id)
        signed_document_id = doc.id
    amnesty = apply_amnesty(
        student_id=setup.student.id,
        points_reduced=points_reduced,
        sp_reset=sp_reset,
        reason=reason,
        reason_category=reason_category,
        principal_name=principal_name,
        issue_date=issue_date,
        academic_year_id=setup.ay.id,
        recorded_by=setup.guru_bk.id,
        signed_document_id=signed_document_id,
        session=db.session,
    )
    db.session.commit()
    return amnesty


def _give_points(setup, points, via="ringan"):
    """Accumulate ``points`` via point-only violations (no SP escalation).

    ringan yields points only (§1.4 row 8) so we can dial up a known total
    without side-effecting the SP level. Each ringan default is 25.
    """
    per = setup.vt_ringan.default_points
    assert points % per == 0, "test helper expects a multiple of ringan default"
    for _ in range(points // per):
        record_violation(
            student_id=setup.student.id,
            violation_type_id=setup.vt_ringan.id,
            points=per,
            chronology="tes",
            location="",
            incident_date=_ISSUE,
            incident_time=None,
            academic_year_id=setup.ay.id,
            semester="1",
            recorded_by=setup.guru_bk.id,
            session=db.session,
        )
    db.session.commit()


def _summary(setup):
    return db.session.get(StudentPointSummary, setup.student.id)


# ---------------------------------------------------------------------------
# 1. Amnesty reduces total_points
# ---------------------------------------------------------------------------
def test_amnesty_reduces_points(violation_setup):
    _give_points(violation_setup, 100)
    assert _summary(violation_setup).total_points == 100

    _amnesty(violation_setup, points_reduced=30)

    assert _summary(violation_setup).total_points == 70


# ---------------------------------------------------------------------------
# 2. Points may go negative (§1.3 / §1.6 — never clamped to 0)
# ---------------------------------------------------------------------------
def test_amnesty_can_drive_total_negative(violation_setup):
    _give_points(violation_setup, 25)

    _amnesty(violation_setup, points_reduced=100)

    summary = _summary(violation_setup)
    assert summary.total_points == -75
    assert summary.total_points < 0  # explicit: no floor at zero


# ---------------------------------------------------------------------------
# 3. sp_reset=False keeps the active SP level + date
# ---------------------------------------------------------------------------
def test_sp_reset_false_keeps_sp_level(violation_setup):
    # Reach SP2 via two berat violations (null -> SP1 -> SP2).
    for _ in range(2):
        record_violation(
            student_id=violation_setup.student.id,
            violation_type_id=violation_setup.vt_berat.id,
            points=violation_setup.vt_berat.default_points,
            chronology="",
            location="",
            incident_date=_ISSUE,
            incident_time=None,
            academic_year_id=violation_setup.ay.id,
            semester="1",
            recorded_by=violation_setup.guru_bk.id,
            session=db.session,
        )
    db.session.commit()
    before = _summary(violation_setup)
    assert before.current_sp_level == "2"
    assert before.last_sp_date is not None
    warnings_before = db.session.query(WarningLetter).count()

    _amnesty(violation_setup, points_reduced=10, sp_reset=False)

    after = _summary(violation_setup)
    assert after.current_sp_level == "2"
    assert after.last_sp_date == before.last_sp_date
    # Historical warning letters are never deleted (§1.6).
    assert db.session.query(WarningLetter).count() == warnings_before


# ---------------------------------------------------------------------------
# 4. sp_reset=True clears current_sp_level / last_sp_date
# ---------------------------------------------------------------------------
def test_sp_reset_true_clears_sp_level(violation_setup):
    for _ in range(2):  # -> SP2
        record_violation(
            student_id=violation_setup.student.id,
            violation_type_id=violation_setup.vt_berat.id,
            points=violation_setup.vt_berat.default_points,
            chronology="",
            location="",
            incident_date=_ISSUE,
            incident_time=None,
            academic_year_id=violation_setup.ay.id,
            semester="1",
            recorded_by=violation_setup.guru_bk.id,
            session=db.session,
        )
    db.session.commit()
    assert _summary(violation_setup).current_sp_level == "2"
    warnings_before = db.session.query(WarningLetter).count()

    _amnesty(violation_setup, points_reduced=10, sp_reset=True)

    after = _summary(violation_setup)
    assert after.current_sp_level is None
    assert after.last_sp_date is None
    # Historical warning letters are preserved, NOT deleted (§1.6).
    assert db.session.query(WarningLetter).count() == warnings_before


# ---------------------------------------------------------------------------
# 5. sp_reset=True lets SP re-escalate from null afterwards
# ---------------------------------------------------------------------------
def test_sp_reset_allows_re_escalation_from_null(violation_setup):
    # SP2 via two berat, then reset via amnesty.
    for _ in range(2):
        record_violation(
            student_id=violation_setup.student.id,
            violation_type_id=violation_setup.vt_berat.id,
            points=violation_setup.vt_berat.default_points,
            chronology="",
            location="",
            incident_date=_ISSUE,
            incident_time=None,
            academic_year_id=violation_setup.ay.id,
            semester="1",
            recorded_by=violation_setup.guru_bk.id,
            session=db.session,
        )
    db.session.commit()
    _amnesty(violation_setup, points_reduced=10, sp_reset=True)
    assert _summary(violation_setup).current_sp_level is None

    # A new berat after reset re-issues SP1 (not SP3) — confirms reset took.
    res = record_violation(
        student_id=violation_setup.student.id,
        violation_type_id=violation_setup.vt_berat.id,
        points=violation_setup.vt_berat.default_points,
        chronology="",
        location="",
        incident_date=_ISSUE,
        incident_time=None,
        academic_year_id=violation_setup.ay.id,
        semester="1",
        recorded_by=violation_setup.guru_bk.id,
        session=db.session,
    )
    db.session.commit()
    assert res["new_warning"].level == "SP1"
    assert _summary(violation_setup).current_sp_level == "1"


# ---------------------------------------------------------------------------
# 6. Letter numbering format + per-year increment (§1.7)
# ---------------------------------------------------------------------------
def test_amnesty_letter_numbering_format(violation_setup):
    am = _amnesty(violation_setup)
    assert am.letter_number == "001/PMT/BK/2026"
    assert am.letter_seq == 1


def test_amnesty_seq_increments_per_year(violation_setup):
    a1 = _amnesty(violation_setup)
    a2 = _amnesty(violation_setup)
    assert a1.letter_seq == 1
    assert a2.letter_seq == 2
    assert a2.letter_number == "002/PMT/BK/2026"
    assert db.session.query(PointAmnesty).count() == 2


# ---------------------------------------------------------------------------
# 7. Persisted fields round-trip correctly
# ---------------------------------------------------------------------------
def test_amnesty_persists_all_fields(violation_setup):
    doc = make_document(violation_setup.guru_bk.id, file_name="signed.pdf")
    am = _amnesty(
        violation_setup,
        points_reduced=40,
        sp_reset=True,
        reason="Kerja bakti",
        reason_category="kerja_bakti",
        principal_name="Budi Saputra, M.Pd",
        signed_document_id=doc.id,
        issue_date=date(2026, 11, 9),
    )

    fresh = db.session.get(PointAmnesty, am.id)
    assert fresh.points_reduced == 40
    assert fresh.reason_category == "kerja_bakti"
    assert fresh.reason == "Kerja bakti"
    assert fresh.sp_reset is True
    assert fresh.principal_name == "Budi Saputra, M.Pd"
    assert fresh.recorded_by == violation_setup.guru_bk.id
    assert fresh.signed_document_id == doc.id
    assert fresh.status == "issued"
    assert fresh.issue_date == date(2026, 11, 9)
    assert fresh.academic_year_id == violation_setup.ay.id


# ---------------------------------------------------------------------------
# 8. Amnesty does NOT un-expel a student (§1.6 is silent on expulsion;
#    expulsion only follows §1.5 triggers)
# ---------------------------------------------------------------------------
def test_amnesty_does_not_un_expel(violation_setup):
    # Expel via sangat_berat.
    record_violation(
        student_id=violation_setup.student.id,
        violation_type_id=violation_setup.vt_sangat.id,
        points=violation_setup.vt_sangat.default_points,
        chronology="",
        location="",
        incident_date=_ISSUE,
        incident_time=None,
        academic_year_id=violation_setup.ay.id,
        semester="1",
        recorded_by=violation_setup.guru_bk.id,
        session=db.session,
    )
    db.session.commit()
    student = db.session.get(Student, violation_setup.student.id)
    assert student.status == "expelled"
    assert _summary(violation_setup).is_expelled is True

    _amnesty(violation_setup, points_reduced=200, sp_reset=True)

    # Amnesty reduces points and resets SP, but the student stays expelled.
    student = db.session.get(Student, violation_setup.student.id)
    assert student.status == "expelled"
    assert _summary(violation_setup).is_expelled is True


# ---------------------------------------------------------------------------
# 9. Service does not commit (D10 — caller controls the transaction)
# ---------------------------------------------------------------------------
def test_apply_amnesty_does_not_commit(violation_setup, app):
    apply_amnesty(
        student_id=violation_setup.student.id,
        points_reduced=10,
        sp_reset=False,
        reason="x",
        reason_category="lainnya",
        principal_name="P",
        issue_date=_ISSUE,
        academic_year_id=violation_setup.ay.id,
        recorded_by=violation_setup.guru_bk.id,
        signed_document_id=make_document(violation_setup.guru_bk.id).id,
        session=db.session,
    )
    db.session.rollback()  # caller abandons — nothing should persist

    assert db.session.query(PointAmnesty).count() == 0


# ---------------------------------------------------------------------------
# 10. Guard: points_reduced must be positive
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [0, -1, -100])
def test_apply_amnesty_rejects_non_positive_points(violation_setup, bad):
    with pytest.raises(ValueError):
        apply_amnesty(
            student_id=violation_setup.student.id,
            points_reduced=bad,
            sp_reset=False,
            reason="x",
            reason_category="lainnya",
            principal_name="P",
            issue_date=_ISSUE,
            academic_year_id=violation_setup.ay.id,
            recorded_by=violation_setup.guru_bk.id,
            signed_document_id=make_document(violation_setup.guru_bk.id).id,
            session=db.session,
        )


# ---------------------------------------------------------------------------
# 11. recompute_summary backstop: total_points follows voided amnesties
# ---------------------------------------------------------------------------
def test_recompute_excludes_voided_amnesty(violation_setup):
    _give_points(violation_setup, 100)
    am = _amnesty(violation_setup, points_reduced=60)
    assert _summary(violation_setup).total_points == 40

    # Void the amnesty (T18 will wire the flow; here we void at the source).
    am.status = "void"
    db.session.commit()

    recompute_summary(violation_setup.student.id, db.session)
    db.session.commit()
    # Voided amnesty no longer counts → points bounce back to 100.
    assert _summary(violation_setup).total_points == 100


# ---------------------------------------------------------------------------
# 12. recompute_summary backstop: is_expelled follows non-void expulsions
# ---------------------------------------------------------------------------
def test_recompute_is_expelled_follows_expulsion_status(violation_setup):
    _give_points(violation_setup, 25)
    sid = violation_setup.student.id

    # No expulsion → not expelled.
    recompute_summary(sid, db.session)
    assert _summary(violation_setup).is_expelled is False

    # Issue an expulsion directly (bypassing record_violation) to exercise
    # the backstop in isolation.
    er = ExpulsionRecommendation(
        letter_number="001/DIK/BK/2026",
        letter_seq=1,
        student_id=sid,
        reason="tes",
        total_points_at_issue=25,
        issued_by=violation_setup.guru_bk.id,
        issue_date=_ISSUE,
        academic_year_id=violation_setup.ay.id,
        status="issued",
    )
    db.session.add(er)
    db.session.commit()
    recompute_summary(sid, db.session)
    assert _summary(violation_setup).is_expelled is True

    # Void it → is_expelled flips back to False.
    er.status = "void"
    db.session.commit()
    recompute_summary(sid, db.session)
    assert _summary(violation_setup).is_expelled is False


# ---------------------------------------------------------------------------
# 13. recompute_summary backstop: voided violations stop counting
# ---------------------------------------------------------------------------
def test_recompute_excludes_voided_violations(violation_setup):
    _give_points(violation_setup, 50)
    from app.models import ViolationRecord

    # Void one of the two ringan records (-25).
    rec = db.session.query(ViolationRecord).first()
    rec.is_void = True
    db.session.commit()

    recompute_summary(violation_setup.student.id, db.session)
    assert _summary(violation_setup).total_points == 25
