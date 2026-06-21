from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from ..forms import StudentForm
from ..helper import hx_render, role_required, sanitize
from ..models import Class, Student, StudentPointSummary

bp = Blueprint("students", __name__, url_prefix="/siswa")


def _class_choices():
    return [
        (c.id, f"{c.name} (Kelas {c.grade_level})")
        for c in Class.query.order_by(Class.grade_level, Class.name).all()
    ]


def _base_query():
    q = Student.query
    if current_user.role == "wali_kelas":
        q = q.filter(Student.class_.homeroom_teacher_id == current_user.id)
    return q


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
    for i, s in enumerate(
        q.order_by(Student.created_at.desc()).all(), 1
    ):
        summary = StudentPointSummary.query.filter_by(
            student_id=s.id
        ).first()
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
        nis=sanitize(form.nis.data),
        nisn=sanitize(form.nisn.data) if form.nisn.data else None,
        name=sanitize(form.name.data),
        gender=form.gender.data,
        birth_place=sanitize(form.birth_place.data) if form.birth_place.data else None,
        birth_date=form.birth_date.data,
        address=sanitize(form.address.data) if form.address.data else None,
        class_id=form.class_id.data,
        parent_name=sanitize(form.parent_name.data)
        if form.parent_name.data
        else None,
        parent_phone=sanitize(form.parent_phone.data)
        if form.parent_phone.data
        else None,
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
            .filter(
                Student.id == id,
                Student.class_.homeroom_teacher_id == current_user.id,
            )
            .first_or_404()
        )
    else:
        student = db.get_or_404(Student, id)

    summary = StudentPointSummary.query.filter_by(student_id=id).first()
    return hx_render(
        "students/detail.html", student=student, summary=summary
    )


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

    student.nis = sanitize(form.nis.data)
    student.nisn = sanitize(form.nisn.data) if form.nisn.data else None
    student.name = sanitize(form.name.data)
    student.gender = form.gender.data
    student.birth_place = (
        sanitize(form.birth_place.data) if form.birth_place.data else None
    )
    student.birth_date = form.birth_date.data
    student.address = sanitize(form.address.data) if form.address.data else None
    student.class_id = form.class_id.data
    student.parent_name = (
        sanitize(form.parent_name.data) if form.parent_name.data else None
    )
    student.parent_phone = (
        sanitize(form.parent_phone.data) if form.parent_phone.data else None
    )
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
    students = (
        Student.query.filter_by(class_id=class_id, status="active")
        .order_by(Student.name)
        .all()
    )
    return render_template("students/_by_class.html", students=students)
