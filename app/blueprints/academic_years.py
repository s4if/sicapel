from flask import Blueprint, jsonify, request
from flask_login import login_required

from ..forms import AcademicYearForm
from ..helper import hx_render, role_required, sanitize
from ..models import AcademicYear

bp = Blueprint("academic_years", __name__, url_prefix="/tahun-ajaran")

_LABEL = "Tahun ajaran"


def _display(ay):
    return ay.year


def _related_counts(academic_year_id):
    from ..models import (
        ExpulsionRecommendation,
        PointAmnesty,
        ViolationRecord,
        WarningLetter,
    )

    return {
        "pelanggaran": ViolationRecord.query.filter_by(
            academic_year_id=academic_year_id
        ).count(),
        "surat peringatan": WarningLetter.query.filter_by(
            academic_year_id=academic_year_id
        ).count(),
        "rekomendasi ekspulsi": ExpulsionRecommendation.query.filter_by(
            academic_year_id=academic_year_id
        ).count(),
        "pemutihan": PointAmnesty.query.filter_by(
            academic_year_id=academic_year_id
        ).count(),
    }


def _row_actions(ay):
    nama = sanitize(_display(ay))
    if getattr(ay, "is_deleted", False):
        restore_url = f"{ay.id}/restore"
        return (
            f'<div class="btn-group btn-group-sm">'
            f'<button class="btn btn-outline-success" type="button" '
            f'onclick="pulihkan_data(this)" '
            f'data-url="{restore_url}" data-nama="{nama}">'
            f'<i class="bi bi-arrow-counterclockwise"></i></button>'
            f"</div>"
        )

    edit_url = f"{ay.id}/edit"
    delete_url = f"{ay.id}/delete"
    return (
        f'<div class="btn-group btn-group-sm">'
        f'<a class="btn btn-outline-primary" href="{edit_url}" '
        f'hx-get="{edit_url}" hx-target="#hx_content" hx-swap="innerHTML">'
        f'<i class="bi bi-pencil"></i></a>'
        f'<button class="btn btn-outline-danger" type="button" '
        f'onclick="hapus_data(this)" '
        f'data-url="{delete_url}" data-nama="{nama}">'
        f'<i class="bi bi-trash"></i></button>'
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
                "is_deleted": ay.is_deleted,
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


@bp.route("/<int:id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete(id):
    from .. import db

    ay = db.get_or_404(AcademicYear, id)

    # I3: the currently-active academic year cannot be deleted.
    if ay.is_active:
        return hx_render(
            "academic_years/index.html",
            error="Tahun ajaran aktif tidak dapat dihapus.",
        )

    if ay.is_deleted:
        return hx_render(
            "academic_years/index.html", error="Data sudah dihapus sebelumnya."
        )

    display = _display(ay)
    related = _related_counts(ay.id)
    related_count = sum(related.values())

    if related_count == 0:
        db.session.delete(ay)
        db.session.commit()
        return hx_render(
            "academic_years/index.html",
            push_url="academic_years.index",
            success=f"{_LABEL} {display} berhasil dihapus secara permanen.",
        )

    ay.is_deleted = True
    db.session.commit()
    detail = ", ".join(f"{k}: {v}" for k, v in related.items() if v > 0)
    return hx_render(
        "academic_years/index.html",
        push_url="academic_years.index",
        success=f"{_LABEL} {display} ditandai sebagai dihapus ({detail}).",
    )


@bp.route("/<int:id>/restore", methods=["POST"])
@login_required
@role_required("admin")
def restore(id):
    from .. import db

    ay = db.get_or_404(AcademicYear, id)
    if not ay.is_deleted:
        return hx_render("academic_years/index.html", error="Data belum dihapus.")

    # I1: is_deleted is independent of is_active; restoring does NOT flip
    # is_active, so it can never create a second active year.
    ay.is_deleted = False
    db.session.commit()
    return hx_render(
        "academic_years/index.html",
        push_url="academic_years.index",
        success=f"{_LABEL} {_display(ay)} berhasil dipulihkan.",
    )
