from datetime import datetime, timezone

from flask_login import UserMixin

from . import db


def _now():
    return datetime.now(timezone.utc)


USER_ROLES = ("admin", "guru_bk", "wali_kelas")
GENDERS = ("L", "P")
STUDENT_STATUSES = ("active", "expelled", "graduated", "transferred")
VIOLATION_CATEGORY_NAMES = ("ringan", "menengah", "berat", "sangat_berat")
SEMESTERS = ("1", "2")
DOCUMENT_TYPES = (
    "evidence_photo",
    "evidence_video",
    "signed_warning_letter",
    "signed_statement_letter",
    "signed_amnesty_letter",
)
WARNING_LETTER_LEVELS = ("SP1", "SP2", "SP3")
WARNING_LETTER_STATUSES = ("issued", "signed_returned", "void")
EXPULSION_STATUSES = ("issued", "void")
SP_LEVELS = ("1", "2", "3")
AMNESTY_REASON_CATEGORIES = ("prestasi", "perilaku_baik", "kerja_bakti", "lainnya")
AMNESTY_STATUSES = ("issued", "void")


def _enum(values, name):
    return db.Enum(*values, name=name, native_enum=True, create_constraint=True)


class AcademicYear(db.Model):
    __tablename__ = "academic_years"

    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.String(20), nullable=False, unique=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=False)
    is_deleted = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(_enum(USER_ROLES, "user_role"), nullable=False)
    nip = db.Column(db.String(40))
    phone = db.Column(db.String(40))
    is_deleted = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class Class(db.Model):
    __tablename__ = "classes"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False)
    grade_level = db.Column(db.Integer, nullable=False)
    homeroom_teacher_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    is_deleted = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    homeroom_teacher = db.relationship("User")


class Student(db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    nis = db.Column(db.String(40), nullable=False, unique=True)
    nisn = db.Column(db.String(40))
    name = db.Column(db.String(120), nullable=False)
    gender = db.Column(_enum(GENDERS, "gender"), nullable=False)
    birth_place = db.Column(db.String(120))
    birth_date = db.Column(db.Date)
    address = db.Column(db.Text)
    photo_path = db.Column(db.String(255))
    class_id = db.Column(
        db.Integer, db.ForeignKey("classes.id"), nullable=False, index=True
    )
    parent_name = db.Column(db.String(120))
    parent_phone = db.Column(db.String(40))
    status = db.Column(
        _enum(STUDENT_STATUSES, "student_status"), nullable=False, default="active"
    )
    is_deleted = db.Column(db.Boolean, nullable=False, default=False)
    enrolled_at = db.Column(db.Date)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    class_ = db.relationship("Class")


class ViolationCategory(db.Model):
    __tablename__ = "violation_categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(
        _enum(VIOLATION_CATEGORY_NAMES, "violation_category_name"),
        nullable=False,
        unique=True,
    )
    min_points = db.Column(db.Integer, nullable=False)
    max_points = db.Column(db.Integer, nullable=False)
    is_direct_expulsion = db.Column(db.Boolean, nullable=False, default=False)
    description = db.Column(db.Text)


class ViolationType(db.Model):
    __tablename__ = "violation_types"

    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(
        db.Integer, db.ForeignKey("violation_categories.id"), nullable=False
    )
    name = db.Column(db.String(120), nullable=False)
    default_points = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_deleted = db.Column(db.Boolean, nullable=False, default=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    category = db.relationship("ViolationCategory")
    created_by_user = db.relationship("User")


class ViolationRecord(db.Model):
    __tablename__ = "violation_records"

    id = db.Column(db.Integer, primary_key=True)
    record_number = db.Column(db.String(60), nullable=False)
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id"), nullable=False, index=True
    )
    violation_type_id = db.Column(
        db.Integer, db.ForeignKey("violation_types.id"), nullable=False
    )
    category_id = db.Column(
        db.Integer,
        db.ForeignKey("violation_categories.id"),
        nullable=False,
        index=True,
    )
    points = db.Column(db.Integer, nullable=False)
    chronology = db.Column(db.Text)
    location = db.Column(db.String(255))
    incident_date = db.Column(db.Date, nullable=False)
    incident_time = db.Column(db.Time)
    academic_year_id = db.Column(
        db.Integer, db.ForeignKey("academic_years.id"), nullable=False, index=True
    )
    semester = db.Column(_enum(SEMESTERS, "semester"), nullable=False)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    is_void = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    __table_args__ = (db.Index("ix_violation_records_created_at", "created_at"),)

    student = db.relationship("Student")
    violation_type = db.relationship("ViolationType")
    category = db.relationship("ViolationCategory")
    academic_year = db.relationship("AcademicYear")
    recorded_by_user = db.relationship("User")


