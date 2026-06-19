from flask import Blueprint
from flask_login import login_required

from ..helper import hx_render, role_required

bp = Blueprint("classes", __name__, url_prefix="/kelas")


@bp.route("/")
@login_required
@role_required("admin")
def index():
    return hx_render(
        "_placeholder.html",
        title="Kelas",
        message="Manajemen kelas akan diimplementasikan pada T10.",
    )
