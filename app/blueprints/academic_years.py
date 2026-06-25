from flask import Blueprint, jsonify, request
from flask_login import login_required

from ..forms import AcademicYearForm
from ..helper import hx_render, role_required, sanitize
from ..models import AcademicYear

bp = Blueprint("academic_years", __name__, url_prefix="/tahun-ajaran")


def _row_actions(ay):
    edit_url = f"{ay.id}/edit"
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
    return hx_render("academic_years/index.html")


@bp.route("/data")
@login_required
@role_required("admin")
def data():
    rows = []
    for i, ay in enumerate(
        AcademicYear.query.order_by(AcademicYear.start_date.desc()).all(), 1
    ):
        rows.append(
            {
                "no": i,
                "year": sanitize(ay.year),
                "start_date": ay.start_date.isoformat() if ay.start_date else "-",
                "end_date": ay.end_date.isoformat() if ay.end_date else "-",
                "is_active": "Aktif" if ay.is_active else "Tidak",
                "actions": _row_actions(ay),
            }
        )
    return jsonify(data=rows)


@bp.route("/tambah", methods=["GET", "POST"])
@login_required
@role_required("admin")
def tambah():
    form = AcademicYearForm()

    if request.method == "GET":
        return hx_render("academic_years/form.html", form=form, academic_year=None)

    if not form.validate_on_submit():
        return hx_render(
            "academic_years/form.html", form=form, academic_year=None
        )

    from .. import db

    if form.is_active.data:
        AcademicYear.query.filter(AcademicYear.is_active.is_(True)).update(
            {"is_active": False}, synchronize_session=False
        )

    ay = AcademicYear(
        year=form.year.data,
        start_date=form.start_date.data,
        end_date=form.end_date.data,
        is_active=form.is_active.data,
    )
    db.session.add(ay)
    db.session.commit()

    return hx_render(
        "academic_years/index.html",
        push_url="academic_years.index",
        success=f"Tahun ajaran {ay.year} berhasil ditambahkan.",
    )


@bp.route("/<int:id>/edit", methods=["GET", "POST"])
@login_required
@role_required("admin")
def edit(id):
    from .. import db

    ay = db.get_or_404(AcademicYear, id)
    form = AcademicYearForm(obj=ay)

    if request.method == "GET":
        return hx_render("academic_years/form.html", form=form, academic_year=ay)

    if not form.validate_on_submit():
        return hx_render(
            "academic_years/form.html", form=form, academic_year=ay
        )

    if form.is_active.data and not ay.is_active:
        AcademicYear.query.filter(AcademicYear.is_active.is_(True)).update(
            {"is_active": False}, synchronize_session=False
        )

    ay.year = form.year.data
    ay.start_date = form.start_date.data
    ay.end_date = form.end_date.data
    ay.is_active = form.is_active.data
    db.session.commit()

    return hx_render(
        "academic_years/index.html",
        push_url="academic_years.index",
        success=f"Tahun ajaran {ay.year} berhasil diperbarui.",
    )
