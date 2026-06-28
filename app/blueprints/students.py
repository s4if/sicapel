from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from ..forms import StudentForm
from ..helper import hx_render, role_required, sanitize, scope_students_to_role
from ..models import Class, Student, StudentPointSummary

bp = Blueprint("students", __name__, url_prefix="/siswa")

_LABEL = "Siswa"


def _display(student):
    return student.name


def _class_choices():
    return [
        (c.id, f"{c.name} (Kelas {c.grade_level})")
        for c in Class.query.filter(Class.is_deleted.is_(False))
        .order_by(Class.grade_level, Class.name)
        .all()
    ]


def _base_query():
    return scope_students_to_role(Student.query)


def _related_counts(student_id):
    from ..models import (
        ExpulsionRecommendation,
        PointAmnesty,
        StudentPointSummary,
        ViolationRecord,
        WarningLetter,
    )

    return {
        "pelanggaran": ViolationRecord.query.filter_by(
            student_id=student_id
        ).count(),
        "surat peringatan": WarningLetter.query.filter_by(
            student_id=student_id
        ).count(),
        "rekomendasi ekspulsi": ExpulsionRecommendation.query.filter_by(
            student_id=student_id
        ).count(),
        "pemutihan": PointAmnesty.query.filter_by(student_id=student_id).count(),
        "ringkasan poin": StudentPointSummary.query.filter_by(
            student_id=student_id
        ).count(),
    }


def _row_actions(student):
    nama = sanitize(_display(student))
    if getattr(student, "is_deleted", False):
        restore_url = f"{student.id}/restore"
        return (
            f'<div class="btn-group btn-group-sm">'
            f'<button class="btn btn-outline-success" type="button" '
            f'onclick="pulihkan_data(this)" '
            f'data-url="{restore_url}" data-nama="{nama}">'
            f'<i class="bi bi-arrow-counterclockwise"></i></button>'
            f"</div>"
        )

    edit_url = f"{student.id}/edit"
    detail_url = f"{student.id}"
    delete_url = f"{student.id}/delete"
    can_manage = current_user.role in ("admin", "guru_bk")
    buttons = (
        f'<div class="btn-group btn-group-sm">'
        f'<a class="btn btn-outline-info" href="{detail_url}" '
        f'hx-get="{detail_url}" hx-target="#hx_content" hx-swap="innerHTML">'
        f'<i class="bi bi-eye"></i></a>'
    )
    if can_manage:
        buttons += (
            f'<a class="btn btn-outline-primary" href="{edit_url}" '
            f'hx-get="{edit_url}" hx-target="#hx_content" hx-swap="innerHTML">'
            f'<i class="bi bi-pencil"></i></a>'
            f'<button class="btn btn-outline-danger" type="button" '
            f'onclick="hapus_data(this)" '
            f'data-url="{delete_url}" data-nama="{nama}">'
            f'<i class="bi bi-trash"></i></button>'
        )
    buttons += "</div>"
    return buttons


@bp.route("/")
@login_required
@role_required("admin", "guru_bk", "wali_kelas")
def index():
    return hx_render("students/index.html")


@bp.route("/data")
@login_required
@role_required("admin", "guru_bk", "wali_kelas")
def data():
    q = _base_query()
    # Hide soft-deleted entities for non-admins: only admins see the trash
    # bin (so they can restore). guru_bk / wali_kelas never see deleted rows.
    if current_user.role != "admin":
        q = q.filter(Student.is_deleted.is_(False))
    rows = []
    for i, s in enumerate(q.order_by(Student.created_at.desc()).all(), 1):
        summary = StudentPointSummary.query.filter_by(student_id=s.id).first()
        rows.append(
            {
                "no": i,
                "nis": sanitize(s.nis),
                "name": sanitize(s.name),
                "gender": "L" if s.gender == "L" else "P",
                "class": sanitize(s.class_.name) if s.class_ else "-",
                "status": s.status.capitalize(),
                "points": summary.total_points if summary else 0,
                "is_deleted": s.is_deleted,
                "actions": _row_actions(s),
            }
        )
    return jsonify(data=rows)


