from flask import Blueprint, jsonify, request
from flask_login import login_required

from ..forms import ClassForm
from ..helper import hx_render, role_required, sanitize
from ..models import Class, Student, User

bp = Blueprint("classes", __name__, url_prefix="/kelas")

_LABEL = "Kelas"


def _display(cls):
    return cls.name


def _teacher_choices():
    return [
        (u.id, u.name)
        for u in User.query.filter(
            User.role == "wali_kelas", User.is_deleted.is_(False)
        )
        .order_by(User.name)
        .all()
    ]


def _related_counts(class_id):
    return {"siswa": Student.query.filter_by(class_id=class_id).count()}


def _row_actions(cls):
    nama = sanitize(_display(cls))
    if getattr(cls, "is_deleted", False):
        restore_url = f"{cls.id}/restore"
        return (
            f'<div class="btn-group btn-group-sm">'
            f'<button class="btn btn-outline-success" type="button" '
            f'onclick="pulihkan_data(this)" '
            f'data-url="{restore_url}" data-nama="{nama}">'
            f'<i class="bi bi-arrow-counterclockwise"></i></button>'
            f"</div>"
        )

    edit_url = f"{cls.id}/edit"
    delete_url = f"{cls.id}/delete"
    return (
        f'<div class="btn-group btn-group-sm">'
        f'<a class="btn btn-outline-primary" href="{edit_url}" '
        f'hx-get="{edit_url}" hx-target="#hx_content" hx-swap="innerHTML">'
        f'<i class="bi bi-pencil"></i></a>'
        f'<button class="btn btn-outline-danger" type="button" '
        f'onclick="hapus_data(this)" '
        f'data-url="{delete_url}" data-nama="{nama}">'
        f'<i class="bi bi-trash"></i></button>'
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
                "is_deleted": c.is_deleted,
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
        name=form.name.data,
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

    cls.name = form.name.data
    cls.grade_level = form.grade_level.data
    cls.homeroom_teacher_id = form.homeroom_teacher_id.data
    db.session.commit()

    return hx_render(
        "classes/index.html",
        push_url="classes.index",
        success=f"Kelas {cls.name} berhasil diperbarui.",
    )


@bp.route("/<int:id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete(id):
    from .. import db

    cls = db.get_or_404(Class, id)

    if cls.is_deleted:
        return hx_render(
            "classes/index.html", error="Data sudah dihapus sebelumnya."
        )

    display = _display(cls)
    related = _related_counts(cls.id)
    related_count = sum(related.values())

    if related_count == 0:
        db.session.delete(cls)
        db.session.commit()
        return hx_render(
            "classes/index.html",
            push_url="classes.index",
            success=f"{_LABEL} {display} berhasil dihapus secara permanen.",
        )

    cls.is_deleted = True
    db.session.commit()
    detail = ", ".join(f"{k}: {v}" for k, v in related.items() if v > 0)
    return hx_render(
        "classes/index.html",
        push_url="classes.index",
        success=f"{_LABEL} {display} ditandai sebagai dihapus ({detail}).",
    )


@bp.route("/<int:id>/restore", methods=["POST"])
@login_required
@role_required("admin")
def restore(id):
    from .. import db

    cls = db.get_or_404(Class, id)
    if not cls.is_deleted:
        return hx_render("classes/index.html", error="Data belum dihapus.")

    cls.is_deleted = False
    db.session.commit()
    return hx_render(
        "classes/index.html",
        push_url="classes.index",
        success=f"{_LABEL} {_display(cls)} berhasil dipulihkan.",
    )
