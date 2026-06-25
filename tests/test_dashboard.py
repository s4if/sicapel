"""T15 — dashboard blueprint: RBAC, role-scoped stats/data, ranking order,
> 200 highlight, HTMX auto-refresh panel.

The dashboard is the monitoring landing page (§1.8). Guru BK / admin see every
student; wali kelas only see students in their own class. Students with
``total_points > 200`` are flagged (display-only alert, §1.8 / §1.5).

Note the strict inequality: exactly 200 points does NOT flag (§1.8). The
simplest way to exceed 200 without triggering expulsion is three berat
violations (75 × 3 = 225, SP3) — a 4th berat would expel per §1.4.
"""

from datetime import date, time

import pytest

from app import db
from app.services import record_violation
from tests.conftest import login

_INCIDENT = date(2026, 9, 1)


def _record(setup, *, vt, student=None, points=None):
    """Thin wrapper around services.record_violation using the shared setup."""
    return record_violation(
        student_id=(student or setup.student).id,
        violation_type_id=vt.id,
        points=points if points is not None else vt.default_points,
        chronology="kronologi tes",
        location="halaman",
        incident_date=_INCIDENT,
        incident_time=time(8, 0),
        academic_year_id=setup.ay.id,
        semester="1",
        recorded_by=setup.guru_bk.id,
        session=db.session,
    )


def _drive_over_threshold(setup):
    """Three berat violations at the category max (75) -> 225 pts, SP3, NOT
    expelled (a 4th berat would expel per §1.4). Strictly > 200 (§1.8)."""
    for _ in range(3):
        _record(setup=setup, vt=setup.vt_berat, points=75)
    db.session.commit()


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
def test_index_redirects_when_anonymous(client):
    resp = client.get("/dashboard/")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


@pytest.mark.parametrize(
    "email", ["admin@example.com", "gurubk@example.com", "walikelas@example.com"]
)
def test_index_ok_for_every_role(client, admin, guru_bk, wali_kelas, email):
    login(client, email)
    assert client.get("/dashboard/").status_code == 200


@pytest.mark.parametrize("endpoint", ["/dashboard/stats", "/dashboard/data"])
def test_sub_endpoints_require_login(client, endpoint):
    assert client.get(endpoint).status_code == 302


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
def test_stats_shows_total_students(client, admin, violation_setup):
    login(client, "admin@example.com")
    body = client.get("/dashboard/stats").get_data(as_text=True)
    assert "Total Siswa" in body
    # one active student seeded by violation_setup
    assert "text-primary\">1</div>" in body


def test_stats_counts_alert_students(client, admin, violation_setup):
    _drive_over_threshold(setup=violation_setup)  # 225 pts > 200

    login(client, "admin@example.com")
    body = client.get("/dashboard/stats").get_data(as_text=True)
    assert "text-danger\">1</div>" in body


def test_stats_zero_alerts_under_threshold(client, admin, violation_setup):
    # Exactly 200 (sangat_berat) is NOT > 200 — no alert (§1.8 strict inequality).
    _record(setup=violation_setup, vt=violation_setup.vt_sangat)
    db.session.commit()

    login(client, "admin@example.com")
    body = client.get("/dashboard/stats").get_data(as_text=True)
    assert "text-danger\">0</div>" in body


def test_stats_reflects_expelled(client, admin, violation_setup):
    _record(setup=violation_setup, vt=violation_setup.vt_sangat)
    db.session.commit()

    login(client, "admin@example.com")
    body = client.get("/dashboard/stats").get_data(as_text=True)
    assert "Dikeluarkan" in body
    assert "text-secondary\">1</div>" in body


def test_stats_panel_htmx_partial_is_fragment(client, admin, violation_setup):
    """The stats endpoint returns a fragment (no <html>/nav) for HTMX swap."""
    login(client, "admin@example.com")
    body = client.get("/dashboard/stats").get_data(as_text=True)
    assert "<html" not in body
    assert "<nav" not in body


# ---------------------------------------------------------------------------
# Ranking data
# ---------------------------------------------------------------------------
def test_data_ranks_by_total_points_desc(client, admin, violation_setup):
    from tests.conftest import make_class, make_student

    cls2 = make_class(violation_setup.guru_bk.id, "X IPA 2")
    low = make_student(cls2.id, "2001", name="Budi")

    _record(setup=violation_setup, vt=violation_setup.vt_berat)  # 60
    _record(setup=violation_setup, vt=violation_setup.vt_ringan, student=low, points=25)
    db.session.commit()

    login(client, "admin@example.com")
    rows = client.get("/dashboard/data").get_json()["data"]
    assert rows[0]["name"] == "Siswa"
    assert rows[0]["points"] == 60
    assert rows[1]["name"] == "Budi"
    assert rows[1]["points"] == 25
    assert rows[0]["no"] == 1
    assert rows[1]["no"] == 2


