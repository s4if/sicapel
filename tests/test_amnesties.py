"""T14 — amnesties blueprint: RBAC, list/data, create + scan upload, detail, PDF.

The create flow uploads the mandatory signed scan, then calls
``services.apply_amnesty``; service-level rules (point reduction, sp_reset,
negative totals) are covered exhaustively in ``test_apply_amnesty.py``.
"""

import io
from datetime import date

import pytest
from werkzeug.datastructures import FileStorage

from app import db
from app.models import Document, PointAmnesty, StudentPointSummary
from app.services import apply_amnesty
from tests.conftest import login, make_document

_ISSUE = date(2026, 10, 1)


def _make_amnesty(setup, *, sp_reset=False, points_reduced=30):
    """Create an amnesty row directly via the service (admin/guru_bk path)."""
    doc = make_document(setup.guru_bk.id)
    am = apply_amnesty(
        student_id=setup.student.id,
        points_reduced=points_reduced,
        sp_reset=sp_reset,
        reason="Prestasi OSN",
        reason_category="prestasi",
        principal_name="Drs. Kepala Sekolah",
        issue_date=_ISSUE,
        academic_year_id=setup.ay.id,
        recorded_by=setup.guru_bk.id,
        signed_document_id=doc.id,
        session=db.session,
    )
    db.session.commit()
    return am