@bp.route("/tambah", methods=["GET", "POST"])
@login_required
@role_required("admin", "guru_bk")
def tambah():
    form = StudentForm()
    form.class_id.choices = _class_choices()

    if request.method == "GET":
        return hx_render("students/form.html", form=form, student=None)

    if not form.validate_on_submit():
        return hx_render("students/form.html", form=form, student=None)

    from .. import db

    student = Student(
        nis=form.nis.data,
        nisn=form.nisn.data or None,
        name=form.name.data,
        gender=form.gender.data,
        birth_place=form.birth_place.data or None,
        birth_date=form.birth_date.data,
        address=form.address.data or None,
        class_id=form.class_id.data,
        parent_name=form.parent_name.data or None,
        parent_phone=form.parent_phone.data or None,
        status=form.status.data,
        enrolled_at=form.enrolled_at.data,
    )
    db.session.add(student)
    db.session.commit()

    return hx_render(
        "students/index.html",
        push_url="students.index",
        success=f"Siswa {student.name} berhasil ditambahkan.",
    )


@bp.route("/<int:id>")
@login_required
@role_required("admin", "guru_bk", "wali_kelas")
def detail(id):
    from .. import db

    if current_user.role == "wali_kelas":
        student = (
            db.session.query(Student)
            .join(Class, Student.class_id == Class.id)
            .filter(
                Student.id == id,
                Class.homeroom_teacher_id == current_user.id,
            )
            .first_or_404()
        )
    else:
        student = db.get_or_404(Student, id)

    # Hide soft-deleted entities for non-admins: a deleted student is invisible
    # (404) to guru_bk / wali_kelas. Only admins may view retired records.
    if student.is_deleted and current_user.role != "admin":
        return hx_render("errors/404.html"), 404

    summary = StudentPointSummary.query.filter_by(student_id=id).first()
    return hx_render("students/detail.html", student=student, summary=summary)


@bp.route("/<int:id>/edit", methods=["GET", "POST"])
@login_required
@role_required("admin", "guru_bk")
def edit(id):
    from .. import db

    student = db.get_or_404(Student, id)
    form = StudentForm(obj=student)
    form.class_id.choices = _class_choices()

    if request.method == "GET":
        return hx_render("students/form.html", form=form, student=student)

    if not form.validate_on_submit():
        return hx_render("students/form.html", form=form, student=student)

    student.nis = form.nis.data
    student.nisn = form.nisn.data or None
    student.name = form.name.data
    student.gender = form.gender.data
    student.birth_place = form.birth_place.data or None
    student.birth_date = form.birth_date.data
    student.address = form.address.data or None
    student.class_id = form.class_id.data
    student.parent_name = form.parent_name.data or None
    student.parent_phone = form.parent_phone.data or None
    student.status = form.status.data
    student.enrolled_at = form.enrolled_at.data
    db.session.commit()

    return hx_render(
        "students/index.html",
        push_url="students.index",
        success=f"Siswa {student.name} berhasil diperbarui.",
    )


@bp.route("/<int:id>/delete", methods=["POST"])
@login_required
@role_required("admin", "guru_bk")
def delete(id):
    from .. import db

    student = db.get_or_404(Student, id)

    if student.is_deleted:
        return hx_render(
            "students/index.html", error="Data sudah dihapus sebelumnya."
        )

    display = _display(student)
    related = _related_counts(student.id)
    related_count = sum(related.values())

    if related_count == 0:
        db.session.delete(student)
        db.session.commit()
        return hx_render(
            "students/index.html",
            push_url="students.index",
            success=f"{_LABEL} {display} berhasil dihapus secara permanen.",
        )

    student.is_deleted = True
    db.session.commit()
    detail = ", ".join(f"{k}: {v}" for k, v in related.items() if v > 0)
    return hx_render(
        "students/index.html",
        push_url="students.index",
        success=f"{_LABEL} {display} ditandai sebagai dihapus ({detail}).",
    )


@bp.route("/<int:id>/restore", methods=["POST"])
@login_required
@role_required("admin")
def restore(id):
    from .. import db

    student = db.get_or_404(Student, id)
    if not student.is_deleted:
        return hx_render("students/index.html", error="Data belum dihapus.")

    student.is_deleted = False
    db.session.commit()
    return hx_render(
        "students/index.html",
        push_url="students.index",
        success=f"{_LABEL} {_display(student)} berhasil dipulihkan.",
    )


@bp.route("/by-class/<int:class_id>")
@login_required
@role_required("admin", "guru_bk", "wali_kelas")
def by_class(class_id):
    from .. import db

    # Ownership guard (inline, matching students.detail): a wali_kelas may
    # only cascade-fetch the students of their own class.
    cls = db.get_or_404(Class, class_id)
    if current_user.role == "wali_kelas" and cls.homeroom_teacher_id != current_user.id:
        return hx_render("errors/403.html"), 403
    students = (
        Student.query.filter_by(class_id=class_id, status="active")
        .filter(Student.is_deleted.is_(False))
        .order_by(Student.name)
        .all()
    )
    return hx_render("students/_by_class.html", students=students)
