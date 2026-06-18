import os

from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from flask_migrate import Migrate

from .helper import htmx

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
migrate = Migrate()


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

    @app.route("/healthcheck")
    def healthcheck():
        return jsonify(status="ok"), 200

    from .seed import seed_cli

    app.cli.add_command(seed_cli)

    return app
