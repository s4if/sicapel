"""T14 — Point amnesties (pemutihan): form + list + detail + PDF + scan upload.

Amnesties reduce a student's ``total_points`` (possibly driving it negative,
§1.3/§1.6) and may optionally reset the active SP level (§1.6 ``sp_reset``).
A signed scanned letter is mandatory (§2.12 ``signed_document_id`` NOT NULL),
input by Guru BK on the principal's behalf. Access is admin + guru_bk only;
wali_kelas never sees this section.
"""

import io

from flask import Blueprint, jsonify, request, send_file, url_for
from flask_login import current_user, login_required

from .. import db
from ..forms import PointAmnestyForm
from ..helper import (
    current_academic_year,
    hx_render,
    role_required,
    sanitize,
)
from ..models import PointAmnesty, Student, StudentPointSummary
from ..services import apply_amnesty, render_amnesty_pdf
from ..uploads import UploadError, save_upload

bp = Blueprint("amnesties", __name__, url_prefix="/pemutihan")

# Only this document_type may be attached to a PointAmnesty (§2.8 / §2.12).
_AMNESTY_DOC_TYPE = "signed_amnesty_letter"


def _student_choices():
    """All students, ordered by name (no role-scoping — admin/guru_bk only)."""
    return [
        (
            s.id,
            f"{s.name} ({s.nis} - {s.class_.name if s.class_ else '-'})",
        )
        for s in Student.query.order_by(Student.name).all()
    ]


def _status_badge(status):
    cls = {"issued": "bg-success", "void": "bg-secondary"}.get(
        status, "bg-secondary"
    )
    label = {"issued": "Diterbitkan", "void": "Batal"}.get(status, status)
    return f'<span class="badge {cls}">{label}</span>'


def _row_actions(a):
    detail_url = f"{a.id}"
    pdf_url = f"{a.id}/pdf"
    return (
        f'<div class="btn-group btn-group-sm">'
        f'<a class="btn btn-outline-info" href="{detail_url}" '
        f'hx-get="{detail_url}" hx-target="#hx_content" hx-swap="innerHTML">'
        f'<i class="bi bi-eye"></i></a>'
        f'<a class="btn btn-outline-danger" href="{pdf_url}" target="_blank" '
        f'hx-boost="false" title="Cetak PDF"><i class="bi bi-file-pdf"></i></a>'
        f'<button class="btn btn-outline-warning" type="button" '
        f"onclick=\"void_amnesty({a.id}, '{sanitize(a.letter_number)}', '{url_for('amnesties.void', id=a.id)}')\" "
        f'title="Batalkan"><i class="bi bi-x-circle"></i></button>'
        f"</div>"
    )


@bp.route("/")
@login_required
@role_required("admin", "guru_bk")
def index():
    return hx_render("amnesties/index.html")


@bp.route("/data")
@login_required
@role_required("admin", "guru_bk")
def data():
    q = PointAmnesty.query.filter(PointAmnesty.status != "void")
    rows = []
    for i, a in enumerate(
        q.order_by(
            PointAmnesty.issue_date.desc(),
            PointAmnesty.letter_seq.desc(),
        ).all(),
        1,
    ):
        rows.append(
            {
                "no": i,
                "letter_number": sanitize(a.letter_number),
                "student": sanitize(a.student.name),
                "class": sanitize(a.student.class_.name)
                if a.student.class_
                else "-",
                "points_reduced": a.points_reduced,
                "sp_reset": "Ya" if a.sp_reset else "Tidak",
                "issue_date": a.issue_date.isoformat(),
                "principal": sanitize(a.principal_name),
                "status": _status_badge(a.status),
                "actions": _row_actions(a),
            }
        )
    return jsonify(data=rows)


@bp.route("/tambah", methods=["GET", "POST"])
@login_required
@role_required("admin", "guru_bk")
def tambah():
    form = PointAmnestyForm()
    form.student_id.choices = _student_choices()

    if request.method == "GET":
        return hx_render("amnesties/form.html", form=form, amnesty=None)

    if not form.validate_on_submit():  # R5: fail -> form
        return hx_render("amnesties/form.html", form=form, amnesty=None)

    ay = current_academic_year()
    if ay is None:
        return hx_render(
            "amnesties/form.html",
            form=form,
            amnesty=None,
            error="Tidak ada tahun ajaran aktif. Hubungi admin.",
        )

    # §1.6 / §2.12: a signed scanned letter is mandatory. Persist it first so
    # the Document has an id to reference; apply_amnesty requires a non-null
    # signed_document_id. save_upload add+flush only (caller commits, D10).
    try:
        doc = save_upload(
            form.file.data,
            document_type=_AMNESTY_DOC_TYPE,
            uploaded_by=current_user.id,
        )
    except UploadError as exc:
        return hx_render(
            "amnesties/form.html",
            form=form,
            amnesty=None,
            error=str(exc),
        )

    amnesty = apply_amnesty(
        student_id=form.student_id.data,
        points_reduced=form.points_reduced.data,
        sp_reset=bool(form.sp_reset.data),
        reason=sanitize(form.reason.data) if form.reason.data else "",
        reason_category=form.reason_category.data,
        principal_name=sanitize(form.principal_name.data),
        issue_date=form.issue_date.data,
        academic_year_id=ay.id,
        recorded_by=current_user.id,
        signed_document_id=doc.id,
        session=db.session,
    )
    db.session.commit()  # caller commits (D10)

    notif = {"success": "Pemutihan poin dicatat."}
    if amnesty.sp_reset:
        notif["info"] = "Level SP siswa direset."

    return hx_render(  # R5: success -> list
        "amnesties/index.html", push_url="amnesties.index", **notif
    )


@bp.route("/<int:id>")
@login_required
@role_required("admin", "guru_bk")
def detail(id):
    a = db.get_or_404(PointAmnesty, id)
    summary = StudentPointSummary.query.filter_by(
        student_id=a.student_id
    ).first()
    return hx_render("amnesties/detail.html", amnesty=a, summary=summary)


@bp.route("/<int:id>/pdf")
@login_required
@role_required("admin", "guru_bk")
def pdf(id):
    """PDF bytes via send_file — exempt from R1 (binary, not HTML, §6.2)."""
    a = db.get_or_404(PointAmnesty, id)
    pdf_bytes = render_amnesty_pdf(a)
    buf = io.BytesIO(pdf_bytes)
    buf.seek(0)
    download = f"{a.letter_number.replace('/', '-')}.pdf"
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
    from ..services import recompute_summary

    a = db.get_or_404(PointAmnesty, id)
    if a.status == "void":
        return hx_render(
            "amnesties/index.html",
            error="Pemutihan sudah dibatalkan.",
        )
    a.status = "void"
    recompute_summary(a.student_id, db.session)
    db.session.commit()
    return hx_render(
        "amnesties/index.html",
        success=f"Pemutihan {sanitize(a.letter_number)} dibatalkan.",
    )


@bp.route("/<int:id>/recover", methods=["POST"])
@login_required
@role_required("admin", "guru_bk")
def recover(id):
    from ..services import recompute_summary

    a = db.get_or_404(PointAmnesty, id)
    if a.status != "void":
        return hx_render(
            "amnesties/index.html",
            error="Pemutihan belum dibatalkan.",
        )
    a.status = "issued"
    recompute_summary(a.student_id, db.session)
    db.session.commit()
    return hx_render(
        "amnesties/index.html",
        success=f"Pemutihan {sanitize(a.letter_number)} dipulihkan.",
    )
