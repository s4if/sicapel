from datetime import date

import click

from . import db
from .helper import hash_password
from .models import AcademicYear, User, ViolationCategory, ViolationType

_CATEGORIES = [
    {
        "name": "ringan",
        "min_points": 5,
        "max_points": 25,
        "is_direct_expulsion": False,
        "description": "Pelanggaran ringan.",
    },
    {
        "name": "menengah",
        "min_points": 25,
        "max_points": 50,
        "is_direct_expulsion": False,
        "description": "Pelanggaran menengah.",
    },
    {
        "name": "berat",
        "min_points": 51,
        "max_points": 75,
        "is_direct_expulsion": False,
        "description": "Pelanggaran berat.",
    },
    {
        "name": "sangat_berat",
        "min_points": 200,
        "max_points": 200,
        "is_direct_expulsion": True,
        "description": "Pelanggaran sangat berat - ekspulsi langsung.",
    },
]

_VIOLATION_TYPES = [
    ("Terlambat masuk sekolah", "ringan", 5),
    ("Tidak memakai atribut lengkap", "ringan", 10),
    ("Rambut tidak rapi", "ringan", 5),
    ("Tidak mengerjakan tugas", "ringan", 10),
    ("Menggunakan gadget saat pelajaran", "menengah", 30),
    ("Membolos pelajaran", "menengah", 50),
    ("Berkata kotor / tidak senopati", "menengah", 30),
    ("Tidak mengikuti upacara tanpa alasan", "menengah", 25),
    ("Merokok di lingkungan sekolah", "berat", 60),
    ("Tawuran", "berat", 75),
    ("Melawan / tidak menaati guru", "berat", 60),
    ("Penggunaan atau pengedaran narkoba", "sangat_berat", 200),
    ("Tindakan kriminal berat", "sangat_berat", 200),
]


def _seed_categories():
    created = 0
    updated = 0
    for spec in _CATEGORIES:
        cat = ViolationCategory.query.filter_by(name=spec["name"]).first()
        if cat is None:
            db.session.add(ViolationCategory(**spec))
            created += 1
        else:
            for key, value in spec.items():
                setattr(cat, key, value)
            updated += 1
    db.session.flush()
    return created, updated


def _seed_admin(email, password):
    admin = User.query.filter_by(email=email).first()
    if admin is None:
        admin = User(
            name="Administrator",
            email=email,
            role="admin",
            password_hash=hash_password(password),
        )
        db.session.add(admin)
        created = True
    else:
        created = False
    db.session.flush()
    return admin, created


def _seed_violation_types(admin):
    by_name = {c.name: c for c in ViolationCategory.query.all()}
    created = 0
    skipped = 0
    for name, cat_name, default_points in _VIOLATION_TYPES:
        cat = by_name.get(cat_name)
        if cat is None:
            continue
        if ViolationType.query.filter_by(name=name).first() is not None:
            skipped += 1
            continue
        db.session.add(
            ViolationType(
                category_id=cat.id,
                name=name,
                default_points=default_points,
                is_active=True,
                created_by=admin.id,
            )
        )
        created += 1
    db.session.flush()
    return created, skipped


def _seed_academic_year(year):
    start_year = int(year.split("/")[0])
    start = date(start_year, 7, 1)
    end = date(start_year + 1, 6, 30)
    AcademicYear.query.filter(AcademicYear.is_active.is_(True)).update(
        {"is_active": False}, synchronize_session=False
    )
    ay = AcademicYear.query.filter_by(year=year).first()
    if ay is None:
        ay = AcademicYear(
            year=year, start_date=start, end_date=end, is_active=True
        )
        db.session.add(ay)
        created = True
    else:
        ay.is_active = True
        ay.start_date = start
        ay.end_date = end
        created = False
    db.session.flush()
    return ay, created


@click.command("seed")
@click.option(
    "--admin-email", default="admin@sicapel.id", show_default=True
)
@click.option(
    "--admin-password", default="admin123", show_default=True
)
@click.option("--year", default="2026/2027", show_default=True)
def seed_cli(admin_email, admin_password, year):
    """Seed baseline master data (idempotent)."""
    click.echo("Seeding SICAPEL baseline data...")
    cat_created, cat_updated = _seed_categories()
    admin, admin_created = _seed_admin(admin_email, admin_password)
    vt_created, vt_skipped = _seed_violation_types(admin)
    ay, ay_created = _seed_academic_year(year)
    db.session.commit()

    click.echo(
        f"  violation_categories: {cat_created} created, {cat_updated} updated"
    )
    admin_status = "created" if admin_created else "already exists (left as-is)"
    click.echo(f"  admin ({admin_email}): {admin_status}")
    click.echo(
        f"  violation_types: {vt_created} created, {vt_skipped} already exist"
    )
    ay_status = "created & set active" if ay_created else "updated & set active"
    click.echo(f"  academic year {year}: {ay_status}")
    click.echo("Seed complete.")
