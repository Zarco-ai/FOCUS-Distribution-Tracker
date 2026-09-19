"""Application configuration.

There is no deployment here on purpose -- this is a local prototype. The one
thing that genuinely matters is SECRET_KEY, which Flask uses to sign the
session cookie and the CSRF tokens. It is deliberately NOT written in this
file: a key committed to a repository is not a secret.

See resolve_secret_key() in app/__init__.py for where it actually comes from.
"""

import os


class Config:
    # Filled in at startup from FOCUS_SECRET_KEY, or from a key generated once
    # and kept in instance/secret_key (which git ignores).
    SECRET_KEY = None

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # instance/focus.db -- Flask fills in the instance folder path for us.
    SQLALCHEMY_DATABASE_URI = "sqlite:///focus.db"

    # CSRF tokens do not expire. The Center Director may leave a batch open on the
    # counting screen for a whole distribution day, and having the form die
    # underneath her after an hour would be worse than the risk it prevents.
    WTF_CSRF_TIME_LIMIT = None

    # Where seed.py reads the catalog from.
    SEED_CSV_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "(C) FOCUS Item Catalog Seed.csv",
    )


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"  # in-memory, thrown away each test

    # Fixed so tests are repeatable, and so the test run never writes a key
    # file. This value is never used by the real app.
    SECRET_KEY = "testing-only-not-a-real-key"  # nosec B105

    # Off by default so the existing tests can post forms directly. The tests
    # that specifically prove CSRF works turn it back on -- see
    # tests/test_security.py.
    WTF_CSRF_ENABLED = False
