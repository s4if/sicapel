from flask import Blueprint
from flask_login import login_required

from ..helper import hx_render, role_required

bp = Blueprint("expulsion", __name__, url_prefix="/ekspulsi")


@bp.route("/")
@login_required
@role_required("admin", "guru_bk")
def index():
    return hx_render(
        "_placeholder.html",
        title="Rekomendasi Ekspulsi",
        message="Daftar rekomendasi ekspulsi akan diimplementasikan pada T13.",
    )
