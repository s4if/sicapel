from urllib.parse import urljoin, urlparse

from flask import Blueprint, redirect, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ..forms import LoginForm
from ..helper import hx_render, verify_password
from ..models import User

bp = Blueprint("auth", __name__, url_prefix="/auth")


def _is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return (
        test_url.scheme in ("http", "https")
        and ref_url.netloc == test_url.netloc
    )


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user is None or not verify_password(
            form.password.data, user.password_hash
        ):
            return hx_render(
                "auth/login.html", form=form, error="Email atau password salah."
            )
        login_user(user)
        target = request.args.get("next")
        if not target or not _is_safe_url(target):
            target = url_for("dashboard.index")
        return redirect(target)
    return hx_render("auth/login.html", form=form)


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
