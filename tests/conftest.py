from datetime import date

import pytest

from app import create_app, db
from app.helper import hash_password
from app.models import (
    AcademicYear,
    Class,
    Document,
    Student,
    User,
    ViolationCategory,
    ViolationType,
)


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


def make_academic_year(year="2026/2027", active=True):
    start_year = int(year.split("/")[0])
    ay = AcademicYear(
        year=year,
        start_date=date(start_year, 7, 1),
        end_date=date(start_year + 1, 6, 30),
        is_active=active,
    )
    db.session.add(ay)
    db.session.commit()
    return ay


_CATEGORY_SPECS = {
    "ringan": (5, 25, False),
    "menengah": (25, 50, False),
    "berat": (51, 75, False),
    "sangat_berat": (200, 200, True),
}


def make_categories():
    """Create the 4 seeded violation_categories, return a name->model dict."""
    created = {}
    for name, (lo, hi, direct) in _CATEGORY_SPECS.items():
        cat = ViolationCategory.query.filter_by(name=name).first()
        if cat is None:
            cat = ViolationCategory(
                name=name,
                min_points=lo,
                max_points=hi,
                is_direct_expulsion=direct,
                description=f"Pelanggaran {name}.",
            )
            db.session.add(cat)
        created[name] = cat
    db.session.commit()
    return created


def make_violation_type(category, name, default_points, created_by):
    vt = ViolationType(
        category_id=category.id,
        name=name,
        default_points=default_points,
        is_active=True,
        created_by=created_by,
    )
    db.session.add(vt)
    db.session.commit()
    return vt


def make_document(
    uploaded_by,
    document_type="signed_amnesty_letter",
    file_name="scan.pdf",
    mime_type="application/pdf",
    file_size=1024,
):
    """Create a minimal Document row (partial T9/T11/T14 enabler).

    Amnesties require a NOT NULL signed_document_id (§2.12), so service &
    route tests need a Document to attach. Path/mime are not validated at
    the model level; real upload hardening lands in T17.
    """
    doc = Document(
        file_name=file_name,
        file_path=f"/tmp/sicapel-test/{file_name}",
        mime_type=mime_type,
        file_size=file_size,
        document_type=document_type,
        uploaded_by=uploaded_by,
    )
    db.session.add(doc)
    db.session.commit()
    return doc


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


@pytest.fixture
def violation_setup(app, guru_bk):
    """Full baseline for service tests: academic year, categories,
    violation types (one per category), a class, and a student.

    Returns a namespace with convenient attributes.
    """
    from types import SimpleNamespace

    ay = make_academic_year()
    cats = make_categories()

    vt_ringan = make_violation_type(cats["ringan"], "Terlambat", 25, guru_bk.id)
    vt_menengah = make_violation_type(cats["menengah"], "Gadget", 50, guru_bk.id)
    vt_berat = make_violation_type(cats["berat"], "Merokok", 60, guru_bk.id)
    vt_sangat = make_violation_type(
        cats["sangat_berat"], "Narkoba", 200, guru_bk.id
    )

    cls = make_class(guru_bk.id, "X IPA 1")
    student = make_student(cls.id, "1001")

    return SimpleNamespace(
        ay=ay,
        guru_bk=guru_bk,
        student=student,
        categories=cats,
        vt_ringan=vt_ringan,
        vt_menengah=vt_menengah,
        vt_berat=vt_berat,
        vt_sangat=vt_sangat,
    )


def login(client, email, password="password"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
