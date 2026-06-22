"""T12 — warnings blueprint: RBAC, list/data, detail, signed-scan upload."""

import io
from datetime import date, time

import pytest
from werkzeug.datastructures import FileStorage

from app import db
from app.models import Document, WarningLetter
from app.services import record_violation
from tests.conftest import login

_INCIDENT = date(2026, 9, 1)


def _make_warning(setup, vt=None):
    """Issue a SP1 warning letter via the real service (berat from null)."""
    result = record_violation(
        student_id=setup.student.id,
        violation_type_id=(vt or setup.vt_berat).id,
        points=(vt or setup.vt_berat).default_points,
        chronology=" Kronologi tes.",
        location="Halaman",
        incident_date=_INCIDENT,
        incident_time=time(8, 0),
        academic_year_id=setup.ay.id,
        semester="1",
        recorded_by=setup.guru_bk.id,
        session=db.session,
    )
    db.session.commit()
    return result["new_warning"]


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
    resp = client.get("/surat-peringatan/")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_index_blocked_for_wali_kelas(client, wali_kelas):
    login(client, "walikelas@example.com")
    assert client.get("/surat-peringatan/").status_code == 403
    assert client.get("/surat-peringatan/data").status_code == 403


@pytest.mark.parametrize("email", ["admin@example.com", "gurubk@example.com"])
def test_index_ok_for_admin_and_guru_bk(client, admin, guru_bk, email):
    login(client, email)
    assert client.get("/surat-peringatan/").status_code == 200


# ---------------------------------------------------------------------------
# data + detail
# ---------------------------------------------------------------------------
def test_data_lists_issued_warning(client, admin, violation_setup):
    wl = _make_warning(violation_setup)
    login(client, "admin@example.com")
    resp = client.get("/surat-peringatan/data")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["data"][0]["letter_number"] == wl.letter_number
    assert payload["data"][0]["level"] == "SP1"


def test_data_excludes_void_warning(client, admin, violation_setup):
    wl = _make_warning(violation_setup)
    wl.status = "void"
    db.session.commit()
    login(client, "admin@example.com")
    payload = client.get("/surat-peringatan/data").get_json()
    assert payload["data"] == []


def test_detail_shows_letter(client, admin, violation_setup):
    wl = _make_warning(violation_setup)
    login(client, "admin@example.com")
    body = client.get(f"/surat-peringatan/{wl.id}").get_data(as_text=True)
    assert wl.letter_number in body
    assert "SP1" in body
    assert "Unggah Dokumen" in body


# ---------------------------------------------------------------------------
# signed-scan upload
# ---------------------------------------------------------------------------
def test_upload_signed_attaches_doc_and_flips_status(
    client, app, admin, violation_setup, tmp_path
):
    wl = _make_warning(violation_setup)
    assert wl.status == "issued"

    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    login(client, "admin@example.com")

    resp = client.post(
        f"/surat-peringatan/{wl.id}/upload-signed",
        data={
            "document_type": "signed_warning_letter",
            "file": _png_storage("ttd.png"),
            "submit": "Unggah",
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200

    db.session.refresh(wl)
    assert wl.signed_warning_doc_id is not None
    assert wl.status == "signed_returned"
    doc = db.session.get(Document, wl.signed_warning_doc_id)
    assert doc.document_type == "signed_warning_letter"
    assert doc.warning_letter_id == wl.id
    assert doc.mime_type == "image/png"
    assert (tmp_path / "signed_warning_letter").exists()


def test_upload_signed_rejects_bad_mime(client, app, admin, violation_setup, tmp_path):
    wl = _make_warning(violation_setup)
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    login(client, "admin@example.com")

    bogus = FileStorage(
        stream=io.BytesIO(b"not a real file at all, just text"),
        filename="evil.pdf",
        content_type="application/pdf",
    )
    resp = client.post(
        f"/surat-peringatan/{wl.id}/upload-signed",
        data={"document_type": "signed_warning_letter", "file": bogus, "submit": "Unggah"},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "tidak diizinkan" in body
    db.session.refresh(wl)
    assert wl.signed_warning_doc_id is None
    assert wl.status == "issued"


def test_upload_signed_requires_file(client, app, admin, violation_setup, tmp_path):
    wl = _make_warning(violation_setup)
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    login(client, "admin@example.com")

    resp = client.post(
        f"/surat-peringatan/{wl.id}/upload-signed",
        data={"document_type": "signed_warning_letter", "submit": "Unggah"},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert "wajib diunggah" in resp.get_data(as_text=True)


def test_upload_blocked_for_wali_kelas(client, wali_kelas, violation_setup):
    wl = _make_warning(violation_setup)
    login(client, "walikelas@example.com")
    assert (
        client.get(f"/surat-peringatan/{wl.id}").status_code == 403
    )
    assert (
        client.post(f"/surat-peringatan/{wl.id}/upload-signed").status_code == 403
    )


def test_upload_two_docs_both_attached(client, app, admin, violation_setup, tmp_path):
    wl = _make_warning(violation_setup)
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    login(client, "admin@example.com")

    client.post(
        f"/surat-peringatan/{wl.id}/upload-signed",
        data={
            "document_type": "signed_warning_letter",
            "file": _png_storage("a.png"),
            "submit": "Unggah",
        },
        content_type="multipart/form-data",
    )
    client.post(
        f"/surat-peringatan/{wl.id}/upload-signed",
        data={
            "document_type": "signed_statement_letter",
            "file": _png_storage("b.png"),
            "submit": "Unggah",
        },
        content_type="multipart/form-data",
    )

    db.session.refresh(wl)
    assert wl.signed_warning_doc_id is not None
    assert wl.signed_statement_doc_id is not None
    assert db.session.query(Document).count() == 2


def test_letter_count_after_escalation(violation_setup):
    """SP1 then SP2 via two berat violations produces two warning letters."""
    _make_warning(violation_setup)  # SP1
    r2 = record_violation(
        student_id=violation_setup.student.id,
        violation_type_id=violation_setup.vt_berat.id,
        points=violation_setup.vt_berat.default_points,
        chronology="x",
        location="x",
        incident_date=_INCIDENT,
        incident_time=time(8, 0),
        academic_year_id=violation_setup.ay.id,
        semester="1",
        recorded_by=violation_setup.guru_bk.id,
        session=db.session,
    )
    db.session.commit()
    assert r2["new_warning"].level == "SP2"
    assert db.session.query(WarningLetter).count() == 2
