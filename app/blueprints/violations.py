from flask import Blueprint
from flask_login import login_required

from ..helper import hx_render, role_required

bp = Blueprint("violations", __name__, url_prefix="/pelanggaran")


@bp.route("/")
@login_required
@role_required("admin", "guru_bk", "wali_kelas")
def index():
    return hx_render(
        "_placeholder.html",
        title="Pelanggaran",
        message="Pencatatan pelanggaran akan diimplementasikan pada T11.",
    )
