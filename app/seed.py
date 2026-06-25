from datetime import date, timedelta
import random

import click

from . import db
from .helper import hash_password
from .models import (
    AcademicYear,
    Class,
    Document,
    Student,
    User,
    ViolationCategory,
    ViolationRecord,
    ViolationType,
)
from .services import apply_amnesty, recompute_summary, record_violation

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
@click.option(
    "--dev", is_flag=True, help="Seed comprehensive dev data (21 students, 3 classes, 4 teachers, violations, SP, amnesties)"
)
def seed_cli(admin_email, admin_password, year, dev):
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

    if dev:
        click.echo()
        _seed_dev_data(admin, ay)

    click.echo("Seed complete.")


# ---------------------------------------------------------------------------
# Dev seed (--dev flag)
# ---------------------------------------------------------------------------
_DEV_TEACHERS = [
    ("Susi Susanti, S.Pd.", "susi@sicapel.id", "guru_bk", "198001012005012001"),
    ("Budi Santoso, S.Pd.", "budi@sicapel.id", "wali_kelas", "198002012005012002"),
    ("Siti Nurhaliza, S.Pd.", "siti@sicapel.id", "wali_kelas", "198003012005012003"),
    ("Ahmad Rizki, S.Pd.", "ahmad@sicapel.id", "wali_kelas", "198004012005012004"),
]

_DEV_CLASSES = [
    ("X IPA 1", 10),
    ("XI IPA 1", 11),
    ("XII IPA 1", 12),
]

_DEV_STUDENTS = [
    # class X IPA 1
    ("2026001", "Adi Pratama", "L"),
    ("2026002", "Bella Sari", "P"),
    ("2026003", "Citra Dewi", "P"),
    ("2026004", "Dimas Arya", "L"),
    ("2026005", "Eka Putri", "P"),
    ("2026006", "Fajar Hidayat", "L"),
    ("2026007", "Gilang Permana", "L"),
    # class XI IPA 1
    ("2025001", "Hana Widya", "P"),
    ("2025002", "Indra Kurniawan", "L"),
    ("2025003", "Joko Susilo", "L"),
    ("2025004", "Kartika Sari", "P"),
    ("2025005", "Luki Pratama", "L"),
    ("2025006", "Mega Wati", "P"),
    ("2025007", "Nanda Puspita", "P"),
    # class XII IPA 1
    ("2024001", "Oscar Tampubolon", "L"),
    ("2024002", "Putri Ayu", "P"),
    ("2024003", "Rendra Malik", "L"),
    ("2024004", "Sari Dewanti", "P"),
    ("2024005", "Teguh Wibowo", "L"),
    ("2024006", "Umi Kalsum", "P"),
    ("2024007", "Vina Amalia", "P"),
]

