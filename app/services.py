"""Service layer — all domain logic.

Functions accept an explicit ``session`` and do **not** commit; the route
caller commits (D10). Implements the SP-escalation rules of §1.4.
"""

from datetime import date

from sqlalchemy import func, select

from .models import (
    AcademicYear,
    ExpulsionRecommendation,
    PointAmnesty,
    Student,
    StudentPointSummary,
    ViolationRecord,
    ViolationType,
    WarningLetter,
)

# Letter-number type codes per §1.7 — format ``{seq:03d}/<TYPE>/BK/{year}``.
_EXPULSION_CODE = "DIK"
_AMNESTY_CODE = "PMT"


# ---------------------------------------------------------------------------
# Letter numbering (T8 — optimistic letter_seq allocation, §8.3)
# ---------------------------------------------------------------------------
def next_letter_seq(model, academic_year_id, session) -> int:
    """Optimistic ``letter_seq`` allocation (T8).

    Pattern: ``COALESCE(MAX(letter_seq), 0) + 1`` evaluated within the
    caller's open transaction. No ``SELECT ... FOR UPDATE`` and no
    ``BEGIN IMMEDIATE`` — concurrency safety comes from the
    ``UNIQUE(academic_year_id, letter_seq)`` constraint on every letter
    table (§2.13 / §8.3), not from row locking.

    Two concurrent allocations that race on the same MAX(seq) both pick
    the same value; exactly one survives COMMIT and the other raises
    ``IntegrityError`` and rolls back. For v1 a rare simultaneous
    collision is acceptable — the transaction rolls back and the error
    surfaces to the user, who retries. No automatic retry here.
    """
    stmt = (
        select(func.coalesce(func.max(model.letter_seq), 0))
        .where(model.academic_year_id == academic_year_id)
    )
    current_max = session.scalar(stmt) or 0
    return current_max + 1


def make_letter_number(seq, type_code, year_label) -> str:
    """Format ``{seq:03d}/<TYPE>/BK/{year}`` e.g. ``001/SP1/BK/2026``."""
    return f"{seq:03d}/{type_code}/BK/{year_label}"


def _year_label(year_value: str) -> str:
    """``"2026/2027"`` -> ``"2026"``."""
    return str(year_value).split("/")[0]


# ---------------------------------------------------------------------------
# Summary maintenance (partial T7 — total_points recompute backstop)
# ---------------------------------------------------------------------------
def recompute_summary(student_id, session) -> StudentPointSummary:
    """Recompute ``total_points`` and ``is_expelled`` from source of truth
    (§2.11, §8.4). Used after void/recover as the backstop.

    ``total_points = SUM(non-void violation_records.points)
                     − SUM(non-void point_amnesties.points_reduced)``
    and may be negative (§1.3).

    ``is_expelled`` is True iff the student has at least one non-void
    ``ExpulsionRecommendation`` — the authoritative trace of §1.5's two
    expulsion triggers (sangat_berat, or menengah/berat after SP3). The
    point/amnesty tables alone cannot reconstruct this without replaying
    the escalation history, so the expulsion table IS the source of truth.

    ``current_sp_level`` / ``last_sp_date`` are managed by
    ``record_violation`` / ``apply_amnesty`` (and the ``sp_reset`` flag) and
    are preserved here; replaying SP escalation from history is a T18 concern.
    """
    violation_total = session.scalar(
        select(func.coalesce(func.sum(ViolationRecord.points), 0))
        .where(ViolationRecord.student_id == student_id)
        .where(ViolationRecord.is_void.is_(False))
    ) or 0

    amnesty_total = session.scalar(
        select(func.coalesce(func.sum(PointAmnesty.points_reduced), 0))
        .where(PointAmnesty.student_id == student_id)
        .where(PointAmnesty.status != "void")
    ) or 0

    expulsion_count = session.scalar(
        select(func.coalesce(func.count(ExpulsionRecommendation.id), 0))
        .where(ExpulsionRecommendation.student_id == student_id)
        .where(ExpulsionRecommendation.status != "void")
    ) or 0
    is_expelled = expulsion_count > 0

    summary = session.get(StudentPointSummary, student_id)
    if summary is None:
        summary = StudentPointSummary(
            student_id=student_id,
            total_points=violation_total - amnesty_total,
            current_sp_level=None,
            last_sp_date=None,
            is_expelled=is_expelled,
        )
        session.add(summary)
    else:
        summary.total_points = violation_total - amnesty_total
        summary.is_expelled = is_expelled
    session.flush()
    return summary


