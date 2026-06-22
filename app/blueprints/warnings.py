"""T12 — Warning letters (SP1/SP2/SP3): list + detail + PDF + signed-scan upload.

Warning letters are auto-issued by ``services.record_violation`` (§1.4) —
this blueprint is read/attach-only: there is no manual "create" route.
Access is admin + guru_bk only (wali_kelas never sees this section).
"""

import io

from flask import Blueprint, jsonify, send_file
from flask_login import current_user, login_required

from ..forms import SignedScanUploadForm
from ..helper import hx_render, role_required, sanitize
from ..models import WarningLetter
from ..services import render_warning_letter_pdf
from ..uploads import UploadError, save_upload

bp = Blueprint("warnings", __name__, url_prefix="/surat-peringatan")

# Only these two document_types may be attached to a WarningLetter (§2.8).
_SIGNED_DOC_TYPES = ("signed_warning_letter", "signed_statement_letter")


def _status_badge(status):
    cls = {
        "issued": "bg-warning text-dark",
        "signed_returned": "bg-success",
        "void": "bg-secondary",
    }.get(status, "bg-secondary")
    label = {
        "issued": "Diterbitkan",
        "signed_returned": "Sudah Ditandatangani",
        "void": "Batal",
    }.get(status, status)
    return f'<span class="badge {cls}">{label}</span>'


def _row_actions(w):
    detail_url = f"{w.id}"
    pdf_url = f"{w.id}/pdf"
    return (
        f'<div class="btn-group btn-group-sm">'
        f'<a class="btn btn-outline-info" href="{detail_url}" '
        f'hx-get="{detail_url}" hx-target="#hx_content" hx-swap="innerHTML">'
        f'<i class="bi bi-eye"></i></a>'
        f'<a class="btn btn-outline-danger" href="{pdf_url}" target="_blank" '
        f'hx-boost="false" title="Cetak PDF"><i class="bi bi-file-pdf"></i></a>'
        f"</div>"
    )


@bp.route("/")
@login_required
@role_required("admin", "guru_bk")
def index():
    return hx_render("warnings/index.html")


@bp.route("/data")
@login_required
@role_required("admin", "guru_bk")
def data():
    q = WarningLetter.query.filter(WarningLetter.status != "void")
    rows = []
    for i, w in enumerate(
        q.order_by(
            WarningLetter.issue_date.desc(),
            WarningLetter.letter_seq.desc(),
        ).all(),
        1,
    ):
        rows.append(
            {
                "no": i,
                "letter_number": sanitize(w.letter_number),
                "level": w.level,
                "student": sanitize(w.student.name),
                "class": sanitize(w.student.class_.name)
                if w.student.class_
                else "-",
                "points": w.total_points_at_issue,
                "issue_date": w.issue_date.isoformat(),
                "status": _status_badge(w.status),
                "actions": _row_actions(w),
            }
        )
    return jsonify(data=rows)


@bp.route("/<int:id>")
@login_required
@role_required("admin", "guru_bk")
def detail(id):
    from .. import db

    w = db.get_or_404(WarningLetter, id)
    form = SignedScanUploadForm()
    return hx_render("warnings/detail.html", letter=w, form=form)


@bp.route("/<int:id>/pdf")
@login_required
@role_required("admin", "guru_bk")
def pdf(id):
    """PDF bytes via send_file — exempt from R1 (binary, not HTML, §6.2)."""
    from .. import db

    w = db.get_or_404(WarningLetter, id)
    pdf_bytes = render_warning_letter_pdf(w)
    buf = io.BytesIO(pdf_bytes)
    buf.seek(0)
    download = f"{w.letter_number.replace('/', '-')}.pdf"
    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=download,
    )


@bp.route("/<int:id>/upload-signed", methods=["POST"])
@login_required
@role_required("admin", "guru_bk")
def upload_signed(id):
    from .. import db

    w = db.get_or_404(WarningLetter, id)

    if w.status == "void":
        return hx_render(
            "warnings/detail.html",
            letter=w,
            form=SignedScanUploadForm(),
            error="Surat yang dibatalkan tidak dapat menerima dokumen.",
        )

    form = SignedScanUploadForm()
    if not form.validate_on_submit():
        return hx_render(
            "warnings/detail.html",
            letter=w,
            form=form,
            error="Pilih jenis dokumen dan lampirkan file.",
        )

    doc_type = form.document_type.data
    if doc_type not in _SIGNED_DOC_TYPES:
        return hx_render(
            "warnings/detail.html",
            letter=w,
            form=form,
            error="Jenis dokumen tidak valid.",
        )

    try:
        doc = save_upload(
            form.file.data,
            document_type=doc_type,
            uploaded_by=current_user.id,
            warning_letter_id=w.id,
        )
    except UploadError as exc:
        return hx_render(
            "warnings/detail.html",
            letter=w,
            form=form,
            error=str(exc),
        )

    if doc_type == "signed_warning_letter":
        w.signed_warning_doc_id = doc.id
    else:
        w.signed_statement_doc_id = doc.id

    # First signed scan flips the letter from "issued" to "signed_returned".
    if w.status == "issued":
        w.status = "signed_returned"

    db.session.commit()

    return hx_render(
        "warnings/detail.html",
        letter=w,
        form=SignedScanUploadForm(),
        success="Dokumen berhasil diunggah.",
    )
