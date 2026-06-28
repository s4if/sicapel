from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from ..forms import ViolationTypeForm
from ..helper import hx_render, role_required, sanitize
from ..models import ViolationCategory, ViolationRecord, ViolationType

bp = Blueprint("violation_types", __name__, url_prefix="/jenis-pelanggaran")

_LABEL = "Jenis pelanggaran"


def _display(vt):
    return vt.name


def _related_counts(violation_type_id):
    return {
        "pelanggaran": ViolationRecord.query.filter_by(
            violation_type_id=violation_type_id
        ).count()
    }


def _row_actions(vt):
    nama = sanitize(_display(vt))
    if getattr(vt, "is_deleted", False):
        restore_url = f"{vt.id}/restore"
        return (
            f'<div class="btn-group btn-group-sm">'
            f'<button class="btn btn-outline-success" type="button" '
            f'onclick="pulihkan_data(this)" '
            f'data-url="{restore_url}" data-nama="{nama}">'
            f'<i class="bi bi-arrow-counterclockwise"></i></button>'
            f"</div>"
        )

    edit_url = f"{vt.id}/edit"
    delete_url = f"{vt.id}/delete"
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


def _category_choices():
    return [
        (c.id, f"{c.name.capitalize()} ({c.min_points}-{c.max_points} poin)")
        for c in ViolationCategory.query.order_by(ViolationCategory.id).all()
    ]


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
                "is_deleted": vt.is_deleted,
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
        name=form.name.data,
        default_points=form.default_points.data,
        description=form.description.data if form.description.data else None,
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
    vt.name = form.name.data
    vt.default_points = form.default_points.data
    vt.description = form.description.data if form.description.data else None
    vt.is_active = form.is_active.data
    db.session.commit()

    return hx_render(
        "violation_types/index.html",
        push_url="violation_types.index",
        success=f"Jenis pelanggaran {vt.name} berhasil diperbarui.",
    )


@bp.route("/<int:id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete(id):
    from .. import db

    vt = db.get_or_404(ViolationType, id)

    if vt.is_deleted:
        return hx_render(
            "violation_types/index.html", error="Data sudah dihapus sebelumnya."
        )

    display = _display(vt)
    related = _related_counts(vt.id)
    related_count = sum(related.values())

    if related_count == 0:
        db.session.delete(vt)
        db.session.commit()
        return hx_render(
            "violation_types/index.html",
            push_url="violation_types.index",
            success=f"{_LABEL} {display} berhasil dihapus secara permanen.",
        )

    vt.is_deleted = True
    db.session.commit()
    detail = ", ".join(f"{k}: {v}" for k, v in related.items() if v > 0)
    return hx_render(
        "violation_types/index.html",
        push_url="violation_types.index",
        success=f"{_LABEL} {display} ditandai sebagai dihapus ({detail}).",
    )


@bp.route("/<int:id>/restore", methods=["POST"])
@login_required
@role_required("admin")
def restore(id):
    from .. import db

    vt = db.get_or_404(ViolationType, id)
    if not vt.is_deleted:
        return hx_render("violation_types/index.html", error="Data belum dihapus.")

    # I1: is_deleted is independent of is_active; restoring never flips a
    # deliberately-deactivated type back to active.
    vt.is_deleted = False
    db.session.commit()
    return hx_render(
        "violation_types/index.html",
        push_url="violation_types.index",
        success=f"{_LABEL} {_display(vt)} berhasil dipulihkan.",
    )