# ---------------------------------------------------------------------------
# record_violation (T6)
# ---------------------------------------------------------------------------
def _next_sp_level(current) -> str:
    """``None -> "1"``, ``"1" -> "2"``, ``"2" -> "3"``. Assumes current != "3"."""
    if current is None:
        return "1"
    return str(int(current) + 1)


def _next_record_number(session, academic_year_id) -> str:
    """Auto-generated ``record_number`` for a violation record.

    Counts all records in the academic year (including voided) so voiding
    a record never causes a future record_number collision.
    """
    count = session.scalar(
        select(func.count(ViolationRecord.id))
        .where(ViolationRecord.academic_year_id == academic_year_id)
    ) or 0
    ay = session.get(AcademicYear, academic_year_id)
    return f"{_year_label(ay.year)}/PV/{count + 1:05d}"


def _issue_warning_letter(
    *,
    student_id,
    academic_year_id,
    level,  # "1" | "2" | "3"
    trigger_violation_record_id,
    total_points_at_issue,
    reason,
    issued_by,
    session,
) -> WarningLetter:
    level_code = f"SP{level}"
    seq = next_letter_seq(WarningLetter, academic_year_id, session)
    ay = session.get(AcademicYear, academic_year_id)
    letter = WarningLetter(
        letter_number=make_letter_number(seq, level_code, _year_label(ay.year)),
        letter_seq=seq,
        student_id=student_id,
        level=level_code,
        trigger_violation_record_id=trigger_violation_record_id,
        total_points_at_issue=total_points_at_issue,
        reason=reason,
        issued_by=issued_by,
        issue_date=date.today(),
        academic_year_id=academic_year_id,
        status="issued",
    )
    session.add(letter)
    session.flush()
    return letter


def _issue_expulsion(
    *,
    student_id,
    academic_year_id,
    trigger_violation_record_id,
    trigger_warning_letter_id,
    reason,
    total_points_at_issue,
    issued_by,
    session,
) -> ExpulsionRecommendation:
    seq = next_letter_seq(ExpulsionRecommendation, academic_year_id, session)
    ay = session.get(AcademicYear, academic_year_id)
    rec = ExpulsionRecommendation(
        letter_number=make_letter_number(seq, _EXPULSION_CODE, _year_label(ay.year)),
        letter_seq=seq,
        student_id=student_id,
        trigger_violation_record_id=trigger_violation_record_id,
        trigger_warning_letter_id=trigger_warning_letter_id,
        reason=reason,
        total_points_at_issue=total_points_at_issue,
        issued_by=issued_by,
        issue_date=date.today(),
        academic_year_id=academic_year_id,
        status="issued",
    )
    session.add(rec)
    session.flush()
    return rec


