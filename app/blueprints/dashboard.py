"""T15 — Dashboard: ranking by total_points, highlight > 200, HTMX auto-refresh 60s.

The dashboard is the landing page for every authenticated user (admin, guru_bk,
wali_kelas). It shows role-scoped monitoring data (§1.8):

  * Summary stat cards (total students, active SP, > 200-point alerts, expelled).
  * A ranking of students by ``total_points`` (§2.11) rendered via DataTables,
    with rows whose ``total_points > 200`` highlighted (display-only alert —
    no automatic action, §1.8 / §1.5).

The stat cards live inside an HTMX-polled panel that re-renders every 60 s
(`GET /dashboard/stats`). The ranking DataTable silently reloads its JSON on
the same cadence so the monitoring view stays fresh without a full page reload.

Wali kelas only ever see students in their own class (§1.1, consistent with
the scoping in every other blueprint); admin & guru_bk see everyone.
"""

from flask import Blueprint, jsonify, url_for
from flask_login import current_user, login_required

from ..helper import hx_render, sanitize, scope_students_to_role
from ..models import Class, Student, StudentPointSummary

bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")

# §1.8 / §1.4: total_points above this threshold is a display-only alert.
_ALERT_THRESHOLD = 200


def _scope_students():
    """Student query scoped to the current user's data access (§1.1).

    Delegates to ``scope_students_to_role`` so the R12 join lives in exactly
    one place; admin / guru_bk are returned unscoped.
    """
    return scope_students_to_role(Student.query)


def _scope_summaries():
    """StudentPointSummary query scoped to the current user (§1.1).

    A summary row only exists for students who have at least one violation or
    amnesty, so this is the right base for SP / point / expulsion stats.
    """
    q = StudentPointSummary.query.join(Student)
    if current_user.role == "wali_kelas":
        q = q.join(Class, Student.class_id == Class.id).filter(
            Class.homeroom_teacher_id == current_user.id
        )
    return q


def _compute_stats():
    """Aggregate monitoring stats for the dashboard cards (§1.8).

    All counts are scoped to the current user's data access. ``total_students``
    counts every student in scope (active + expelled etc.); the expelled card
    surfaces how many of those are no longer active.
    """
    total_students = _scope_students().count()

    students_with_sp = (
        _scope_summaries()
        .filter(StudentPointSummary.current_sp_level.isnot(None))
        .count()
    )

    alert_students = (
        _scope_summaries()
        .filter(StudentPointSummary.total_points > _ALERT_THRESHOLD)
        .count()
    )

    expelled_students = _scope_students().filter(Student.status == "expelled").count()

    return {
        "total_students": total_students,
        "students_with_sp": students_with_sp,
        "alert_students": alert_students,
        "alert_threshold": _ALERT_THRESHOLD,
        "expelled_students": expelled_students,
    }


def _row_actions(student_id):
    detail_url = url_for("students.detail", id=student_id)
    return (
        f'<div class="btn-group btn-group-sm">'
        f'<a class="btn btn-outline-info" href="{detail_url}" '
        f'hx-get="{detail_url}" hx-target="#hx_content" hx-swap="innerHTML" '
        f'title="Lihat detail siswa">'
        f'<i class="bi bi-eye"></i></a>'
        f"</div>"
    )


@bp.route("/")
@login_required
def index():
    stats = _compute_stats()
    return hx_render("dashboard/index.html", stats=stats)


@bp.route("/stats")
@login_required
def stats():
    """HTMX partial: re-rendered every 60 s (§1.8 auto-refresh).

    Returns only the stat cards markup so the poll swaps a small fragment,
    not the whole page.
    """
    return hx_render("dashboard/_stats.html", stats=_compute_stats())


@bp.route("/data")
@login_required
def data():
    """DataTables JSON feed — students ranked by ``total_points`` desc (§1.8).

    Only students with a summary row appear (i.e. those with at least one
    violation/amnesty). Rows with ``total_points > 200`` carry ``alert: True``
    so the DataTables ``createdRow`` callback can highlight them (§1.8).
    """
    q = _scope_summaries().order_by(
        StudentPointSummary.total_points.desc(),
        Student.name.asc(),
    )
    rows = []
    for i, s in enumerate(q.all(), 1):
        student = s.student
        rows.append(
            {
                "no": i,
                "nis": sanitize(student.nis),
                "name": sanitize(student.name),
                "class": sanitize(student.class_.name) if student.class_ else "-",
                "points": s.total_points,
                "sp": f"SP{s.current_sp_level}" if s.current_sp_level else "-",
                "status": student.status.capitalize(),
                "alert": s.total_points > _ALERT_THRESHOLD,
                "actions": _row_actions(student.id),
            }
        )
    return jsonify(data=rows)
