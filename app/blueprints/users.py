from flask import Blueprint, jsonify, request
from flask_login import login_required

from ..forms import UserEditForm, UserForm
from ..helper import hx_render, hash_password, role_required, sanitize
from ..models import User

bp = Blueprint("users", __name__, url_prefix="/pengguna")


def _row_actions(user):
    edit_url = f"{user.id}/edit"
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