def record_violation(
    *,
    student_id,
    violation_type_id,
    points,
    chronology,
    location,
    incident_date,
    incident_time,
    academic_year_id,
    semester,
    recorded_by,
    session,
) -> dict:
    """Record a violation and apply §1.4 escalation rules. Atomic; caller commits.

    Returns::

        {'violation': ViolationRecord,
         'new_warning': WarningLetter | None,
         'new_expulsion': ExpulsionRecommendation | None,
         'summary': StudentPointSummary,
         'student_expelled': bool}
    """
    vtype = session.get(ViolationType, violation_type_id)
    category = vtype.category
    cat_name = category.name

    # --- Step 1: persist the violation record (always, for every category). ---
    violation = ViolationRecord(
        record_number=_next_record_number(session, academic_year_id),
        student_id=student_id,
        violation_type_id=violation_type_id,
        category_id=category.id,
        points=points,
        chronology=chronology,
        location=location,
        incident_date=incident_date,
        incident_time=incident_time,
        academic_year_id=academic_year_id,
        semester=semester,
        recorded_by=recorded_by,
        is_void=False,
    )
    session.add(violation)
    session.flush()  # flush so violation.id is available for FK references below

    # --- Step 2: refresh the cached summary so total_points includes this
    # violation. recompute_summary() sums non-void violations minus non-void
    # amnesties (§2.11). The SP-level fields are NOT touched here; they are
    # driven by the escalation logic below. ---
    summary = recompute_summary(student_id, session)
    total = summary.total_points

    student = session.get(Student, student_id)
    # level is None (no SP yet) or "1"/"2"/"3" (current SP level).
    level = summary.current_sp_level

    new_warning = None
    new_expulsion = None
    student_expelled = False

    def _expel(trigger_warning_id, reason):
        # Helper: issue an ExpulsionRecommendation, flip student.status to
        # "expelled", and mark the summary. Shared by both expulsion triggers
        # (sangat_berat + post-SP3) per §1.5.
        nonlocal new_expulsion, student_expelled
        new_expulsion = _issue_expulsion(
            student_id=student_id,
            academic_year_id=academic_year_id,
            trigger_violation_record_id=violation.id,
            trigger_warning_letter_id=trigger_warning_id,
            reason=reason,
            total_points_at_issue=total,
            issued_by=recorded_by,
            session=session,
        )
        student.status = "expelled"
        summary.is_expelled = True
        student_expelled = True

    # --- Step 3: apply the §1.4 escalation matrix.
    # The branches below MUST stay in this exact order because the checks
    # narrow from most-severe to least-severe. Order matters: e.g. the
    # post-SP3 expulsion check (level == "3") must come BEFORE the category
    # checks so a berat/menengah committed after SP3 expels rather than
    # (incorrectly) trying to escalate past SP3.
    if cat_name == "sangat_berat":
        # §1.4 row 1 / §1.5 trigger 1: sangat_berat ALWAYS means immediate
        # expulsion, regardless of current SP level or point total.
        _expel(
            None,
            f"Dikeluarkan karena pelanggaran sangat berat ({vtype.name}).",
        )
    elif level == "3":
        # §1.4 final rule / §1.5 trigger 2: any menengah/berat violation
        # committed AFTER SP3 triggers expulsion. (ringan falls through to
        # "points only" since it never enters this elif chain — see below.)
        _expel(
            None,
            f"Dikeluarkan karena pelanggaran {cat_name} setelah SP3.",
        )
    elif cat_name == "berat":
        # §1.4 rows 2-4: berat issues SP1 from null, or escalates SP1->SP2 /
        # SP2->SP3. (level == "3" is already handled above, so _next_sp_level
        # is only ever called with None/"1"/"2" here — it never overflows.)
        new_level = _next_sp_level(level)
        new_warning = _issue_warning_letter(
            student_id=student_id,
            academic_year_id=academic_year_id,
            level=new_level,
            trigger_violation_record_id=violation.id,
            total_points_at_issue=total,
            reason=f"Diterbitkan karena pelanggaran berat ({vtype.name}, {points} poin).",
            issued_by=recorded_by,
            session=session,
        )
        summary.current_sp_level = new_level
        summary.last_sp_date = new_warning.issue_date
    elif cat_name == "menengah":
        if level is not None:
            # §1.4 row 5: menengah with an EXISTING SP escalates exactly like
            # berat (SP1->SP2->SP3). No point threshold applies here.
            new_level = _next_sp_level(level)
            new_warning = _issue_warning_letter(
                student_id=student_id,
                academic_year_id=academic_year_id,
                level=new_level,
                trigger_violation_record_id=violation.id,
                total_points_at_issue=total,
                reason=f"Diterbitkan karena pelanggaran menengah ({vtype.name}, {points} poin).",
                issued_by=recorded_by,
                session=session,
            )
            summary.current_sp_level = new_level
            summary.last_sp_date = new_warning.issue_date
        elif total > 100:
            # §1.4 row 6: menengah with NO prior SP but total_points > 100
            # (measured AFTER adding this violation's points) issues SP1.
            new_warning = _issue_warning_letter(
                student_id=student_id,
                academic_year_id=academic_year_id,
                level="1",
                trigger_violation_record_id=violation.id,
                total_points_at_issue=total,
                reason=f"Diterbitkan karena pelanggaran menengah ({vtype.name}, {points} poin), total poin {total}.",
                issued_by=recorded_by,
                session=session,
            )
            summary.current_sp_level = "1"
            summary.last_sp_date = new_warning.issue_date
        # §1.4 row 7 (implicit): menengah, no prior SP, total <= 100 —
        # points only, no letter. Nothing to do; falls through.

    # §1.4 row 8 (implicit): ringan ALWAYS yields points only. It never
    # reaches any of the branches above (none match cat_name == "ringan"),
    # so no SP is issued and no expulsion occurs. The violation recorded in
    # Step 1 is the only side effect.

    session.flush()
    return {
        "violation": violation,
        "new_warning": new_warning,
        "new_expulsion": new_expulsion,
        "summary": summary,
        "student_expelled": student_expelled,
    }


