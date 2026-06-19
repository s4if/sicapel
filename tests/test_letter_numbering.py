"""Tests for letter_seq allocation (§8.3 / §13.4).

Deterministic and single-threaded. In-memory SQLite (``sqlite://``) is
per-connection, so it cannot reliably exercise real concurrency via
``threading``. The production race (two writers racing on MAX(seq)) is
therefore covered *analytically* by the IntegrityError backstop test
below: if a duplicate ``(academic_year_id, letter_seq)`` cannot persist,
then a racing commit cannot corrupt the sequence either — exactly one
wins, the other rolls back.
"""

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import AcademicYear, ExpulsionRecommendation
from app.services import make_letter_number, next_letter_seq


def _persist_expulsion(setup, *, seq, ay_id):
    """Insert a minimal ExpulsionRecommendation with the given seq and flush.

    ExpulsionRecommendation has nullable triggers, so it needs no
    violation/warning FK setup — the leanest way to populate letter_seq
    rows for allocation + constraint tests.
    """
    rec = ExpulsionRecommendation(
        letter_number=make_letter_number(seq, "DIK", "2026"),
        letter_seq=seq,
        student_id=setup.student.id,
        trigger_violation_record_id=None,
        trigger_warning_letter_id=None,
        reason="tes",
        total_points_at_issue=0,
        issued_by=setup.guru_bk.id,
        issue_date=date(2026, 9, 1),
        academic_year_id=ay_id,
        status="issued",
    )
    db.session.add(rec)
    db.session.flush()
    return rec


# ---------------------------------------------------------------------------
# 1. first allocation for a year returns 1 (empty table)
# ---------------------------------------------------------------------------
def test_first_allocation_returns_one(violation_setup):
    ay_id = violation_setup.ay.id
    assert next_letter_seq(ExpulsionRecommendation, ay_id, db.session) == 1


# ---------------------------------------------------------------------------
# 2. subsequent allocations increment monotonically — no gaps, no dups
# ---------------------------------------------------------------------------
def test_allocations_increment_monotonically(violation_setup):
    ay_id = violation_setup.ay.id
    expected = []
    for _ in range(4):
        seq = next_letter_seq(ExpulsionRecommendation, ay_id, db.session)
        expected.append(seq)
        _persist_expulsion(violation_setup, seq=seq, ay_id=ay_id)
    db.session.commit()

    assert expected == [1, 2, 3, 4]
    # next call after persisting 1..4 yields 5
    assert next_letter_seq(ExpulsionRecommendation, ay_id, db.session) == 5


# ---------------------------------------------------------------------------
# 3. sequences are independent per academic year
# ---------------------------------------------------------------------------
def test_sequences_independent_per_academic_year(violation_setup):
    ay_a = violation_setup.ay
    ay_b = AcademicYear(
        year="2027/2028",
        start_date=date(2027, 7, 1),
        end_date=date(2028, 6, 30),
        is_active=False,
    )
    db.session.add(ay_b)
    db.session.commit()

    # Populate year A with two letters.
    _persist_expulsion(violation_setup, seq=1, ay_id=ay_a.id)
    _persist_expulsion(violation_setup, seq=2, ay_id=ay_a.id)
    db.session.commit()

    # Year B starts fresh at 1; year A continues at 3.
    assert next_letter_seq(ExpulsionRecommendation, ay_b.id, db.session) == 1
    assert next_letter_seq(ExpulsionRecommendation, ay_a.id, db.session) == 3


# ---------------------------------------------------------------------------
# 4. letter_number format: {seq:03d}/<TYPE>/BK/{year}
# ---------------------------------------------------------------------------
def test_letter_number_format():
    assert make_letter_number(1, "SP1", "2026") == "001/SP1/BK/2026"
    assert make_letter_number(42, "SP2", "2026") == "042/SP2/BK/2026"
    # seq >= 1000 is not truncated (zero-pad is min-width 3)
    assert make_letter_number(1234, "DIK", "2027") == "1234/DIK/BK/2027"


# ---------------------------------------------------------------------------
# 5. backstop proof: duplicate (academic_year_id, letter_seq) cannot persist
#    This is the guarantee that makes the optimistic §8.3 strategy safe.
# ---------------------------------------------------------------------------
def test_duplicate_year_seq_raises_integrity_error(violation_setup):
    ay_id = violation_setup.ay.id
    _persist_expulsion(violation_setup, seq=1, ay_id=ay_id)
    db.session.commit()

    # Reusing seq=1 for the same academic year must violate the UNIQUE
    # constraint uq_expulsion_year_seq.
    with pytest.raises(IntegrityError):
        _persist_expulsion(violation_setup, seq=1, ay_id=ay_id)
        db.session.flush()
    db.session.rollback()
