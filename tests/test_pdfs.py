"""T12/T16 — PDF render smoke tests (§13.6).

Gated with ``importorskip("weasyprint")`` so they skip cleanly when the
OS-level Pango/Cairo deps are missing.
"""

from datetime import date, time

import pytest

weasyprint = pytest.importorskip("weasyprint")  # noqa: N816

from app import db  # noqa: E402
from app.services import record_violation, render_warning_letter_pdf  # noqa: E402
from tests.conftest import login  # noqa: E402

_INCIDENT = date(2026, 9, 1)


def _make_warning(setup):
    result = record_violation(
        student_id=setup.student.id,
        violation_type_id=setup.vt_berat.id,
        points=setup.vt_berat.default_points,
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


def test_render_warning_letter_pdf_is_pdf_bytes(violation_setup):
    wl = _make_warning(violation_setup)
    data = render_warning_letter_pdf(wl)
    assert isinstance(data, bytes)
    assert data[:4] == b"%PDF"
    assert len(data) > 100


def test_warning_letter_pdf_route(client, admin, violation_setup):
    wl = _make_warning(violation_setup)
    login(client, "admin@example.com")
    resp = client.get(f"/surat-peringatan/{wl.id}/pdf")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data[:4] == b"%PDF"
    assert "attachment" in resp.headers.get("Content-Disposition", "")
    safe = wl.letter_number.replace("/", "-")
    assert safe in resp.headers["Content-Disposition"]
