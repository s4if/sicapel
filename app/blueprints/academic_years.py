from flask import Blueprint, jsonify, request
from flask_login import login_required

from ..forms import AcademicYearForm, RolloverForm
from ..helper import current_academic_year, hx_render, role_required, sanitize
from ..models import AcademicYear, Class, ClassEnrollment, User
from ..services import promote_academic_year

bp = Blueprint("academic_years", __name__, url_prefix="/tahun-ajaran")

_LABEL = "Tahun ajaran"

# The school runs a fixed 10/11/12 grade ladder (ClassForm choices); grade 12
# graduates on rollover (CLASSES_MODIFICATION §4.2).
_GRADUATE_GRADE = 12


def _display(ay):
    return ay.year


def _related_counts(academic_year_id):
    from ..models import (
        ExpulsionRecommendation,
        PointAmnesty,
        ViolationRecord,
        WarningLetter,
    )

    return {
        "pelanggaran": ViolationRecord.query.filter_by(
            academic_year_id=academic_year_id
        ).count(),
        "surat peringatan": WarningLetter.query.filter_by(
            academic_year_id=academic_year_id
        ).count(),
        "rekomendasi ekspulsi": ExpulsionRecommendation.query.filter_by(
            academic_year_id=academic_year_id
        ).count(),
        "pemutihan": PointAmnesty.query.filter_by(
            academic_year_id=academic_year_id
        ).count(),
    }


def _row_actions(ay):
    nama = sanitize(_display(ay))
    if getattr(ay, "is_deleted", False):
        restore_url = f"{ay.id}/restore"
        return (
            f'<div class="btn-group btn-group-sm">'
            f'<button class="btn btn-outline-success" type="button" '
            f'onclick="pulihkan_data(this)" '
            f'data-url="{restore_url}" data-nama="{nama}">'
            f'<i class="bi bi-arrow-counterclockwise"></i></button>'
            f"</div>"
        )

    edit_url = f"{ay.id}/edit"
    delete_url = f"{ay.id}/delete"
    return (
        f'<div class="btn-group btn-group-sm">'
        f'<a class="btn btn-outline-primary" href="{edit_url}" '
        f'hx-get="{edit_url}" hx-target="#hx_content" hx-swap="innerHTML">'
        f'<i class="bi bi-pencil"></i></a>'
        f'<button class="btn btn-outline-danger" type="button" '
        f'onclick="hapus_data(this)" '
        f'data-url="{delete_url}" data-nama="{nama}">'
        f'<i class="bi bi-trash"></i></button>'
        f"</div>"
    )


@bp.route("/")
@login_required
@role_required("admin")
def index():
    return hx_render("academic_years/index.html")


@bp.route("/data")
@login_required
@role_required("admin")
def data():
    rows = []
    for i, ay in enumerate(
        AcademicYear.query.order_by(AcademicYear.start_date.desc()).all(), 1
    ):
        rows.append(
            {
                "no": i,
                "year": sanitize(ay.year),
                "start_date": ay.start_date.isoformat() if ay.start_date else "-",
                "end_date": ay.end_date.isoformat() if ay.end_date else "-",
                "is_active": "Aktif" if ay.is_active else "Tidak",
                "is_deleted": ay.is_deleted,
                "actions": _row_actions(ay),
            }
        )
    return jsonify(data=rows)


@bp.route("/tambah", methods=["GET", "POST"])
@login_required
@role_required("admin")
def tambah():
    form = AcademicYearForm()

    if request.method == "GET":
        return hx_render("academic_years/form.html", form=form, academic_year=None)

    if not form.validate_on_submit():
        return hx_render(
            "academic_years/form.html", form=form, academic_year=None
        )

    from .. import db

    if form.is_active.data:
        AcademicYear.query.filter(AcademicYear.is_active.is_(True)).update(
            {"is_active": False}, synchronize_session=False
        )

    ay = AcademicYear(
        year=form.year.data,
        start_date=form.start_date.data,
        end_date=form.end_date.data,
        is_active=form.is_active.data,
    )
    db.session.add(ay)
    db.session.commit()

    return hx_render(
        "academic_years/index.html",
        push_url="academic_years.index",
        success=f"Tahun ajaran {ay.year} berhasil ditambahkan.",
    )


