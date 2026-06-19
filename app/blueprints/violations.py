from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from ..forms import ViolationRecordForm
from ..helper import (
    current_academic_year,
    hx_render,
    role_required,
    sanitize,
)
from ..models import (
    Class,
    Student,
    StudentPointSummary,
    ViolationRecord,
    ViolationType,
)
from ..services import record_violation, recompute_summary

bp = Blueprint("violations", __name__, url_prefix="/pelanggaran")


def _student_choices():
    q = Student.query.filter(Student.status != "expelled").order_by(Student.name)
    if current_user.role == "wali_kelas":
        q = q.filter(Student.class_.homeroom_teacher_id == current_user.id)
    return [(s.id, f"{s.name} ({s.nis} - {s.class_.name})") for s in q.all()]


def _violation_type_choices():
    return [
        (vt.id, f"{vt.name} ({vt.category.name}, {vt.default_points} poin)")
        for vt in ViolationType.query.filter_by(is_active=True)
        .order_by(ViolationType.name)
        .all()
    ]


def _class_choices():
    return [
        (c.id, f"{c.name} (Kelas {c.grade_level})")
        for c in Class.query.order_by(Class.grade_level, Class.name).all()
    ]


def _row_actions(v):
    detail_url = f"{v.id}"
    return (
        f'<div class="btn-group btn-group-sm">'
        f'<a class="btn btn-outline-info" href="{detail_url}" '
        f'hx-get="{detail_url}" hx-target="#hx_content" hx-swap="innerHTML">'
        f'<i class="bi bi-eye"></i></a>'
        f'<button class="btn btn-outline-danger" type="button" '
        f'onclick="hapus_violation({v.id}, \'{sanitize(v.student.name)}\')">'
        f'<i class="bi bi-x-circle"></i></button>'
        f"</div>"
    )


@bp.route("/")
@login_required
@role_required("admin", "guru_bk", "wali_kelas")
def index():
    return hx_render("violations/index.html")


@bp.route("/data")
@login_required
@role_required("admin", "guru_bk", "wali_kelas")
def data():
    q = ViolationRecord.query.filter_by(is_void=False)
    if current_user.role == "wali_kelas":
        q = q.join(Student).filter(
            Student.class_.homeroom_teacher_id == current_user.id
        )
    rows = []
    for i, v in enumerate(
        q.order_by(ViolationRecord.created_at.desc()).all(), 1
    ):
        rows.append(
            {
                "no": i,
                "student": sanitize(v.student.name),
                "type": sanitize(v.violation_type.name),
                "category": v.category.name.capitalize() if v.category else "-",
                "points": v.points,
                "date": v.incident_date.isoformat(),
                "actions": _row_actions(v),
            }
        )
    return jsonify(data=rows)


@bp.route("/preview-points")
@login_required
@role_required("admin", "guru_bk", "wali_kelas")
def preview_points():
    violation_type_id = request.args.get("violation_type_id", type=int)
    student_id = request.args.get("student_id", type=int)

    if not violation_type_id:
        return jsonify(
            {
                "points": 0,
                "category": "",
                "will_trigger_sp": False,
                "sp_level": None,
            }
        )

    vt = ViolationType.query.get_or_404(violation_type_id)
    category = vt.category

    will_trigger_sp = False
    sp_level = None

    if student_id:
        summary = StudentPointSummary.query.filter_by(
            student_id=student_id
        ).first()
        level = summary.current_sp_level if summary else None
        total = summary.total_points if summary else 0

        if category.name == "sangat_berat":
            will_trigger_sp = False
        elif level == "3":
            will_trigger_sp = False
        elif category.name == "berat":
            will_trigger_sp = True
            sp_level = "1" if level is None else str(int(level) + 1)
        elif category.name == "menengah":
            if level is not None:
                will_trigger_sp = True
                sp_level = str(int(level) + 1)
            elif total + vt.default_points > 100:
                will_trigger_sp = True
                sp_level = "1"

    return jsonify(
        {
            "points": vt.default_points,
            "category": category.name.capitalize() if category else "",
            "will_trigger_sp": will_trigger_sp,
            "sp_level": sp_level,
        }
    )


@bp.route("/by-type/<int:violation_type_id>")
@login_required
@role_required("admin", "guru_bk", "wali_kelas")
def by_type(violation_type_id):
    vt = ViolationType.query.get_or_404(violation_type_id)
    return jsonify(
        {
            "id": vt.id,
            "name": vt.name,
            "default_points": vt.default_points,
            "category": vt.category.name if vt.category else "",
            "category_id": vt.category_id,
        }
    )


@bp.route("/tambah", methods=["GET", "POST"])
@login_required
@role_required("admin", "guru_bk", "wali_kelas")
def tambah():
    form = ViolationRecordForm()
    form.student_id.choices = _student_choices()
    form.violation_type_id.choices = _violation_type_choices()

    if request.method == "GET":
        return hx_render(
            "violations/form.html",
            form=form,
            record=None,
            class_choices=_class_choices(),
        )

    if not form.validate_on_submit():
        return hx_render(
            "violations/form.html",
            form=form,
            record=None,
            class_choices=_class_choices(),
        )

    from .. import db

    ay = current_academic_year()
    if ay is None:
        return hx_render(
            "violations/form.html",
            form=form,
            record=None,
            class_choices=_class_choices(),
            error="Tidak ada tahun ajaran aktif. Hubungi admin.",
        )

    result = record_violation(
        student_id=form.student_id.data,
        violation_type_id=form.violation_type_id.data,
        points=form.points.data,
        chronology=sanitize(form.chronology.data),
        location=sanitize(form.location.data),
        incident_date=form.incident_date.data,
        incident_time=form.incident_time.data,
        academic_year_id=ay.id,
        semester=form.semester.data,
        recorded_by=current_user.id,
        session=db.session,
    )
    db.session.commit()

    notif = {"success": "Pelanggaran dicatat."}
    if result.get("new_warning"):
        notif[
            "info"
        ] = f"SP{result['new_warning'].level} diterbitkan untuk siswa."
    if result.get("student_expelled"):
        notif[
            "error"
        ] = "Siswa dikeluarkan &mdash; surat rekomendasi terbit."

    return hx_render(
        "violations/index.html", push_url="violations.index", **notif
    )


@bp.route("/<int:id>")
@login_required
@role_required("admin", "guru_bk", "wali_kelas")
def detail(id):
    from .. import db

    if current_user.role == "wali_kelas":
        v = (
            db.session.query(ViolationRecord)
            .join(Student)
            .filter(
                ViolationRecord.id == id,
                ViolationRecord.is_void.is_(False),
                Student.class_.homeroom_teacher_id == current_user.id,
            )
            .first_or_404()
        )
    else:
        v = db.get_or_404(ViolationRecord, id)

    summary = StudentPointSummary.query.filter_by(
        student_id=v.student_id
    ).first()
    return hx_render(
        "violations/detail.html", record=v, summary=summary
    )


@bp.route("/<int:id>/void", methods=["POST"])
@login_required
@role_required("admin", "guru_bk")
def void(id):
    from .. import db

    v = db.get_or_404(ViolationRecord, id)
    if v.is_void:
        return hx_render(
            "violations/index.html",
            error="Pelanggaran sudah dibatalkan sebelumnya.",
        )

    v.is_void = True
    recompute_summary(v.student_id, db.session)
    db.session.commit()

    return hx_render(
        "violations/index.html",
        success=f"Pelanggaran {sanitize(v.violation_type.name)} untuk {sanitize(v.student.name)} dibatalkan.",
    )
