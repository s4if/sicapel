from flask_login import login_required

from app.helper import class_owned_required, role_required
from tests.conftest import login, make_class, make_student, make_user


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


def _register_class_owned_route(app, path):
    @app.route(path)
    @login_required
    @class_owned_required
    def _student_view(student_id):
        return "ok"


def test_class_owned_required_bypasses_for_admin(app, client, admin):
    other = make_user("wali_kelas", "other@example.com", name="Other WK")
    cls = make_class(other.id, "XI IPA 9")
    student = make_student(cls.id, "999")
    _register_class_owned_route(app, "/_test/student-a/<int:student_id>")
    login(client, "admin@example.com")
    resp = client.get(f"/_test/student-a/{student.id}")
    assert resp.status_code == 200


def test_class_owned_required_allows_owner_wali_kelas(app, client, wali_kelas):
    cls = make_class(wali_kelas.id, "X IPA 1")
    student = make_student(cls.id, "100")
    _register_class_owned_route(app, "/_test/student-b/<int:student_id>")
    login(client, "walikelas@example.com")
    resp = client.get(f"/_test/student-b/{student.id}")
    assert resp.status_code == 200


def test_class_owned_required_blocks_non_owner_wali_kelas(app, client, wali_kelas):
    other = make_user("wali_kelas", "other2@example.com", name="Other WK")
    cls = make_class(other.id, "X IPA 2")
    student = make_student(cls.id, "200")
    _register_class_owned_route(app, "/_test/student-c/<int:student_id>")
    login(client, "walikelas@example.com")
    resp = client.get(f"/_test/student-c/{student.id}")
    assert resp.status_code == 403


def test_404_handler(client):
    resp = client.get("/this-route-does-not-exist")
    assert resp.status_code == 404
    assert b"404" in resp.data
