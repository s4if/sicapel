import functools
import html

import bcrypt
from flask import make_response, render_template, url_for, current_app
from flask_htmx import HTMX
from flask_login import current_user

htmx = HTMX()

_BCRYPT_MAX_BYTES = 72


def hash_password(password):
    return bcrypt.hashpw(
        password.encode("utf-8")[:_BCRYPT_MAX_BYTES], bcrypt.gensalt()
    ).decode("utf-8")


def verify_password(password, password_hash):
    return bcrypt.checkpw(
        password.encode("utf-8")[:_BCRYPT_MAX_BYTES],
        password_hash.encode("utf-8"),
    )


def sanitize(value):
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def hx_render(template, push_url=None, **kwargs):
    kwargs.setdefault(
        "current_user", current_user if current_user.is_authenticated else None
    )
    kwargs.setdefault("is_htmx", htmx)
    if push_url:
        resp = make_response(render_template(template, **kwargs))
        resp.headers["HX-Push-Url"] = (
            push_url
            if push_url.startswith(("/", "http"))
            else url_for(push_url)
        )
        return resp
    return render_template(template, **kwargs)


def role_required(*roles):
    def decorator(view):
        @functools.wraps(view)
        def wrapped(**kwargs):
            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()
            if current_user.role not in roles:
                return hx_render("errors/403.html"), 403
            return view(**kwargs)

        return wrapped

    return decorator


def class_owned_required(view):
    @functools.wraps(view)
    def wrapped(student_id, **kwargs):
        if current_user.role == "wali_kelas":
            from . import db
            from .models import Student

            s = db.get_or_404(Student, student_id)
            if s.class_.homeroom_teacher_id != current_user.id:
                return hx_render("errors/403.html"), 403
        return view(student_id=student_id, **kwargs)

    return wrapped


def current_academic_year():
    from .models import AcademicYear

    return AcademicYear.query.filter_by(is_active=True).first()