# ---------------------------------------------------------------------------
# apply_amnesty (T7)
# ---------------------------------------------------------------------------
def apply_amnesty(
    *,
    student_id,
    points_reduced,
    sp_reset,
    reason,
    reason_category,
    principal_name,
    issue_date,
    academic_year_id,
    recorded_by,
    signed_document_id,
    session,
) -> PointAmnesty:
    """Record a point amnesty (pemutihan) per §1.6. Atomic; caller commits.

    - ``points_reduced`` is a positive integer; the student's
      ``total_points`` is reduced by exactly that amount and MAY go negative
      (never clamped to 0 — §1.3 / §1.6 "No limit on reduction amount").
    - If ``sp_reset`` is True, ``current_sp_level`` and ``last_sp_date`` are
      cleared (student is "clean" of the active SP). Historical
      ``warning_letters`` rows are NEVER deleted (§1.6).
    - A signed scanned letter is mandatory; the caller must pass an existing
      ``documents.id`` (``signed_document_id``). Amnesty does NOT un-expel a
      student — ``is_expelled`` / ``student.status`` are untouched here.
    """
    if points_reduced <= 0:
        # §1.6 implies a real reduction; guard against zero/negative input
        # which would silently no-op or inflate the totals.
        raise ValueError("points_reduced must be a positive integer")

    seq = next_letter_seq(PointAmnesty, academic_year_id, session)
    ay = session.get(AcademicYear, academic_year_id)
    amnesty = PointAmnesty(
        letter_number=make_letter_number(seq, _AMNESTY_CODE, _year_label(ay.year)),
        letter_seq=seq,
        student_id=student_id,
        points_reduced=points_reduced,
        reason_category=reason_category,
        reason=reason,
        sp_reset=sp_reset,
        principal_name=principal_name,
        recorded_by=recorded_by,
        issue_date=issue_date,
        academic_year_id=academic_year_id,
        signed_document_id=signed_document_id,
        status="issued",
    )
    session.add(amnesty)
    session.flush()

    # Refresh the cached summary so total_points reflects the reduction.
    # recompute_summary sums non-void violations minus non-void amnesties,
    # and the row just inserted (status="issued") is included automatically.
    summary = recompute_summary(student_id, session)

    if sp_reset:
        # §1.6 sp_reset=True: clear the active SP level + date. Historical
        # warning_letters are preserved (never deleted) — only the cached
        # "current" level is reset so future menengah/berat re-escalate from
        # null instead of from the old level.
        summary.current_sp_level = None
        summary.last_sp_date = None

    session.flush()
    return amnesty