@bp.route("/<int:id>/edit", methods=["GET", "POST"])
@login_required
@role_required("admin")
def edit(id):
    from .. import db

    ay = db.get_or_404(AcademicYear, id)
    form = AcademicYearForm(obj=ay)

    if request.method == "GET":
        return hx_render("academic_years/form.html", form=form, academic_year=ay)

    if not form.validate_on_submit():
        return hx_render(
            "academic_years/form.html", form=form, academic_year=ay
        )

    if form.is_active.data and not ay.is_active:
        AcademicYear.query.filter(AcademicYear.is_active.is_(True)).update(
            {"is_active": False}, synchronize_session=False
        )

    ay.year = form.year.data
    ay.start_date = form.start_date.data
    ay.end_date = form.end_date.data
    ay.is_active = form.is_active.data
    db.session.commit()

    return hx_render(
        "academic_years/index.html",
        push_url="academic_years.index",
        success=f"Tahun ajaran {ay.year} berhasil diperbarui.",
    )


@bp.route("/<int:id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete(id):
    from .. import db

    ay = db.get_or_404(AcademicYear, id)

    # I3: the currently-active academic year cannot be deleted.
    if ay.is_active:
        return hx_render(
            "academic_years/index.html",
            error="Tahun ajaran aktif tidak dapat dihapus.",
        )

    if ay.is_deleted:
        return hx_render(
            "academic_years/index.html", error="Data sudah dihapus sebelumnya."
        )

    display = _display(ay)
    related = _related_counts(ay.id)
    related_count = sum(related.values())

    if related_count == 0:
        db.session.delete(ay)
        db.session.commit()
        return hx_render(
            "academic_years/index.html",
            push_url="academic_years.index",
            success=f"{_LABEL} {display} berhasil dihapus secara permanen.",
        )

    ay.is_deleted = True
    db.session.commit()
    detail = ", ".join(f"{k}: {v}" for k, v in related.items() if v > 0)
    return hx_render(
        "academic_years/index.html",
        push_url="academic_years.index",
        success=f"{_LABEL} {display} ditandai sebagai dihapus ({detail}).",
    )


@bp.route("/<int:id>/restore", methods=["POST"])
@login_required
@role_required("admin")
def restore(id):
    from .. import db

    ay = db.get_or_404(AcademicYear, id)
    if not ay.is_deleted:
        return hx_render("academic_years/index.html", error="Data belum dihapus.")

    # I1: is_deleted is independent of is_active; restoring does NOT flip
    # is_active, so it can never create a second active year.
    ay.is_deleted = False
    db.session.commit()
    return hx_render(
        "academic_years/index.html",
        push_url="academic_years.index",
        success=f"{_LABEL} {_display(ay)} berhasil dipulihkan.",
    )


# ---------------------------------------------------------------------------
# Rollover — start a new academic year (CLASSES_MODIFICATION §7 / D-C2)
# ---------------------------------------------------------------------------
def _teacher_choices():
    return [
        (u.id, u.name)
        for u in User.query.filter(
            User.role == "wali_kelas", User.is_deleted.is_(False)
        )
        .order_by(User.name)
        .all()
    ]


def _default_target_class(source_cls, all_classes):
    """Default target = the next-grade class sharing the same name suffix
    (e.g. ``X IPA 1`` → ``XI IPA 1``). None if no match (admin picks)."""
    target_grade = source_cls.grade_level + 1
    parts = source_cls.name.split(" ", 1)
    suffix = parts[1] if len(parts) > 1 else ""
    for c in all_classes:
        if c.grade_level != target_grade:
            continue
        tparts = c.name.split(" ", 1)
        if len(tparts) > 1 and tparts[1] == suffix:
            return c
    return None


def _source_classes(source_year_id):
    """Classes that have an active enrollment in the source year, ordered."""
    from .. import db
    from sqlalchemy import distinct

    source_class_ids = [
        row[0]
        for row in db.session.query(distinct(ClassEnrollment.class_id))
        .filter(
            ClassEnrollment.academic_year_id == source_year_id,
            ClassEnrollment.is_active.is_(True),
        )
        .all()
    ]
    if not source_class_ids:
        return []
    return (
        Class.query.filter(
            Class.id.in_(source_class_ids), Class.is_deleted.is_(False)
        )
        .order_by(Class.grade_level, Class.name)
        .all()
    )


def _build_rows(source_year_id):
    """One mapping row per source class, with a defaulted target (§7)."""
    all_classes = (
        Class.query.filter(Class.is_deleted.is_(False))
        .order_by(Class.grade_level, Class.name)
        .all()
    )
    teachers = _teacher_choices()
    rows = []
    for c in _source_classes(source_year_id):
        is_graduating = c.grade_level == _GRADUATE_GRADE
        default = None if is_graduating else _default_target_class(c, all_classes)
        rows.append(
            {
                "source_class": c,
                "is_graduating": is_graduating,
                "default_target_id": default.id if default else None,
            }
        )
    return rows, all_classes, teachers


def _target_candidates(source_year_id):
    """Eligible target years: existing, not active, not deleted, no
    enrollments yet (idempotency-friendly)."""
    from .. import db
    from sqlalchemy import func

    years = (
        AcademicYear.query.filter(
            AcademicYear.is_active.is_(False),
            AcademicYear.is_deleted.is_(False),
            AcademicYear.id != source_year_id,
        )
        .order_by(AcademicYear.start_date.desc())
        .all()
    )
    candidates = []
    for ay in years:
        count = (
            db.session.query(func.count(ClassEnrollment.id))
            .filter(ClassEnrollment.academic_year_id == ay.id)
            .scalar()
            or 0
        )
        if count == 0:
            candidates.append(ay)
    return candidates


@bp.route("/rollover", methods=["GET", "POST"])
@login_required
@role_required("admin")
def rollover():
    from .. import db

    source = current_academic_year()
    if source is None:
        return hx_render(
            "academic_years/rollover.html",
            error="Belum ada tahun ajaran aktif.",
        )

    rows, all_classes, teachers = _build_rows(source.id)
    candidates = _target_candidates(source.id)

    form = RolloverForm()
    form.target_year_id.choices = [(ay.id, ay.year) for ay in candidates]

    context = {
        "form": form,
        "source": source,
        "rows": rows,
        "all_classes": all_classes,
        "teachers": teachers,
        "graduate_grade": _GRADUATE_GRADE,
        "candidates": candidates,
    }

    if request.method == "GET":
        return hx_render("academic_years/rollover.html", **context)

    # --- POST: validate + commit. ---
    if not candidates:
        context["error"] = "Tidak ada tahun ajaran tujuan yang tersedia."
        return hx_render("academic_years/rollover.html", **context)

    if not form.validate_on_submit():
        return hx_render("academic_years/rollover.html", **context)

    # Build the class_map from the submitted per-row selects; graduating
    # rows are excluded (they have no target).
    class_map = {}
    missing = []
    for row in rows:
        c = row["source_class"]
        if c.grade_level == _GRADUATE_GRADE:
            continue
        tgt = request.form.get(f"target-{c.id}", type=int)
        teacher = request.form.get(f"teacher-{c.id}", type=int)
        if not tgt or not teacher:
            missing.append(c.name)
        else:
            class_map[c.id] = (tgt, teacher)

    if missing:
        context["error"] = (
            "Baris berikut belum punya kelas tujuan / wali kelas: "
            + ", ".join(missing)
            + "."
        )
        return hx_render("academic_years/rollover.html", **context)

    try:
        result = promote_academic_year(
            source_year_id=source.id,
            target_year_id=form.target_year_id.data,
            class_map=class_map,
            session=db.session,
        )
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        context["error"] = str(exc)
        return hx_render("academic_years/rollover.html", **context)

    target_year = db.get_or_404(AcademicYear, form.target_year_id.data)
    return hx_render(
        "academic_years/rollover.html",
        form=form,
        source=db.session.get(AcademicYear, source.id),
        target=target_year,
        rows=rows,
        all_classes=all_classes,
        teachers=teachers,
        graduate_grade=_GRADUATE_GRADE,
        candidates=candidates,
        result=result,
        success=(
            f"Rollover selesai. Lulus: {len(result['graduated'])}, "
            f"Naik kelas: {len(result['promoted'])}, "
            f"Dilewati: {len(result['skipped'])}."
        ),
    )
