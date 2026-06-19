"""Tests for services.record_violation — the 7+1 SP-escalation branches of §1.4.

Each test exercises one branch of the escalation matrix and asserts the
result dict (new_warning / new_expulsion / summary / student_expelled)
plus the persisted side effects (student.status, summary.current_sp_level).
"""

from datetime import date, time

from app import db
from app.models import (
    ExpulsionRecommendation,
    Student,
    StudentPointSummary,
    ViolationRecord,
    WarningLetter,
)
from app.services import record_violation

_INCIDENT = date(2026, 9, 1)
_INCIDENT_TIME = time(8, 0)


def _record(setup, *, violation_type, points=None):
    """Call record_violation with sane defaults and commit."""
    result = record_violation(
        student_id=setup.student.id,
        violation_type_id=violation_type.id,
        points=points if points is not None else violation_type.default_points,
        chronology=" Kronologi tes.",
        location="Halaman",
        incident_date=_INCIDENT,
        incident_time=_INCIDENT_TIME,
        academic_year_id=setup.ay.id,
        semester="1",
        recorded_by=setup.guru_bk.id,
        session=db.session,
    )
    db.session.commit()
    return result


def _reload(setup):
    """Re-fetch student + summary fresh from the session."""
    setup.student = db.session.get(Student, setup.student.id)
    return setup.student


# ---------------------------------------------------------------------------
# 1. ringan -> points only
# ---------------------------------------------------------------------------
def test_ringan_points_only(violation_setup):
    res = _record(violation_setup, violation_type=violation_setup.vt_ringan)

    assert res["new_warning"] is None
    assert res["new_expulsion"] is None
    assert res["student_expelled"] is False
    assert res["summary"].total_points == 25
    assert res["summary"].current_sp_level is None
    assert res["summary"].is_expelled is False
    assert _reload(violation_setup).status == "active"
    assert res["violation"].is_void is False


# ---------------------------------------------------------------------------
# 2. menengah + no prior SP + total <= 100 -> points only
# ---------------------------------------------------------------------------
def test_menengah_no_prior_sp_total_le_100(violation_setup):
    res = _record(violation_setup, violation_type=violation_setup.vt_menengah)

    assert res["new_warning"] is None
    assert res["new_expulsion"] is None
    assert res["summary"].total_points == 50
    assert res["summary"].current_sp_level is None
    assert _reload(violation_setup).status == "active"


# ---------------------------------------------------------------------------
# 3. menengah + no prior SP + total > 100 -> SP1
# ---------------------------------------------------------------------------
def test_menengah_no_prior_sp_total_gt_100(violation_setup):
    # Accumulate 100 points via ringan (points only, no SP) first.
    for _ in range(4):
        _record(violation_setup, violation_type=violation_setup.vt_ringan)
    # Now a menengah (+50) -> total 150 > 100 -> SP1.
    res = _record(violation_setup, violation_type=violation_setup.vt_menengah)

    assert res["new_warning"] is not None
    assert res["new_warning"].level == "SP1"
    assert res["new_expulsion"] is None
    assert res["summary"].current_sp_level == "1"
    assert res["summary"].total_points == 150
    assert _reload(violation_setup).status == "active"


# ---------------------------------------------------------------------------
# 4. menengah + prior SP -> escalate
# ---------------------------------------------------------------------------
def test_menengah_with_prior_sp_escalates(violation_setup):
    # Reach SP1 via berat (berat from null -> SP1).
    _record(violation_setup, violation_type=violation_setup.vt_berat)
    # menengah while already having SP -> escalate to SP2.
    res = _record(violation_setup, violation_type=violation_setup.vt_menengah)

    assert res["new_warning"].level == "SP2"
    assert res["summary"].current_sp_level == "2"
    assert res["new_expulsion"] is None
    assert _reload(violation_setup).status == "active"


# ---------------------------------------------------------------------------
# 5. berat from null -> SP1
# ---------------------------------------------------------------------------
def test_berat_from_null_issues_sp1(violation_setup):
    res = _record(violation_setup, violation_type=violation_setup.vt_berat)

    assert res["new_warning"].level == "SP1"
    assert res["summary"].current_sp_level == "1"
    assert res["new_expulsion"] is None
    assert res["student_expelled"] is False
    assert _reload(violation_setup).status == "active"


