from flask import Blueprint, jsonify, request
from flask_login import login_required

from ..forms import ClassForm
from ..helper import hx_render, role_required, sanitize
from ..models import Class, User

bp = Blueprint("classes", __name__, url_prefix="/kelas")


def _teacher_choices():
    return [
        (u.id, u.name)
        for u in User.query.filter(User.role == "wali_kelas")
        .order_by(User.name)
        .all()
    ]


def _row_actions(cls):
    edit_url = f"{cls.id}/edit"
    return (
        f'<div class="btn-group btn-group-sm">'
        f'<a class="btn btn-outline-primary" href="{edit_url}" '
        f'hx-get="{edit_url}" hx-target="#hx_content" hx-swap="innerHTML">'
        f'<i class="bi bi-pencil"></i></a>'
        f"</div>"
    )


@bp.route("/")
@login_required
@role_required("admin")
def index():
    return hx_render("classes/index.html")


@bp.route("/data")
@login_required
@role_required("admin")
def data():
    rows = []
    for i, c in enumerate(
        Class.query.order_by(Class.grade_level, Class.name).all(), 1
    ):
        rows.append(
            {
                "no": i,
                "name": sanitize(c.name),
                "grade_level": c.grade_level,
                "homeroom_teacher": sanitize(c.homeroom_teacher.name)
                if c.homeroom_teacher
                else "-",
                "actions": _row_actions(c),
            }
        )
    return jsonify(data=rows)


@bp.route("/tambah", methods=["GET", "POST"])
@login_required
@role_required("admin")
def tambah():
    form = ClassForm()
    form.homeroom_teacher_id.choices = _teacher_choices()

    if request.method == "GET":
        return hx_render("classes/form.html", form=form, cls=None)

    if not form.validate_on_submit():
        return hx_render("classes/form.html", form=form, cls=None)

    from .. import db

    cls = Class(
        name=sanitize(form.name.data),
        grade_level=form.grade_level.data,
        homeroom_teacher_id=form.homeroom_teacher_id.data,
    )
    db.session.add(cls)
    db.session.commit()

    return hx_render(
        "classes/index.html",
        push_url="classes.index",
        success=f"Kelas {cls.name} berhasil ditambahkan.",
    )


@bp.route("/<int:id>/edit", methods=["GET", "POST"])
@login_required
@role_required("admin")
def edit(id):
    from .. import db

    cls = db.get_or_404(Class, id)
    form = ClassForm(obj=cls)
    form.homeroom_teacher_id.choices = _teacher_choices()

    if request.method == "GET":
        return hx_render("classes/form.html", form=form, cls=cls)

    if not form.validate_on_submit():
        return hx_render("classes/form.html", form=form, cls=cls)

    cls.name = sanitize(form.name.data)
    cls.grade_level = form.grade_level.data
    cls.homeroom_teacher_id = form.homeroom_teacher_id.data
    db.session.commit()

    return hx_render(
        "classes/index.html",
        push_url="classes.index",
        success=f"Kelas {cls.name} berhasil diperbarui.",
    )