# (student_nis, violation_type_name, points, chronology, location, days_ago, semester)
_DEV_VIOLATIONS = [
    ("2026001", "Terlambat masuk sekolah", 5, "Terlambat 15 menit", "Gerbang", 45, "1"),
    ("2026001", "Rambut tidak rapi", 5, "Rambut panjang", "Kelas", 40, "1"),
    ("2026001", "Merokok di lingkungan sekolah", 60, "Kedapatan merokok di toilet", "Toilet", 30, "1"),
    ("2026002", "Menggunakan gadget saat pelajaran", 30, "Main HP saat pelajaran biologi", "Kelas", 25, "1"),
    ("2026003", "Tidak mengikuti upacara tanpa alasan", 25, "Alfa upacara bendera", "Lapangan", 20, "1"),
    ("2026004", "Terlambat masuk sekolah", 5, "Terlambat 10 menit", "Gerbang", 35, "1"),
    ("2026004", "Membolos pelajaran", 50, "Bolos pelajaran matematika", "Kantin", 28, "1"),
    ("2026004", "Berkata kotor / tidak senopati", 30, "Berkata kasar ke teman", "Kelas", 18, "1"),
    ("2026005", "Terlambat masuk sekolah", 5, "Terlambat 5 menit", "Gerbang", 50, "1"),
    ("2026006", "Tidak memakai atribut lengkap", 10, "Tidak pakai dasi", "Upacara", 30, "1"),
    ("2026007", "Berkata kotor / tidak senopati", 30, "Berkata kotor", "Kelas", 22, "1"),
    ("2025001", "Menggunakan gadget saat pelajaran", 30, "Main HP", "Kelas", 20, "1"),
    ("2025001", "Tidak mengerjakan tugas", 10, "Tugas matematika tidak dikumpul", "Kelas", 12, "1"),
    ("2025002", "Terlambat masuk sekolah", 5, "Terlambat 20 menit", "Gerbang", 55, "1"),
    ("2025002", "Membolos pelajaran", 50, "Bolos pelajaran kimia", "Lapangan", 40, "1"),
    ("2025002", "Merokok di lingkungan sekolah", 60, "Merokok di toilet belakang", "Toilet", 35, "1"),
    ("2025003", "Rambut tidak rapi", 5, "Rambut tidak dipotong", "Kelas", 20, "1"),
    ("2025004", "Menggunakan gadget saat pelajaran", 30, "Main HP", "Kelas", 18, "1"),
    ("2025005", "Terlambat masuk sekolah", 5, "Terlambat 10 menit", "Gerbang", 15, "1"),
    ("2025006", "Tidak memakai atribut lengkap", 10, "Tidak pakai sepatu hitam", "Kelas", 10, "1"),
    ("2025007", "Tidak mengerjakan tugas", 10, "PR fisika tidak dikerjakan", "Kelas", 5, "1"),
    ("2024001", "Melawan / tidak menaati guru", 60, "Melawan guru BK", "Ruang BK", 30, "1"),
    ("2024002", "Tidak mengikuti upacara tanpa alasan", 25, "Alfa upacara", "Lapangan", 40, "1"),
    ("2024002", "Berkata kotor / tidak senopati", 30, "Kata-kata tidak sopan", "Kelas", 35, "1"),
    ("2024003", "Terlambat masuk sekolah", 5, "Terlambat 15 menit", "Gerbang", 20, "1"),
    ("2024004", "Menggunakan gadget saat pelajaran", 30, "Main HP", "Kelas", 25, "1"),
    ("2024007", "Tidak memakai atribut lengkap", 10, "Tidak pakai dasi", "Kelas", 15, "1"),
]

# (student_nis, points_reduced, reason_category, reason, sp_reset)
_DEV_AMNESTIES = [
    ("2026005", 5, "prestasi", "Juara 1 lomba matematika tingkat provinsi", False),
    ("2025006", 10, "prestasi", "Juara harapan lomba pidato bahasa Inggris", False),
    ("2024003", 10, "perilaku_baik", "Menjadi petugas upacara selama 1 semester", False),
    ("2025003", 5, "perilaku_baik", "Rajin piket kelas selama 2 bulan", True),
    ("2026006", 10, "kerja_bakti", "Gotong royong bersih-bersih lingkungan sekolah", False),
]


