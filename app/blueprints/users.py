from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from ..forms import UserEditForm, UserForm
from ..helper import hx_render, hash_password, role_required, sanitize
from ..models import User

bp = Blueprint("users", __name__, url_prefix="/pengguna")

_LABEL = "Pengguna"


def _display(user):
    return user.name


def _related_counts(user_id):
    from ..models import (
        Class,
        Document,
        ExpulsionRecommendation,
        PointAmnesty,
        ViolationRecord,
        ViolationType,
        WarningLetter,
    )

    return {
        "kelas wali": Class.query.filter_by(homeroom_teacher_id=user_id).count(),
        "pelanggaran": ViolationRecord.query.filter_by(recorded_by=user_id).count(),
        "jenis pelanggaran": ViolationType.query.filter_by(created_by=user_id).count(),
        "surat peringatan": WarningLetter.query.filter_by(issued_by=user_id).count(),
        "rekomendasi ekspulsi": ExpulsionRecommendation.query.filter_by(
            issued_by=user_id
        ).count(),
        "pemutihan": PointAmnesty.query.filter_by(recorded_by=user_id).count(),
        "dokumen": Document.query.filter_by(uploaded_by=user_id).count(),
    }


def _row_actions(user):
    nama = sanitize(_display(user))
    if getattr(user, "is_deleted", False):
        restore_url = f"{user.id}/restore"
        return (
            f'<div class="btn-group btn-group-sm">'
            f'<button class="btn btn-outline-success" type="button" '
            f'onclick="pulihkan_data(this)" '
            f'data-url="{restore_url}" data-nama="{nama}">'
            f'<i class="bi bi-arrow-counterclockwise"></i></button>'
            f"</div>"
        )

    edit_url = f"{user.id}/edit"
    delete_url = f"{user.id}/delete"
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
    return hx_render("users/index.html")


@bp.route("/data")
@login_required
@role_required("admin")
def data():
    rows = []
    for i, u in enumerate(
        User.query.order_by(User.created_at.desc()).all(), 1
    ):
        rows.append(
            {
                "no": i,
                "name": sanitize(u.name),
                "email": sanitize(u.email),
                "role": u.role.replace("_", " ").title(),
                "nip": sanitize(u.nip) if u.nip else "-",
                "phone": sanitize(u.phone) if u.phone else "-",
                "is_deleted": u.is_deleted,
                "actions": _row_actions(u),
            }
        )
    return jsonify(data=rows)


@bp.route("/tambah", methods=["GET", "POST"])
@login_required
@role_required("admin")
def tambah():
    form = UserForm()

    if request.method == "GET":
        return hx_render("users/form.html", form=form, user=None)

    if not form.validate_on_submit():
        return hx_render("users/form.html", form=form, user=None)

    from .. import db

    user = User(
        name=form.name.data,
        email=form.email.data,
        password_hash=hash_password(form.password.data),
        role=form.role.data,
        nip=form.nip.data or None,
        phone=form.phone.data or None,
    )
    db.session.add(user)
    db.session.commit()

    return hx_render(
        "users/index.html",
        push_url="users.index",
        success=f"Pengguna {user.name} berhasil ditambahkan.",
    )


@bp.route("/<int:id>/edit", methods=["GET", "POST"])
@login_required
@role_required("admin")
def edit(id):
    from .. import db

    user = db.get_or_404(User, id)
    form = UserEditForm(obj=user)

    if request.method == "GET":
        return hx_render("users/form.html", form=form, user=user)

    if not form.validate_on_submit():
        return hx_render("users/form.html", form=form, user=user)

    user.name = form.name.data
    user.email = form.email.data
    user.role = form.role.data
    user.nip = form.nip.data or None
    user.phone = form.phone.data or None
    db.session.commit()

    return hx_render(
        "users/index.html",
        push_url="users.index",
        success=f"Pengguna {user.name} berhasil diperbarui.",
    )


@bp.route("/<int:id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete(id):
    from .. import db

    user = db.get_or_404(User, id)

    # I4: cannot delete the last remaining admin. Checked before the self
    # guard because the last admin is necessarily the current admin (only
    # admins can delete), so this is the only reachable path to it.
    if user.role == "admin":
        other_admins = User.query.filter(
            User.role == "admin",
            User.is_deleted.is_(False),
            User.id != user.id,
        ).count()
        if other_admins == 0:
            return hx_render(
                "users/index.html",
                error="Tidak dapat menghapus admin terakhir.",
            )

    # I4: an admin cannot delete their own account.
    if user.id == current_user.id:
        return hx_render(
            "users/index.html", error="Anda tidak dapat menghapus akun sendiri."
        )

    if user.is_deleted:
        return hx_render(
            "users/index.html", error="Data sudah dihapus sebelumnya."
        )

    display = _display(user)
    related = _related_counts(user.id)
    related_count = sum(related.values())

    if related_count == 0:
        db.session.delete(user)
        db.session.commit()
        return hx_render(
            "users/index.html",
            push_url="users.index",
            success=f"{_LABEL} {display} berhasil dihapus secara permanen.",
        )

    user.is_deleted = True
    db.session.commit()
    detail = ", ".join(f"{k}: {v}" for k, v in related.items() if v > 0)
    return hx_render(
        "users/index.html",
        push_url="users.index",
        success=f"{_LABEL} {display} ditandai sebagai dihapus ({detail}).",
    )


@bp.route("/<int:id>/restore", methods=["POST"])
@login_required
@role_required("admin")
def restore(id):
    from .. import db

    user = db.get_or_404(User, id)
    if not user.is_deleted:
        return hx_render("users/index.html", error="Data belum dihapus.")

    user.is_deleted = False
    db.session.commit()
    return hx_render(
        "users/index.html",
        push_url="users.index",
        success=f"{_LABEL} {_display(user)} berhasil dipulihkan.",
    )
