from flask import Blueprint
from flask_login import login_required

from ..helper import hx_render, role_required

bp = Blueprint("users", __name__, url_prefix="/pengguna")


@bp.route("/")
@login_required
@role_required("admin")
def index():
    return hx_render(
        "_placeholder.html",
        title="Pengguna",
        message="Manajemen pengguna akan diimplementasikan pada T10.",
    )
