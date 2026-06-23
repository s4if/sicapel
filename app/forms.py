from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired
from wtforms import (
    BooleanField,
    DateField,
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
    TimeField,
)
from wtforms.validators import DataRequired, Email, NumberRange, Optional

from .models import AMNESTY_REASON_CATEGORIES, SEMESTERS, STUDENT_STATUSES, USER_ROLES


class LoginForm(FlaskForm):
    email = StringField(
        "Email",
        validators=[DataRequired(), Email(check_deliverability=False)],
    )
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Login")


class StudentForm(FlaskForm):
    nis = StringField("NIS", validators=[DataRequired()])
    nisn = StringField("NISN", validators=[Optional()])
    name = StringField("Nama Lengkap", validators=[DataRequired()])
    gender = SelectField(
        "Jenis Kelamin",
        choices=[("L", "Laki-laki"), ("P", "Perempuan")],
        validators=[DataRequired()],
    )
    birth_place = StringField("Tempat Lahir", validators=[Optional()])
    birth_date = DateField("Tanggal Lahir", validators=[Optional()], format="%Y-%m-%d")
    address = TextAreaField("Alamat", validators=[Optional()])
    class_id = SelectField("Kelas", coerce=int, validators=[DataRequired()])
    parent_name = StringField("Nama Orang Tua", validators=[Optional()])
    parent_phone = StringField("No. Telepon Orang Tua", validators=[Optional()])
    status = SelectField(
        "Status",
        choices=[(s, s.capitalize()) for s in STUDENT_STATUSES],
        validators=[DataRequired()],
    )
    enrolled_at = DateField("Tanggal Masuk", validators=[Optional()], format="%Y-%m-%d")
    submit = SubmitField("Simpan")


class ClassForm(FlaskForm):
    name = StringField("Nama Kelas", validators=[DataRequired()])
    grade_level = SelectField(
        "Tingkat",
        choices=[(10, "Kelas 10"), (11, "Kelas 11"), (12, "Kelas 12")],
        coerce=int,
        validators=[DataRequired()],
    )
    homeroom_teacher_id = SelectField(
        "Wali Kelas", coerce=int, validators=[DataRequired()]
    )
    submit = SubmitField("Simpan")


class UserForm(FlaskForm):
    name = StringField("Nama Lengkap", validators=[DataRequired()])
    email = StringField("Email", validators=[DataRequired(), Email(check_deliverability=False)])
    password = PasswordField("Password", validators=[DataRequired()])
    role = SelectField(
        "Peran",
        choices=[(r, r.replace("_", " ").title()) for r in USER_ROLES],
        validators=[DataRequired()],
    )
    nip = StringField("NIP", validators=[Optional()])
    phone = StringField("No. Telepon", validators=[Optional()])
    submit = SubmitField("Simpan")


class UserEditForm(FlaskForm):
    name = StringField("Nama Lengkap", validators=[DataRequired()])
    email = StringField("Email", validators=[DataRequired(), Email(check_deliverability=False)])
    role = SelectField(
        "Peran",
        choices=[(r, r.replace("_", " ").title()) for r in USER_ROLES],
        validators=[DataRequired()],
    )
    nip = StringField("NIP", validators=[Optional()])
    phone = StringField("No. Telepon", validators=[Optional()])
    submit = SubmitField("Simpan")


class ViolationTypeForm(FlaskForm):
    category_id = SelectField("Kategori", coerce=int, validators=[DataRequired()])
    name = StringField("Nama Pelanggaran", validators=[DataRequired()])
    default_points = IntegerField(
        "Poin Default",
        validators=[DataRequired(), NumberRange(min=1)],
    )
    description = TextAreaField("Deskripsi", validators=[Optional()])
    is_active = BooleanField("Aktif", default=True)
    submit = SubmitField("Simpan")


class AcademicYearForm(FlaskForm):
    year = StringField("Tahun Ajaran", validators=[DataRequired()])
    start_date = DateField("Tanggal Mulai", validators=[DataRequired()], format="%Y-%m-%d")
    end_date = DateField("Tanggal Selesai", validators=[DataRequired()], format="%Y-%m-%d")
    is_active = BooleanField("Aktif (jadikan tahun ajaran berjalan)")
    submit = SubmitField("Simpan")


class ViolationRecordForm(FlaskForm):
    student_id = SelectField("Siswa", coerce=int, validators=[DataRequired()])
    violation_type_id = SelectField("Jenis Pelanggaran", coerce=int, validators=[DataRequired()])
    points = IntegerField("Poin", validators=[DataRequired(), NumberRange(min=1)])
    chronology = TextAreaField("Kronologi", validators=[Optional()])
    location = StringField("Lokasi", validators=[Optional()])
    incident_date = DateField("Tanggal Kejadian", validators=[DataRequired()], format="%Y-%m-%d")
    incident_time = TimeField("Jam Kejadian", validators=[Optional()], format="%H:%M")
    semester = SelectField(
        "Semester",
        choices=[(s, f"Semester {s}") for s in SEMESTERS],
        validators=[DataRequired()],
    )
    submit = SubmitField("Simpan")


class SignedScanUploadForm(FlaskForm):
    """Upload a signed-scan Document attached to a WarningLetter (T12).

    MIME is validated from content in ``app.uploads.save_upload`` (not via
    FileAllowed, which only checks extensions).
    """

    document_type = SelectField(
        "Jenis Dokumen",
        choices=[
            ("signed_warning_letter", "Scan Surat Peringatan (ditandatangani)"),
            ("signed_statement_letter", "Scan Pernyataan Siswa"),
        ],
        validators=[DataRequired()],
    )
    file = FileField("File", validators=[FileRequired(message="File wajib diunggah.")])
    submit = SubmitField("Unggah")


class PointAmnestyForm(FlaskForm):
    """Create a point amnesty (pemutihan) — T14 / §1.6.

    A signed scanned letter is mandatory (§2.12 ``signed_document_id`` NOT
    NULL) and is uploaded as ``file``; MIME is validated from content in
    ``app.uploads.save_upload``. ``sp_reset`` optionally clears the active SP
    level (historical ``warning_letters`` are never deleted).
    """

    student_id = SelectField("Siswa", coerce=int, validators=[DataRequired()])
    points_reduced = IntegerField(
        "Poin Dikurangi",
        validators=[DataRequired(), NumberRange(min=1)],
    )
    reason_category = SelectField(
        "Kategori Alasan",
        choices=[
            (c, {"prestasi": "Prestasi", "perilaku_baik": "Perilaku Baik",
                 "kerja_bakti": "Kerja Bakti", "lainnya": "Lainnya"}[c])
            for c in AMNESTY_REASON_CATEGORIES
        ],
        validators=[DataRequired()],
    )
    reason = TextAreaField("Alasan / Uraian", validators=[Optional()])
    sp_reset = BooleanField("Reset SP (kosongkan level SP aktif)")
    principal_name = StringField(
        "Nama Kepala Sekolah", validators=[DataRequired()]
    )
    issue_date = DateField(
        "Tanggal Surat", validators=[DataRequired()], format="%Y-%m-%d"
    )
    file = FileField(
        "Scan Surat Pemutihan (ditandatangani)",
        validators=[FileRequired(message="Scan surat pemutihan wajib diunggah.")],
    )
    submit = SubmitField("Simpan")