def _png_storage(filename="scan.png"):
    """Real PNG bytes (so python-magic sniffs image/png, not the extension)."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buf, format="PNG")
    buf.seek(0)
    return FileStorage(stream=buf, filename=filename, content_type="image/png")


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
def test_index_redirects_when_anonymous(client):
    resp = client.get("/pemutihan/")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_index_blocked_for_wali_kelas(client, wali_kelas):
    login(client, "walikelas@example.com")
    assert client.get("/pemutihan/").status_code == 403
    assert client.get("/pemutihan/data").status_code == 403
    assert client.get("/pemutihan/tambah").status_code == 403


@pytest.mark.parametrize("email", ["admin@example.com", "gurubk@example.com"])
def test_index_ok_for_admin_and_guru_bk(client, admin, guru_bk, email):
    login(client, email)
    assert client.get("/pemutihan/").status_code == 200
    assert client.get("/pemutihan/tambah").status_code == 200


# ---------------------------------------------------------------------------
# data + detail
# ---------------------------------------------------------------------------
def test_data_lists_issued_amnesty(client, admin, violation_setup):
    am = _make_amnesty(violation_setup)
    login(client, "admin@example.com")
    resp = client.get("/pemutihan/data")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["data"][0]["letter_number"] == am.letter_number
    assert payload["data"][0]["points_reduced"] == 30
    assert payload["data"][0]["sp_reset"] == "Tidak"


def test_data_excludes_void_amnesty(client, admin, violation_setup):
    am = _make_amnesty(violation_setup)
    am.status = "void"
    db.session.commit()
    login(client, "admin@example.com")
    payload = client.get("/pemutihan/data").get_json()
    assert payload["data"] == []


def test_detail_shows_amnesty(client, admin, violation_setup):
    am = _make_amnesty(violation_setup, sp_reset=True)
    login(client, "admin@example.com")
    body = client.get(f"/pemutihan/{am.id}").get_data(as_text=True)
    assert am.letter_number in body
    assert am.principal_name in body
    assert "Ya" in body  # sp_reset badge
    assert am.signed_document.file_name in body


def test_detail_404_for_missing(client, admin):
    login(client, "admin@example.com")
    assert client.get("/pemutihan/9999").status_code == 404


# ---------------------------------------------------------------------------
# create flow (tambah) + mandatory scan upload
# ---------------------------------------------------------------------------
def test_tambah_creates_amnesty_with_signed_doc(
    client, app, admin, violation_setup, tmp_path
):
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    login(client, "admin@example.com")

    resp = client.post(
        "/pemutihan/tambah",
        data={
            "student_id": violation_setup.student.id,
            "points_reduced": 40,
            "reason_category": "prestasi",
            "reason": "Juara OSN",
            "sp_reset": "y",
            "principal_name": "Drs. Kepala",
            "issue_date": "2026-10-01",
            "file": _png_storage("ttd.png"),
            "submit": "Simpan",
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200

    am = db.session.query(PointAmnesty).first()
    assert am is not None
    assert am.points_reduced == 40
    assert am.sp_reset is True
    assert am.principal_name == "Drs. Kepala"
    assert am.recorded_by == admin.id

    # Mandatory signed document attached + written to disk.
    doc = db.session.get(Document, am.signed_document_id)
    assert doc.document_type == "signed_amnesty_letter"
    assert doc.uploaded_by == admin.id
    assert (tmp_path / "signed_amnesty_letter").exists()

    # total_points reduced (and may go negative — here just reduced).
    summary = db.session.get(StudentPointSummary, violation_setup.student.id)
    assert summary.total_points == -40


def test_tambah_without_sp_reset_keeps_level(client, app, guru_bk, violation_setup, tmp_path):
    """SP2 -> amnesty without sp_reset keeps the SP level (§1.6)."""
    from app.services import record_violation

    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    for _ in range(2):  # null -> SP1 -> SP2
        record_violation(
            student_id=violation_setup.student.id,
            violation_type_id=violation_setup.vt_berat.id,
            points=violation_setup.vt_berat.default_points,
            chronology="",
            location="",
            incident_date=_ISSUE,
            incident_time=None,
            academic_year_id=violation_setup.ay.id,
            semester="1",
            recorded_by=violation_setup.guru_bk.id,
            session=db.session,
        )
    db.session.commit()
    summary = db.session.get(StudentPointSummary, violation_setup.student.id)
    assert summary.current_sp_level == "2"

    login(client, "gurubk@example.com")
    client.post(
        "/pemutihan/tambah",
        data={
            "student_id": violation_setup.student.id,
            "points_reduced": 10,
            "reason_category": "perilaku_baik",
            "reason": "x",
            "principal_name": "Kepala",
            "issue_date": "2026-10-01",
            "file": _png_storage("ttd.png"),
            "submit": "Simpan",
        },
        content_type="multipart/form-data",
    )

    summary = db.session.get(StudentPointSummary, violation_setup.student.id)
    assert summary.current_sp_level == "2"  # unchanged


def test_tambah_rejects_bad_mime(client, app, admin, violation_setup, tmp_path):
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    login(client, "admin@example.com")

    bogus = FileStorage(
        stream=io.BytesIO(b"not a real file, plain text"),
        filename="evil.pdf",
        content_type="application/pdf",
    )
    resp = client.post(
        "/pemutihan/tambah",
        data={
            "student_id": violation_setup.student.id,
            "points_reduced": 10,
            "reason_category": "lainnya",
            "principal_name": "Kepala",
            "issue_date": "2026-10-01",
            "file": bogus,
            "submit": "Simpan",
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert "tidak diizinkan" in resp.get_data(as_text=True)
    assert db.session.query(PointAmnesty).count() == 0
    assert db.session.query(Document).count() == 0


def test_tambah_requires_file(client, app, admin, violation_setup, tmp_path):
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    login(client, "admin@example.com")

    resp = client.post(
        "/pemutihan/tambah",
        data={
            "student_id": violation_setup.student.id,
            "points_reduced": 10,
            "reason_category": "lainnya",
            "principal_name": "Kepala",
            "issue_date": "2026-10-01",
            "submit": "Simpan",
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert "wajib diunggah" in resp.get_data(as_text=True)
    assert db.session.query(PointAmnesty).count() == 0


def test_tambah_requires_active_academic_year(client, app, admin, violation_setup, tmp_path):
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    violation_setup.ay.is_active = False
    db.session.commit()
    login(client, "admin@example.com")

    resp = client.post(
        "/pemutihan/tambah",
        data={
            "student_id": violation_setup.student.id,
            "points_reduced": 10,
            "reason_category": "lainnya",
            "principal_name": "Kepala",
            "issue_date": "2026-10-01",
            "file": _png_storage("ttd.png"),
            "submit": "Simpan",
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert "tahun ajaran aktif" in resp.get_data(as_text=True)
    assert db.session.query(PointAmnesty).count() == 0


# ---------------------------------------------------------------------------
# PDF (gated on weasyprint like test_pdfs.py)
# ---------------------------------------------------------------------------
def test_render_amnesty_pdf_is_pdf_bytes(violation_setup):
    pytest.importorskip("weasyprint")
    from app.services import render_amnesty_pdf

    am = _make_amnesty(violation_setup)
    data = render_amnesty_pdf(am)
    assert isinstance(data, bytes)
    assert data[:4] == b"%PDF"
    assert len(data) > 100


def test_amnesty_pdf_route(client, admin, violation_setup):
    pytest.importorskip("weasyprint")
    am = _make_amnesty(violation_setup)
    login(client, "admin@example.com")
    resp = client.get(f"/pemutihan/{am.id}/pdf")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data[:4] == b"%PDF"
    assert "attachment" in resp.headers.get("Content-Disposition", "")
    safe = am.letter_number.replace("/", "-")
    assert safe in resp.headers["Content-Disposition"]


def test_pdf_blocked_for_wali_kelas(client, wali_kelas, violation_setup):
    am = _make_amnesty(violation_setup)
    login(client, "walikelas@example.com")
    assert client.get(f"/pemutihan/{am.id}/pdf").status_code == 403