class WarningLetter(db.Model):
    __tablename__ = "warning_letters"

    id = db.Column(db.Integer, primary_key=True)
    letter_number = db.Column(db.String(60), nullable=False)
    letter_seq = db.Column(db.Integer, nullable=False)
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id"), nullable=False, index=True
    )
    level = db.Column(_enum(WARNING_LETTER_LEVELS, "warning_letter_level"), nullable=False)
    trigger_violation_record_id = db.Column(
        db.Integer, db.ForeignKey("violation_records.id"), nullable=False
    )
    total_points_at_issue = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.Text)
    issued_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    issue_date = db.Column(db.Date, nullable=False)
    academic_year_id = db.Column(
        db.Integer, db.ForeignKey("academic_years.id"), nullable=False
    )
    signed_warning_doc_id = db.Column(
        db.Integer, db.ForeignKey("documents.id", use_alter=True)
    )
    signed_statement_doc_id = db.Column(
        db.Integer, db.ForeignKey("documents.id", use_alter=True)
    )
    status = db.Column(
        _enum(WARNING_LETTER_STATUSES, "warning_letter_status"),
        nullable=False,
        default="issued",
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    __table_args__ = (
        db.UniqueConstraint(
            "academic_year_id", "letter_seq", name="uq_warning_letters_year_seq"
        ),
    )

    student = db.relationship("Student")
    trigger_violation_record = db.relationship("ViolationRecord")
    issued_by_user = db.relationship("User")
    academic_year = db.relationship("AcademicYear")
    signed_warning_doc = db.relationship(
        "Document", foreign_keys=[signed_warning_doc_id]
    )
    signed_statement_doc = db.relationship(
        "Document", foreign_keys=[signed_statement_doc_id]
    )


class ExpulsionRecommendation(db.Model):
    __tablename__ = "expulsion_recommendations"

    id = db.Column(db.Integer, primary_key=True)
    letter_number = db.Column(db.String(60), nullable=False)
    letter_seq = db.Column(db.Integer, nullable=False)
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id"), nullable=False, index=True
    )
    trigger_violation_record_id = db.Column(
        db.Integer, db.ForeignKey("violation_records.id")
    )
    trigger_warning_letter_id = db.Column(
        db.Integer, db.ForeignKey("warning_letters.id")
    )
    reason = db.Column(db.Text)
    total_points_at_issue = db.Column(db.Integer, nullable=False)
    issued_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    issue_date = db.Column(db.Date, nullable=False)
    academic_year_id = db.Column(
        db.Integer, db.ForeignKey("academic_years.id"), nullable=False
    )
    status = db.Column(
        _enum(EXPULSION_STATUSES, "expulsion_status"), nullable=False, default="issued"
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        db.UniqueConstraint(
            "academic_year_id", "letter_seq", name="uq_expulsion_year_seq"
        ),
    )

    student = db.relationship("Student")
    trigger_violation_record = db.relationship("ViolationRecord")
    trigger_warning_letter = db.relationship("WarningLetter")
    issued_by_user = db.relationship("User")
    academic_year = db.relationship("AcademicYear")


class Document(db.Model):
    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    violation_record_id = db.Column(db.Integer, db.ForeignKey("violation_records.id"))
    warning_letter_id = db.Column(db.Integer, db.ForeignKey("warning_letters.id", use_alter=True))
    file_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    mime_type = db.Column(db.String(120), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    document_type = db.Column(_enum(DOCUMENT_TYPES, "document_type"), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    violation_record = db.relationship("ViolationRecord")
    warning_letter = db.relationship("WarningLetter", foreign_keys=[warning_letter_id])
    uploaded_by_user = db.relationship("User")


class StudentPointSummary(db.Model):
    __tablename__ = "student_point_summaries"

    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id"), primary_key=True
    )
    total_points = db.Column(db.Integer, nullable=False, default=0, index=True)
    current_sp_level = db.Column(_enum(SP_LEVELS, "sp_level"), nullable=True)
    last_sp_date = db.Column(db.Date, nullable=True)
    is_expelled = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    student = db.relationship("Student")


class PointAmnesty(db.Model):
    __tablename__ = "point_amnesties"

    id = db.Column(db.Integer, primary_key=True)
    letter_number = db.Column(db.String(60), nullable=False)
    letter_seq = db.Column(db.Integer, nullable=False)
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id"), nullable=False, index=True
    )
    points_reduced = db.Column(db.Integer, nullable=False)
    reason_category = db.Column(
        _enum(AMNESTY_REASON_CATEGORIES, "amnesty_reason_category"), nullable=False
    )
    reason = db.Column(db.Text)
    sp_reset = db.Column(db.Boolean, nullable=False, default=False)
    principal_name = db.Column(db.String(120), nullable=False)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    issue_date = db.Column(db.Date, nullable=False)
    academic_year_id = db.Column(
        db.Integer, db.ForeignKey("academic_years.id"), nullable=False
    )
    signed_document_id = db.Column(
        db.Integer, db.ForeignKey("documents.id"), nullable=False
    )
    status = db.Column(
        _enum(AMNESTY_STATUSES, "amnesty_status"), nullable=False, default="issued"
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    __table_args__ = (
        db.UniqueConstraint(
            "academic_year_id", "letter_seq", name="uq_point_amnesties_year_seq"
        ),
    )

    student = db.relationship("Student")
    recorded_by_user = db.relationship("User")
    academic_year = db.relationship("AcademicYear")
    signed_document = db.relationship("Document")