def test_data_flags_alert_rows_over_200(client, admin, violation_setup):
    _drive_over_threshold(setup=violation_setup)  # 225 > 200

    login(client, "admin@example.com")
    rows = client.get("/dashboard/data").get_json()["data"]
    assert len(rows) == 1
    assert rows[0]["points"] == 225
    assert rows[0]["alert"] is True


def test_data_alert_false_at_exactly_200(client, admin, violation_setup):
    _record(setup=violation_setup, vt=violation_setup.vt_sangat)  # exactly 200
    db.session.commit()

    login(client, "admin@example.com")
    rows = client.get("/dashboard/data").get_json()["data"]
    assert rows[0]["points"] == 200
    assert rows[0]["alert"] is False


def test_data_excludes_students_without_summary(client, admin, violation_setup):
    """A student with no violations has no summary row -> not in ranking."""
    from tests.conftest import make_class, make_student

    cls2 = make_class(violation_setup.guru_bk.id, "X IPA 2")
    make_student(cls2.id, "9999", name="Tanpa Poin")

    login(client, "admin@example.com")
    rows = client.get("/dashboard/data").get_json()["data"]
    assert rows == []


def test_data_shows_sp_level(client, admin, violation_setup):
    _record(setup=violation_setup, vt=violation_setup.vt_berat)
    db.session.commit()

    login(client, "admin@example.com")
    rows = client.get("/dashboard/data").get_json()["data"]
    assert rows[0]["sp"] == "SP1"


def test_data_sanitizes_student_name(client, admin, violation_setup):
    """R9: user-controlled strings in DataTables cells are sanitized."""
    from tests.conftest import make_class, make_student

    cls2 = make_class(violation_setup.guru_bk.id, "X IPA X")
    s = make_student(cls2.id, "4001", name="<b>Bold</b>")
    _record(setup=violation_setup, vt=violation_setup.vt_ringan, student=s, points=5)
    db.session.commit()

    login(client, "admin@example.com")
    rows = client.get("/dashboard/data").get_json()["data"]
    names = [r["name"] for r in rows]
    assert "<b>Bold</b>" not in names
    assert "&lt;b&gt;Bold&lt;/b&gt;" in names


# ---------------------------------------------------------------------------
# Wali kelas scoping
# ---------------------------------------------------------------------------
def test_wali_kelas_only_sees_own_class(client, violation_setup):
    from tests.conftest import make_class, make_student, make_user

    wk1 = make_user("wali_kelas", "wk1@example.com", name="Wali Satu")
    wk2 = make_user("wali_kelas", "wk2@example.com", name="Wali Dua")
    cls1 = make_class(wk1.id, "X IPA A")
    cls2 = make_class(wk2.id, "X IPA B")
    s1 = make_student(cls1.id, "3001", name="Milik Wali 1")
    s2 = make_student(cls2.id, "3002", name="Milik Wali 2")

    _record(setup=violation_setup, vt=violation_setup.vt_ringan, student=s1, points=10)
    _record(setup=violation_setup, vt=violation_setup.vt_ringan, student=s2, points=20)
    db.session.commit()

    login(client, "wk1@example.com")
    rows = client.get("/dashboard/data").get_json()["data"]
    names = [r["name"] for r in rows]
    assert "Milik Wali 1" in names
    assert "Milik Wali 2" not in names


# ---------------------------------------------------------------------------
# Index page integration (HTMX auto-refresh wiring)
# ---------------------------------------------------------------------------
def test_index_has_htmx_poll_on_stats_panel(client, admin, violation_setup):
    login(client, "admin@example.com")
    body = client.get("/dashboard/").get_data(as_text=True)
    assert 'id="dashboard-stats"' in body
    assert 'hx-get="/dashboard/stats"' in body
    assert 'hx-trigger="every 60s"' in body


def test_index_has_ranking_table_and_highlight_js(client, admin, violation_setup):
    login(client, "admin@example.com")
    body = client.get("/dashboard/").get_data(as_text=True)
    assert 'id="dashboardRankTable"' in body
    assert "createdRow" in body
    assert "table-danger" in body


def test_index_shows_alert_badge_when_over_threshold(client, admin, violation_setup):
    _drive_over_threshold(setup=violation_setup)  # 225 > 200

    login(client, "admin@example.com")
    body = client.get("/dashboard/").get_data(as_text=True)
    assert "badge bg-danger" in body
    assert "225" not in body  # badge shows count, not points


def test_index_no_alert_badge_when_under_threshold(client, admin, violation_setup):
    login(client, "admin@example.com")
    body = client.get("/dashboard/").get_data(as_text=True)
    assert "badge bg-danger" not in body
