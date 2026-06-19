from flask import Blueprint
from flask_login import login_required

from ..helper import hx_render

bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@bp.route("/")
@login_required
def index():
    return hx_render("dashboard/index.html")
