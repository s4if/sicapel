from flask import Blueprint
from flask_login import login_required

from ..helper import hx_render, role_required

bp = Blueprint("violation_types", __name__, url_prefix="/jenis-pelanggaran")


@bp.route("/")
@login_required
@role_required("admin")
def index():
    return hx_render(
        "_placeholder.html",
        title="Jenis Pelanggaran",
        message="Manajemen jenis pelanggaran akan diimplementasikan pada T10.",
    )
