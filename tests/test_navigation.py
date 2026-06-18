"""Tests for T5: base.html / macros.html / role-aware nav / dual-mode header."""
import pytest

from tests.conftest import login


def _nav(client, email):
    login(client, email)
    resp = client.get("/dashboard/")
    client.get("/auth/logout")
    return resp


def test_nav_shows_everything_for_admin(client, admin):
    resp = _nav(client, "admin@example.com")
    for label in (
        b"Dashboard",
        b"Pelanggaran",
        b"Siswa",
        b"Surat Peringatan",
        b"Pemutihan",
        b"Ekspulsi",
        b"Administrasi",
    ):
        assert label in resp.data


def test_nav_for_guru_bk_has_data_sections_not_admin(client, guru_bk):
    resp = _nav(client, "gurubk@example.com")
    assert b"Surat Peringatan" in resp.data
    assert b"Pemutihan" in resp.data
    assert b"Ekspulsi" in resp.data
    assert b"Administrasi" not in resp.data


def test_nav_for_wali_kelas_only_has_basic_sections(client, wali_kelas):
    resp = _nav(client, "walikelas@example.com")
    assert b"Pelanggaran" in resp.data
    assert b"Siswa" in resp.data
    assert b"Surat Peringatan" not in resp.data
    assert b"Pemutihan" not in resp.data
    assert b"Ekspulsi" not in resp.data
    assert b"Administrasi" not in resp.data


def test_nav_links_carry_both_href_and_hx_get(client, admin):
    login(client, "admin@example.com")
    resp = client.get("/dashboard/")
    body = resp.data.decode()
    # R6: in-content links carry both href and hx-get at the same URL.
    assert 'href="/pelanggaran/"' in body
    assert 'hx-get="/pelanggaran/"' in body


def test_nav_hidden_when_not_authenticated(client):
    resp = client.get("/auth/login")
    assert b'<nav class="navbar' not in resp.data


def test_base_has_single_swap_target_and_boost(client, admin):
    login(client, "admin@example.com")
    resp = client.get("/dashboard/")
    body = resp.data.decode()
    # R7 + R10
    assert 'hx-boost="true"' in body
    assert 'id="hx_content"' in body


@pytest.mark.parametrize(
    "url",
    [
        "/siswa/",
        "/kelas/",
        "/pelanggaran/",
        "/surat-peringatan/",
        "/pemutihan/",
        "/ekspulsi/",
        "/pengguna/",
        "/jenis-pelanggaran/",
        "/tahun-ajaran/",
    ],
)
def test_stub_routes_accessible_for_admin(client, admin, url):
    login(client, "admin@example.com")
    assert client.get(url).status_code == 200


@pytest.mark.parametrize(
    "url",
    ["/kelas/", "/pengguna/", "/jenis-pelanggaran/", "/tahun-ajaran/"],
)
def test_admin_only_routes_blocked_for_guru_bk(client, guru_bk, url):
    login(client, "gurubk@example.com")
    assert client.get(url).status_code == 403


@pytest.mark.parametrize(
    "url", ["/surat-peringatan/", "/pemutihan/", "/ekspulsi/"]
)
def test_guru_bk_routes_blocked_for_wali_kelas(client, wali_kelas, url):
    login(client, "walikelas@example.com")
    assert client.get(url).status_code == 403


@pytest.mark.parametrize(
    "url", ["/siswa/", "/pelanggaran/"]
)
def test_shared_routes_accessible_for_wali_kelas(client, wali_kelas, url):
    login(client, "walikelas@example.com")
    assert client.get(url).status_code == 200


def test_htmx_request_strips_base_layout(client, admin):
    login(client, "admin@example.com")
    resp = client.get("/siswa/", headers={"HX-Request": "true"})
    body = resp.data.decode()
    # Dual-mode header: partial emits <title> but not <html>/<nav>/#hx_content
    assert "<title>" in body
    assert "<html" not in body
    assert "<nav" not in body
    assert 'id="hx_content"' not in body


def test_full_request_includes_base_layout(client, admin):
    login(client, "admin@example.com")
    resp = client.get("/siswa/")
    body = resp.data.decode()
    assert "<html" in body
    assert 'id="hx_content"' in body
