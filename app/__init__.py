"""Application factory.

    from app import create_app
    app = create_app()

Everything is wired here and nowhere else: config, database, template filters,
and the page blueprints.
"""

import os
import secrets
import stat

from flask import Flask

from app.config import Config
from app.extensions import csrf, db


def create_app(config_object=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)

    # instance/ holds the SQLite file and the signing key. Flask does not
    # create it for us.
    os.makedirs(app.instance_path, exist_ok=True)

    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = resolve_secret_key(app.instance_path)

    db.init_app(app)
    csrf.init_app(app)

    # Importing the models registers every table with SQLAlchemy. Without this
    # create_all() would produce an empty database.
    from app import models  # noqa: F401

    register_template_helpers(app)
    register_blueprints(app)

    # No migrations. This is a prototype -- the schema is created on startup
    # and the catalog is loaded by seed.py.
    with app.app_context():
        db.create_all()

    return app


def resolve_secret_key(instance_path):
    """The key Flask uses to sign session cookies and CSRF tokens.

    In order of preference:

    1. The FOCUS_SECRET_KEY environment variable, if you have set one.
    2. instance/secret_key -- generated once, on first run, and reused after
       that so restarting the app does not invalidate a form The Center Director already
       has open.

    It is never written into the source, because a key in a repository is not
    a secret. instance/ is in .gitignore.
    """
    from_env = os.environ.get("FOCUS_SECRET_KEY")
    if from_env:
        return from_env

    key_path = os.path.join(instance_path, "secret_key")

    if os.path.exists(key_path):
        with open(key_path, "r", encoding="utf-8") as handle:
            existing = handle.read().strip()
        if existing:
            return existing

    key = secrets.token_hex(32)
    with open(key_path, "w", encoding="utf-8") as handle:
        handle.write(key)

    # Readable and writable by this user only.
    os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)

    return key


def register_blueprints(app):
    from app.views.admin import admin_bp
    from app.views.batches import batches_bp
    from app.views.entry import entry_bp
    from app.views.home import home_bp
    from app.views.review import review_bp
    from app.views.totals import totals_bp

    app.register_blueprint(home_bp)
    app.register_blueprint(entry_bp)
    app.register_blueprint(batches_bp)
    app.register_blueprint(review_bp)
    app.register_blueprint(totals_bp)
    app.register_blueprint(admin_bp)


def register_template_helpers(app):
    """Formatting helpers available in every Jinja template."""

    from app.constants import (
        CONDITION_USED,
        bucket_label,
        category_label,
        category_short_label,
    )

    @app.template_filter("money")
    def money_filter(value):
        """1234.5 -> $1,234.50 ; None -> a dash, not $0.00."""
        if value is None:
            return "—"
        return "${:,.2f}".format(value)

    @app.template_filter("category_label")
    def category_label_filter(slug):
        return category_label(slug)

    @app.template_filter("category_short")
    def category_short_filter(slug):
        return category_short_label(slug)

    @app.template_filter("bucket_label")
    def bucket_label_filter(slug):
        return bucket_label(slug)

    @app.context_processor
    def inject_constants():
        from app.models import get_commit_mode

        return {
            "CONDITION_USED": CONDITION_USED,
            "commit_mode": get_commit_mode(),
        }
