"""T13 — expulsion blueprint: RBAC, list/data, detail, PDF.

Expulsion recommendations are auto-issued by ``services.record_violation``
(§1.5); the two helper factories below exercise both triggers.
"""

from datetime import date, time

import pytest

from app import db
from app.models import Student
from app.services import record_violation
from tests.conftest import login

_INCIDENT = date(2026, 9, 1)


def _make_expulsion_via_sangat_berat(setup):
    """Trigger 1 (§1.5): sangat_berat -> immediate expulsion."""
    result = record_violation(
        student_id=setup.student.id,
        violation_type_id=setup.vt_sangat.id,
        points=setup.vt_sangat.default_points,
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
    return result["new_expulsion"]


def _make_expulsion_after_sp3(setup):
    """Trigger 2 (§1.5): menengah/berat after SP3 -> expulsion.

    Escalates null -> SP1 -> SP2 -> SP3 via three berat violations, then a
    fourth berat triggers the recommendation.
    """
    for _ in range(3):
        record_violation(
            student_id=setup.student.id,
            violation_type_id=setup.vt_berat.id,
            points=setup.vt_berat.default_points,
            chronology="x",
            location="x",
            incident_date=_INCIDENT,
            incident_time=time(8, 0),
            academic_year_id=setup.ay.id,
            semester="1",
            recorded_by=setup.guru_bk.id,
            session=db.session,
        )
    result = record_violation(
        student_id=setup.student.id,
        violation_type_id=setup.vt_berat.id,
        points=setup.vt_berat.default_points,
        chronology="x",
        location="x",
        incident_date=_INCIDENT,
        incident_time=time(8, 0),
        academic_year_id=setup.ay.id,
        semester="1",
        recorded_by=setup.guru_bk.id,
        session=db.session,
    )
    db.session.commit()
    return result["new_expulsion"]


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
def test_index_redirects_when_anonymous(client):
    resp = client.get("/ekspulsi/")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_index_blocked_for_wali_kelas(client, wali_kelas):
    login(client, "walikelas@example.com")
    assert client.get("/ekspulsi/").status_code == 403
    assert client.get("/ekspulsi/data").status_code == 403


@pytest.mark.parametrize("email", ["admin@example.com", "gurubk@example.com"])
def test_index_ok_for_admin_and_guru_bk(client, admin, guru_bk, email):
    login(client, email)
    assert client.get("/ekspulsi/").status_code == 200


# ---------------------------------------------------------------------------
# data + detail
# ---------------------------------------------------------------------------
def test_data_lists_issued_expulsion(client, admin, violation_setup):
    e = _make_expulsion_via_sangat_berat(violation_setup)
    login(client, "admin@example.com")
    resp = client.get("/ekspulsi/data")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["data"][0]["letter_number"] == e.letter_number
    assert payload["data"][0]["student"] == violation_setup.student.name


def test_data_excludes_void_expulsion(client, admin, violation_setup):
    e = _make_expulsion_via_sangat_berat(violation_setup)
    e.status = "void"
    db.session.commit()
    login(client, "admin@example.com")
    payload = client.get("/ekspulsi/data").get_json()
    assert payload["data"] == []


def test_detail_shows_expulsion(client, admin, violation_setup):
    e = _make_expulsion_via_sangat_berat(violation_setup)
    login(client, "admin@example.com")
    body = client.get(f"/ekspulsi/{e.id}").get_data(as_text=True)
    assert e.letter_number in body
    assert "Rekomendasi Ekspulsi" in body
    assert violation_setup.student.name in body
    # The sangat_berat trigger violation is linked.
    assert "Pelanggaran Pemicu" in body


def test_detail_404_for_missing(client, admin):
    login(client, "admin@example.com")
    assert client.get("/ekspulsi/9999").status_code == 404


def test_detail_shows_post_sp3_expulsion(client, admin, violation_setup):
    """Trigger 2 path: detail still renders, links the triggering violation."""
    e = _make_expulsion_after_sp3(violation_setup)
    login(client, "admin@example.com")
    body = client.get(f"/ekspulsi/{e.id}").get_data(as_text=True)
    assert e.letter_number in body


# ---------------------------------------------------------------------------
# PDF (gated on weasyprint like test_pdfs.py)
# ---------------------------------------------------------------------------
def test_render_expulsion_pdf_is_pdf_bytes(violation_setup):
    pytest.importorskip("weasyprint")
    from app.services import render_expulsion_pdf

    e = _make_expulsion_via_sangat_berat(violation_setup)
    data = render_expulsion_pdf(e)
    assert isinstance(data, bytes)
    assert data[:4] == b"%PDF"
    assert len(data) > 100


def test_expulsion_pdf_route(client, admin, violation_setup):
    pytest.importorskip("weasyprint")
    e = _make_expulsion_via_sangat_berat(violation_setup)
    login(client, "admin@example.com")
    resp = client.get(f"/ekspulsi/{e.id}/pdf")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data[:4] == b"%PDF"
    assert "attachment" in resp.headers.get("Content-Disposition", "")
    safe = e.letter_number.replace("/", "-")
    assert safe in resp.headers["Content-Disposition"]


def test_pdf_blocked_for_wali_kelas(client, wali_kelas, violation_setup):
    e = _make_expulsion_via_sangat_berat(violation_setup)
    login(client, "walikelas@example.com")
    assert client.get(f"/ekspulsi/{e.id}/pdf").status_code == 403


# ---------------------------------------------------------------------------
# void / recover — student.status reconciliation
# ---------------------------------------------------------------------------
def test_void_expulsion_restores_student_status(client, admin, violation_setup):
    """Voiding an expulsion flips student.status expelled -> active."""
    e = _make_expulsion_via_sangat_berat(violation_setup)
    db.session.commit()

    sid = violation_setup.student.id
    assert db.session.get(Student, sid).status == "expelled"

    login(client, "admin@example.com")
    resp = client.post(f"/ekspulsi/{e.id}/void")
    assert resp.status_code == 200

    db.session.expire_all()
    assert db.session.get(Student, sid).status == "active"


def test_recover_expulsion_re_marks_student_expelled(client, admin, violation_setup):
    """Recovering a voided expulsion flips student.status active -> expelled."""
    e = _make_expulsion_via_sangat_berat(violation_setup)
    db.session.commit()

    sid = violation_setup.student.id
    assert db.session.get(Student, sid).status == "expelled"

    login(client, "admin@example.com")
    client.post(f"/ekspulsi/{e.id}/void")
    db.session.expire_all()
    assert db.session.get(Student, sid).status == "active"

    client.post(f"/ekspulsi/{e.id}/recover")
    db.session.expire_all()
    assert db.session.get(Student, sid).status == "expelled"
