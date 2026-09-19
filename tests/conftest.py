"""Shared test setup.

Every test gets a fresh in-memory database. `seeded_app` additionally loads the
real catalog CSV, so the tests are checking the actual data The Center Director will use
rather than made-up fixtures.
"""

import datetime

import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.services import seeding


@pytest.fixture
def app():
    """An empty app with empty tables."""
    application = create_app(TestConfig)
    with application.app_context():
        db.drop_all()
        db.create_all()
        yield application
        db.session.remove()


@pytest.fixture
def seeded_app(app):
    """The same app with the real 119-item catalog loaded."""
    seeding.seed_all(app.config["SEED_CSV_PATH"])
    return app


@pytest.fixture
def client(seeded_app):
    return seeded_app.test_client()


@pytest.fixture
def csv_path(app):
    return app.config["SEED_CSV_PATH"]


@pytest.fixture
def today():
    return datetime.date.today()
