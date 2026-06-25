"""T13 — Expulsion recommendations: list + detail + PDF.

Expulsion recommendations are auto-issued by ``services.record_violation``
on the two triggers of §1.5 (sangat_berat, or menengah/berat after SP3) —
this blueprint is read-only: there is no manual "create" route. Void
operations are deferred to T18; the ``data`` endpoint already excludes
``status == "void"`` rows so voided recommendations stay hidden.

Access is admin + guru_bk only (wali_kelas never sees this section),
mirroring the warnings blueprint.
"""

import io

from flask import Blueprint, jsonify, send_file, url_for
from flask_login import login_required

from .. import db
from ..helper import hx_render, role_required, sanitize
from ..models import ExpulsionRecommendation
from ..services import render_expulsion_pdf

bp = Blueprint("expulsion", __name__, url_prefix="/ekspulsi")


def _status_badge(status):
    cls = {"issued": "bg-danger", "void": "bg-secondary"}.get(status, "bg-secondary")
    label = {"issued": "Diterbitkan", "void": "Batal"}.get(status, status)
    return f'<span class="badge {cls}">{label}</span>'


def _row_actions(e):
    detail_url = f"{e.id}"
    pdf_url = f"{e.id}/pdf"
    return (
        f'<div class="btn-group btn-group-sm">'
        f'<a class="btn btn-outline-info" href="{detail_url}" '
        f'hx-get="{detail_url}" hx-target="#hx_content" hx-swap="innerHTML">'
        f'<i class="bi bi-eye"></i></a>'
        f'<a class="btn btn-outline-danger" href="{pdf_url}" target="_blank" '
        f'hx-boost="false" title="Cetak PDF"><i class="bi bi-file-pdf"></i></a>'
        f'<button class="btn btn-outline-warning" type="button" '
        f'data-nomor="{sanitize(e.letter_number)}" '
        f'data-url="{url_for("expulsion.void", id=e.id)}" '
        f'onclick="void_expulsion(this)" title="Batalkan"><i class="bi bi-x-circle"></i></button>'
        f"</div>"
    )


@bp.route("/")
@login_required
@role_required("admin", "guru_bk")
def index():
    return hx_render("expulsion/index.html")


@bp.route("/data")
@login_required
@role_required("admin", "guru_bk")
def data():
    q = ExpulsionRecommendation.query.filter(
        ExpulsionRecommendation.status != "void"
    )
    rows = []
    for i, e in enumerate(
        q.order_by(
            ExpulsionRecommendation.issue_date.desc(),
            ExpulsionRecommendation.letter_seq.desc(),
        ).all(),
        1,
    ):
        rows.append(
            {
                "no": i,
                "letter_number": sanitize(e.letter_number),
                "student": sanitize(e.student.name),
                "class": sanitize(e.student.class_.name)
                if e.student.class_
                else "-",
                "points": e.total_points_at_issue,
                "issue_date": e.issue_date.isoformat(),
                "status": _status_badge(e.status),
                "actions": _row_actions(e),
            }
        )
    return jsonify(data=rows)


@bp.route("/<int:id>")
@login_required
@role_required("admin", "guru_bk")
def detail(id):
    e = db.get_or_404(ExpulsionRecommendation, id)
    return hx_render("expulsion/detail.html", expulsion=e)


@bp.route("/<int:id>/pdf")
@login_required
@role_required("admin", "guru_bk")
def pdf(id):
    """PDF bytes via send_file — exempt from R1 (binary, not HTML, §6.2)."""
    e = db.get_or_404(ExpulsionRecommendation, id)
    pdf_bytes = render_expulsion_pdf(e)
    buf = io.BytesIO(pdf_bytes)
    buf.seek(0)
    download = f"{e.letter_number.replace('/', '-')}.pdf"
    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=download,
    )


@bp.route("/<int:id>/void", methods=["POST"])
@login_required
@role_required("admin", "guru_bk")
def void(id):
    e = db.get_or_404(ExpulsionRecommendation, id)
    if e.status == "void":
        return hx_render(
            "expulsion/index.html",
            error="Rekomendasi ekspulsi sudah dibatalkan.",
        )
    e.status = "void"
    db.session.commit()
    return hx_render(
        "expulsion/index.html",
        success=f"Rekomendasi ekspulsi {e.letter_number} dibatalkan.",
    )


@bp.route("/<int:id>/recover", methods=["POST"])
@login_required
@role_required("admin", "guru_bk")
def recover(id):
    e = db.get_or_404(ExpulsionRecommendation, id)
    if e.status != "void":
        return hx_render(
            "expulsion/index.html",
            error="Rekomendasi ekspulsi belum dibatalkan.",
        )
    e.status = "issued"
    db.session.commit()
    return hx_render(
        "expulsion/index.html",
        success=f"Rekomendasi ekspulsi {e.letter_number} dipulihkan.",
    )
