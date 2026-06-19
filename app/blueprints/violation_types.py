from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from ..forms import ViolationTypeForm
from ..helper import hx_render, role_required, sanitize
from ..models import ViolationCategory, ViolationType

bp = Blueprint("violation_types", __name__, url_prefix="/jenis-pelanggaran")


def _category_choices():
    return [
        (c.id, f"{c.name.capitalize()} ({c.min_points}-{c.max_points} poin)")
        for c in ViolationCategory.query.order_by(ViolationCategory.id).all()
    ]


def _row_actions(vt):
    edit_url = f"{vt.id}/edit"
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
    return hx_render("violation_types/index.html")


@bp.route("/data")
@login_required
@role_required("admin")
def data():
    rows = []
    for i, vt in enumerate(
        ViolationType.query.order_by(ViolationType.created_at.desc()).all(), 1
    ):
        rows.append(
            {
                "no": i,
                "name": sanitize(vt.name),
                "category": vt.category.name.capitalize() if vt.category else "-",
                "default_points": vt.default_points,
                "is_active": "Aktif" if vt.is_active else "Nonaktif",
                "actions": _row_actions(vt),
            }
        )
    return jsonify(data=rows)


@bp.route("/tambah", methods=["GET", "POST"])
@login_required
@role_required("admin")
def tambah():
    form = ViolationTypeForm()
    form.category_id.choices = _category_choices()

    if request.method == "GET":
        return hx_render("violation_types/form.html", form=form, violation_type=None)

    if not form.validate_on_submit():
        return hx_render(
            "violation_types/form.html", form=form, violation_type=None
        )

    from .. import db

    vt = ViolationType(
        category_id=form.category_id.data,
        name=sanitize(form.name.data),
        default_points=form.default_points.data,
        description=sanitize(form.description.data) if form.description.data else None,
        is_active=form.is_active.data,
        created_by=current_user.id,
    )
    db.session.add(vt)
    db.session.commit()

    return hx_render(
        "violation_types/index.html",
        push_url="violation_types.index",
        success=f"Jenis pelanggaran {vt.name} berhasil ditambahkan.",
    )


@bp.route("/<int:id>/edit", methods=["GET", "POST"])
@login_required
@role_required("admin")
def edit(id):
    from .. import db

    vt = db.get_or_404(ViolationType, id)
    form = ViolationTypeForm(obj=vt)
    form.category_id.choices = _category_choices()

    if request.method == "GET":
        return hx_render("violation_types/form.html", form=form, violation_type=vt)

    if not form.validate_on_submit():
        return hx_render(
            "violation_types/form.html", form=form, violation_type=vt
        )

    vt.category_id = form.category_id.data
    vt.name = sanitize(form.name.data)
    vt.default_points = form.default_points.data
    vt.description = (
        sanitize(form.description.data) if form.description.data else None
    )
    vt.is_active = form.is_active.data
    db.session.commit()

    return hx_render(
        "violation_types/index.html",
        push_url="violation_types.index",
        success=f"Jenis pelanggaran {vt.name} berhasil diperbarui.",
    )
