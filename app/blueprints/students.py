from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from ..forms import StudentForm
from ..helper import hx_render, role_required, sanitize, scope_students_to_role
from ..models import Class, Student, StudentPointSummary

bp = Blueprint("students", __name__, url_prefix="/siswa")


def _class_choices():
    return [
        (c.id, f"{c.name} (Kelas {c.grade_level})")
        for c in Class.query.order_by(Class.grade_level, Class.name).all()
    ]


def _base_query():
    return scope_students_to_role(Student.query)


def _row_actions(student):
    edit_url = f"{student.id}/edit"
    detail_url = f"{student.id}"
    return (
        f'<div class="btn-group btn-group-sm">'
        f'<a class="btn btn-outline-info" href="{detail_url}" '
        f'hx-get="{detail_url}" hx-target="#hx_content" hx-swap="innerHTML">'
        f'<i class="bi bi-eye"></i></a>'
        f'<a class="btn btn-outline-primary" href="{edit_url}" '
        f'hx-get="{edit_url}" hx-target="#hx_content" hx-swap="innerHTML">'
        f'<i class="bi bi-pencil"></i></a>'
        f"</div>"
    )


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
        .order_by(Student.name)
        .all()
    )
    return hx_render("students/_by_class.html", students=students)
