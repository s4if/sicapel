import os

from flask import Flask, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user, logout_user
from flask_wtf import CSRFProtect
from flask_migrate import Migrate

from .helper import hx_render, htmx

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
migrate = Migrate()

login_manager.login_view = "auth.login"
login_manager.login_message = "Silakan login untuk mengakses halaman ini."
login_manager.login_message_category = "info"


@login_manager.user_loader
def load_user(user_id):
    from .models import User

    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    return db.session.get(User, uid)


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-me"),
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "DATABASE_URL",
            f"sqlite:///{os.path.join(app.instance_path, 'sicapel.sqlite')}",
        ),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        UPLOAD_FOLDER=os.environ.get(
            "UPLOAD_FOLDER", os.path.join(app.instance_path, "uploads")
        ),
        CACHE_DIR=os.path.join(app.instance_path, "cache"),
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,
    )
    for sub in ("uploads", "cache"):
        os.makedirs(os.path.join(app.instance_path, sub), exist_ok=True)
    app.config.from_pyfile("config.py", silent=True)
    if test_config:
        app.config.from_mapping(test_config)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    htmx.init_app(app)

    @app.before_request
    def _reject_deleted_users():
        # I5: a soft-deleted user loses access immediately, not at next login.
        # Re-validates is_deleted on every authenticated request and kills any
        # still-active session.
        if current_user.is_authenticated and getattr(
            current_user, "is_deleted", False
        ):
            logout_user()
            return hx_render("errors/403.html"), 403

    from .blueprints import (
        academic_years,
        amnesties,
        auth,
        classes,
        dashboard,
        expulsion,
        students,
        users,
        violation_types,
        violations,
        warnings,
    )

    for bp in (
        auth.bp,
        dashboard.bp,
        students.bp,
        classes.bp,
        violations.bp,
        warnings.bp,
        amnesties.bp,
        expulsion.bp,
        users.bp,
        violation_types.bp,
        academic_years.bp,
    ):
        app.register_blueprint(bp)

    @app.route("/")
    def index():
        return redirect(url_for("dashboard.index"))

    @app.route("/healthcheck")
    def healthcheck():
        return jsonify(status="ok"), 200

    @app.errorhandler(403)
    def forbidden(_e):
        return hx_render("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(_e):
        return hx_render("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(_e):
        return hx_render("errors/500.html"), 500

    from .seed import seed_cli

    app.cli.add_command(seed_cli)

    return app