def _seed_dev_data(admin, ay):
    """Seed comprehensive dev data for development/testing."""
    click.echo("  Creating dev teachers...")
    teachers = []
    for name, email, role, nip in _DEV_TEACHERS:
        t = User.query.filter_by(email=email).first()
        if t is None:
            t = User(
                name=name,
                email=email,
                role=role,
                password_hash=hash_password("guru123"),
                nip=nip,
            )
            db.session.add(t)
            db.session.flush()
            click.echo(f"    Created: {name} ({role})")
        else:
            click.echo(f"    Skipped (exists): {name} ({role})")
        teachers.append(t)
    guru_bk = teachers[0]

    click.echo("  Creating dev classes...")
    classes = []
    for (name, grade_level), wt in zip(_DEV_CLASSES, teachers[1:]):
        c = Class.query.filter_by(name=name).first()
        if c is None:
            c = Class(
                name=name,
                grade_level=grade_level,
                homeroom_teacher_id=wt.id,
            )
            db.session.add(c)
            db.session.flush()
            click.echo(f"    Created: {name}")
        else:
            click.echo(f"    Skipped (exists): {name}")
        classes.append(c)

    # Assign 7 students per class
    click.echo("  Creating dev students...")
    students_by_nis = {}
    per_class = 7
    for idx, (nis, name, gender) in enumerate(_DEV_STUDENTS):
        class_idx = idx // per_class
        s = Student.query.filter_by(nis=nis).first()
        if s is None:
            s = Student(
                nis=nis,
                name=name,
                gender=gender,
                class_id=classes[class_idx].id,
                birth_place="Kota Fiktif",
                birth_date=date(2008, random.randint(1, 12), random.randint(1, 28)),
                status="active",
                enrolled_at=ay.start_date,
            )
            db.session.add(s)
            db.session.flush()
        students_by_nis[nis] = s
    click.echo(f"    Created/skipped {len(_DEV_STUDENTS)} students.")

    db.session.commit()
    click.echo("    [commit] Teachers, classes, students saved.")

    # Check if any student already has violations — if so, skip (idempotent).
    existing = ViolationRecord.query.first()
    if existing is not None:
        click.echo("    Violations already exist — skipping (idempotent).")
    else:
        click.echo("  Creating dev violations...")
        vtype_map = {vt.name: vt for vt in ViolationType.query.all()}
        missed = []
        counted = 0
        for nis, vt_name, points, chrono, loc, days_ago, sem in _DEV_VIOLATIONS:
            student = students_by_nis.get(nis)
            vt = vtype_map.get(vt_name)
            if student is None or vt is None:
                missed.append((nis, vt_name))
                continue
            incident = date.today() - timedelta(days=days_ago)
            result = record_violation(
                student_id=student.id,
                violation_type_id=vt.id,
                points=points,
                chronology=chrono,
                location=loc,
                incident_date=incident,
                incident_time=None,
                academic_year_id=ay.id,
                semester=sem,
                recorded_by=guru_bk.id,
                session=db.session,
            )
            if result.get("new_warning"):
                click.echo(
                    f"    → {result['new_warning'].level} issued for {student.name}"
                )
            if result.get("student_expelled"):
                click.echo(
                    f"    → EXPULSION issued for {student.name}"
                )
            counted += 1
        db.session.commit()
        click.echo(f"    {counted} violations recorded ({len(missed)} skipped due to missing refs).")

        # Create amnesties (with dummy documents for the signed scan)
        click.echo("  Creating dev amnesties...")
        for nis, pts, reason_cat, reason, sp_reset in _DEV_AMNESTIES:
            student = students_by_nis.get(nis)
            if student is None:
                continue
            dummy_doc = Document(
                file_name=f"amnesty_{nis}.pdf",
                file_path="/dev/null",
                mime_type="application/pdf",
                file_size=0,
                document_type="signed_amnesty_letter",
                uploaded_by=admin.id,
            )
            db.session.add(dummy_doc)
            db.session.flush()

            apply_amnesty(
                student_id=student.id,
                points_reduced=pts,
                sp_reset=sp_reset,
                reason=reason,
                reason_category=reason_cat,
                principal_name="Dr. H. Supardi, M.Pd.",
                issue_date=date.today(),
                academic_year_id=ay.id,
                recorded_by=guru_bk.id,
                signed_document_id=dummy_doc.id,
                session=db.session,
            )
            click.echo(
                f"    → {pts} pts amnesty for {student.name}"
                + (" (with SP reset)" if sp_reset else "")
            )
        db.session.commit()
        click.echo(f"    {len(_DEV_AMNESTIES)} amnesties applied.")

    # Ensure every student has a summary
    click.echo("  Finalizing student summaries...")
    for s in Student.query.all():
        recompute_summary(s.id, db.session)
    db.session.commit()
    click.echo("    All student summaries up to date.")