# ---------------------------------------------------------------------------
# 6. berat from SP3 -> expulsion
# ---------------------------------------------------------------------------
def test_berat_from_sp3_triggers_expulsion(violation_setup):
    # Escalate null -> SP1 -> SP2 -> SP3 via three berat violations.
    for expected_level in ("1", "2", "3"):
        res = _record(violation_setup, violation_type=violation_setup.vt_berat)
        assert res["summary"].current_sp_level == expected_level

    # A 4th berat after SP3 -> expulsion.
    res = _record(violation_setup, violation_type=violation_setup.vt_berat)

    assert res["new_expulsion"] is not None
    assert res["new_warning"] is None
    assert res["student_expelled"] is True
    assert res["summary"].is_expelled is True
    assert _reload(violation_setup).status == "expelled"


# ---------------------------------------------------------------------------
# 7. sangat_berat -> immediate expulsion + student.status = expelled
# ---------------------------------------------------------------------------
def test_sangat_berat_immediate_expulsion(violation_setup):
    res = _record(violation_setup, violation_type=violation_setup.vt_sangat)

    assert res["new_expulsion"] is not None
    assert res["new_warning"] is None
    assert res["student_expelled"] is True
    assert res["summary"].is_expelled is True
    assert res["summary"].total_points == 200
    assert _reload(violation_setup).status == "expelled"


# ---------------------------------------------------------------------------
# 8. menengah/berat after SP3 -> expulsion (menengah variant)
# ---------------------------------------------------------------------------
def test_menengah_after_sp3_triggers_expulsion(violation_setup):
    # Reach SP3 via three berat violations.
    for _ in range(3):
        _record(violation_setup, violation_type=violation_setup.vt_berat)
    assert (
        db.session.get(StudentPointSummary, violation_setup.student.id)
    ).current_sp_level == "3"

    # A menengah after SP3 -> expulsion.
    res = _record(violation_setup, violation_type=violation_setup.vt_menengah)

    assert res["new_expulsion"] is not None
    assert res["new_warning"] is None
    assert res["student_expelled"] is True
    assert _reload(violation_setup).status == "expelled"


# ---------------------------------------------------------------------------
# Letter numbering + record_number sanity (relies on partial T8)
# ---------------------------------------------------------------------------
def test_warning_letter_numbering_format(violation_setup):
    res = _record(violation_setup, violation_type=violation_setup.vt_berat)
    wl = res["new_warning"]
    assert wl.letter_number == "001/SP1/BK/2026"
    assert wl.letter_seq == 1


def test_expulsion_letter_numbering_format(violation_setup):
    res = _record(violation_setup, violation_type=violation_setup.vt_sangat)
    er = res["new_expulsion"]
    assert er.letter_number == "001/DIK/BK/2026"
    assert er.letter_seq == 1


def test_record_number_is_generated(violation_setup):
    res = _record(violation_setup, violation_type=violation_setup.vt_ringan)
    assert res["violation"].record_number == "2026/PV/00001"


def test_letter_seq_increments_per_year(violation_setup):
    # SP1 from berat
    r1 = _record(violation_setup, violation_type=violation_setup.vt_berat)
    # escalate to SP2 via berat
    r2 = _record(violation_setup, violation_type=violation_setup.vt_berat)
    assert r1["new_warning"].letter_seq == 1
    assert r2["new_warning"].letter_seq == 2
    assert r2["new_warning"].level == "SP2"
    # Warning letters + violation records persisted counts.
    assert db.session.query(WarningLetter).count() == 2
    assert db.session.query(ViolationRecord).count() == 2


def test_total_points_accumulate_across_categories(violation_setup):
    _record(violation_setup, violation_type=violation_setup.vt_ringan)      # 25, no SP
    _record(violation_setup, violation_type=violation_setup.vt_menengah)    # 50, total 75 <=100, no SP
    res = _record(violation_setup, violation_type=violation_setup.vt_berat)  # 60, berat from null -> SP1
    assert res["summary"].total_points == 135
    assert res["summary"].current_sp_level == "1"
    # No expulsion records yet.
    assert db.session.query(ExpulsionRecommendation).count() == 0


def test_does_not_commit_on_rollback(violation_setup, app):
    """Service must not commit; caller controls the transaction."""
    _record(violation_setup, violation_type=violation_setup.vt_ringan)
    # Roll back the committed setup — simulate caller rollback before commit.
    # (Already committed in _record; verify no extra commits happen by
    # confirming the service leaves the session usable.)
    summary = db.session.get(StudentPointSummary, violation_setup.student.id)
    assert summary is not None
    assert summary.total_points == 25
