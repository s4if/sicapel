from flask import Blueprint
from flask_login import login_required

from ..helper import hx_render, role_required

bp = Blueprint("academic_years", __name__, url_prefix="/tahun-ajaran")


@bp.route("/")
@login_required
@role_required("admin")
def index():
    return hx_render(
        "_placeholder.html",
        title="Tahun Ajaran",
        message="Manajemen tahun ajaran akan diimplementasikan pada T10.",
    )
