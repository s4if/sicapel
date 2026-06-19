from flask import Blueprint
from flask_login import login_required

from ..helper import hx_render, role_required

bp = Blueprint("warnings", __name__, url_prefix="/surat-peringatan")


@bp.route("/")
@login_required
@role_required("admin", "guru_bk")
def index():
    return hx_render(
        "_placeholder.html",
        title="Surat Peringatan",
        message="Daftar surat peringatan akan diimplementasikan pada T12.",
    )
