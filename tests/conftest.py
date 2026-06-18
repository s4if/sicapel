import pytest

from app import create_app, db
from app.helper import hash_password
from app.models import Class, Student, User


def make_user(role, email, name=None, password="password"):
    user = User(
        name=name or f"User {role}",
        email=email,
        role=role,
        password_hash=hash_password(password),
    )
    db.session.add(user)
    db.session.commit()
    return user


def make_class(homeroom_teacher_id, name, grade_level=10):
    cls = Class(
        name=name,
        grade_level=grade_level,
        homeroom_teacher_id=homeroom_teacher_id,
    )
    db.session.add(cls)
    db.session.commit()
    return cls


def make_student(class_id, nis, name="Siswa"):
    student = Student(
        nis=nis,
        name=name,
        gender="L",
        class_id=class_id,
        status="active",
    )
    db.session.add(student)
    db.session.commit()
    return student


@pytest.fixture
def app():
    app = create_app(
        test_config={
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "WTF_CSRF_ENABLED": False,
            "SECRET_KEY": "test-secret",
        }
    )
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin(app):
    return make_user("admin", "admin@example.com")


@pytest.fixture
def guru_bk(app):
    return make_user("guru_bk", "gurubk@example.com")


@pytest.fixture
def wali_kelas(app):
    return make_user("wali_kelas", "walikelas@example.com")


def login(client, email, password="password"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
