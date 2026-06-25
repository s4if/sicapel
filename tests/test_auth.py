from flask_login import login_required

from app import db
from app.helper import role_required, verify_password
from app.models import User
from tests.conftest import login


def test_login_page_get(client):
    resp = client.get("/auth/login")
    assert resp.status_code == 200
    assert b"SICAPEL" in resp.data


def test_root_redirects_to_dashboard(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers["Location"]


def test_protected_dashboard_redirects_to_login(client):
    resp = client.get("/dashboard/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_login_success_redirects_to_dashboard(client, admin):
    resp = login(client, "admin@example.com")
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers["Location"]


def test_login_wrong_password_shows_error(client, admin):
    resp = client.post(
        "/auth/login",
        data={"email": "admin@example.com", "password": "wrong"},
    )
    assert resp.status_code == 200
    assert b"salah" in resp.data


def test_login_unknown_user(client):
    resp = client.post(
        "/auth/login", data={"email": "nobody@example.com", "password": "x"}
    )
    assert resp.status_code == 200
    assert b"salah" in resp.data


def test_authenticated_user_at_login_redirects(client, admin):
    login(client, "admin@example.com")
    resp = client.get("/auth/login", follow_redirects=False)
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers["Location"]


def test_login_respects_safe_next(client, admin):
    resp = client.post(
        "/auth/login?next=/dashboard/",
        data={"email": "admin@example.com", "password": "password"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard/")


def test_login_rejects_unsafe_next(client, admin):
    resp = client.post(
        "/auth/login?next=https://evil.example.com/",
        data={"email": "admin@example.com", "password": "password"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "evil.example.com" not in resp.headers["Location"]


def test_login_rejects_protocol_relative_url(client, admin):
    resp = client.post(
        "/auth/login?next=//evil.example.com/",
        data={"email": "admin@example.com", "password": "password"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "evil.example.com" not in resp.headers["Location"]


def test_login_rejects_triple_slash_url(client, admin):
    resp = client.post(
        "/auth/login?next=///evil.example.com/",
        data={"email": "admin@example.com", "password": "password"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "evil.example.com" not in resp.headers["Location"]


def test_login_rejects_backslash_url(client, admin):
    resp = client.post(
        "/auth/login?next=\\\\evil.example.com/",
        data={"email": "admin@example.com", "password": "password"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "evil.example.com" not in resp.headers["Location"]


def test_logout_requires_login(client):
    resp = client.get("/auth/logout", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_change_password_requires_login(client):
    resp = client.get("/auth/change-password", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_change_password_page_get(client, admin):
    login(client, "admin@example.com")
    resp = client.get("/auth/change-password")
    assert resp.status_code == 200
    assert b"Ubah Password" in resp.data


def test_change_password_success(client, admin, app):
    login(client, "admin@example.com")
    resp = client.post(
        "/auth/change-password",
        data={
            "current_password": "password",
            "new_password": "newpassword123",
            "confirm_password": "newpassword123",
        },
    )
    assert resp.status_code == 200
    assert b"berhasil" in resp.data

    with app.app_context():
        user = db.session.get(User, admin.id)
        assert verify_password("newpassword123", user.password_hash)
        assert not verify_password("password", user.password_hash)


def test_change_password_wrong_current(client, admin, app):
    login(client, "admin@example.com")
    resp = client.post(
        "/auth/change-password",
        data={
            "current_password": "wrong",
            "new_password": "newpassword123",
            "confirm_password": "newpassword123",
        },
    )
    assert resp.status_code == 200
    assert b"salah" in resp.data

    with app.app_context():
        user = db.session.get(User, admin.id)
        assert verify_password("password", user.password_hash)


def test_change_password_mismatched_confirm(client, admin):
    login(client, "admin@example.com")
    resp = client.post(
        "/auth/change-password",
        data={
            "current_password": "password",
            "new_password": "newpassword123",
            "confirm_password": "different",
        },
    )
    assert resp.status_code == 200
    assert b"tidak cocok" in resp.data


def test_change_password_new_same_as_current(client, admin):
    login(client, "admin@example.com")
    resp = client.post(
        "/auth/change-password",
        data={
            "current_password": "password",
            "new_password": "password",
            "confirm_password": "password",
        },
    )
    assert resp.status_code == 200
    assert b"tidak boleh sama" in resp.data


def test_change_password_too_short(client, admin, app):
    login(client, "admin@example.com")
    resp = client.post(
        "/auth/change-password",
        data={
            "current_password": "password",
            "new_password": "short",
            "confirm_password": "short",
        },
    )
    assert resp.status_code == 200

    with app.app_context():
        user = db.session.get(User, admin.id)
        assert verify_password("password", user.password_hash)


def test_can_login_with_new_password(client, admin):
    login(client, "admin@example.com")
    client.post(
        "/auth/change-password",
        data={
            "current_password": "password",
            "new_password": "newpassword123",
            "confirm_password": "newpassword123",
        },
    )
    client.get("/auth/logout")
    resp = client.post(
        "/auth/login",
        data={"email": "admin@example.com", "password": "newpassword123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers["Location"]


def test_logout_clears_session(client, admin):
    login(client, "admin@example.com")
    resp = client.get("/auth/logout", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]
    after = client.get("/dashboard/", follow_redirects=False)
    assert after.status_code == 302
    assert "/auth/login" in after.headers["Location"]


def _register_role_route(app, path):
    @app.route(path)
    @login_required
    @role_required("admin")
    def _admin_only():
        return "ok"


def test_role_required_allows_correct_role(app, client, admin):
    _register_role_route(app, "/_test/admin-only")
    login(client, "admin@example.com")
    resp = client.get("/_test/admin-only")
    assert resp.status_code == 200


def test_role_required_blocks_wrong_role(app, client, wali_kelas):
    _register_role_route(app, "/_test/admin-only-2")
    login(client, "walikelas@example.com")
    resp = client.get("/_test/admin-only-2")
    assert resp.status_code == 403
    assert b"403" in resp.data


def test_404_handler(client):
    resp = client.get("/this-route-does-not-exist")
    assert resp.status_code == 404
    assert b"404" in resp.data
