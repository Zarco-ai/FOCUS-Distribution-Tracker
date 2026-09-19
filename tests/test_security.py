"""The security properties, written down as tests.

The rest of the suite runs with CSRF turned off so the tests can post forms
directly. These turn it back on and prove it actually works -- otherwise
Flask-WTF would be a dependency that quietly does nothing.

The later tests encode the manual review: no raw SQL, no disabled template
escaping, no key in the source, debugger off. They exist so that if someone
adds a `text()` query or a `|safe` filter in six months, a test fails instead
of nobody noticing.
"""

import os
import re
import pathlib
import stat

import pytest

from app import create_app, resolve_secret_key
from app.config import Config, TestConfig
from app.extensions import db
from app.services import seeding

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATES = PROJECT_ROOT / "app" / "templates"
SOURCE_DIRS = [PROJECT_ROOT / "app", PROJECT_ROOT / "seed.py", PROJECT_ROOT / "run.py"]


class CsrfConfig(TestConfig):
    """Like the test config, but with the protection switched back on."""

    WTF_CSRF_ENABLED = True


@pytest.fixture
def csrf_app():
    application = create_app(CsrfConfig)
    with application.app_context():
        db.drop_all()
        db.create_all()
        seeding.seed_all(application.config["SEED_CSV_PATH"])
        yield application
        db.session.remove()


@pytest.fixture
def csrf_client(csrf_app):
    return csrf_app.test_client()


def token_from(html):
    """Pull a CSRF token out of a rendered page."""
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "no CSRF token found on the page"
    return match.group(1)


# --- CSRF is really enforced ------------------------------------------------


def test_a_form_post_without_a_token_is_rejected(csrf_client):
    response = csrf_client.post("/batch/resume")
    assert response.status_code == 400


def test_a_form_post_with_a_token_is_accepted(csrf_client):
    page = csrf_client.get("/").get_data(as_text=True)
    response = csrf_client.post(
        "/batch/resume", data={"csrf_token": token_from(page)}
    )
    assert response.status_code == 302


def test_the_json_api_without_the_header_is_rejected(csrf_client):
    page = csrf_client.get("/").get_data(as_text=True)
    redirect = csrf_client.post(
        "/batch/resume", data={"csrf_token": token_from(page)}
    )
    batch_id = int(redirect.headers["Location"].rstrip("/").split("/")[-1])

    response = csrf_client.post(
        f"/api/batch/{batch_id}/line", json={"item_id": 1, "quantity": 1}
    )
    assert response.status_code == 400


def test_the_json_api_with_the_header_is_accepted(csrf_client):
    from app.services import catalog

    page = csrf_client.get("/").get_data(as_text=True)
    token = token_from(page)
    redirect = csrf_client.post("/batch/resume", data={"csrf_token": token})
    batch_id = int(redirect.headers["Location"].rstrip("/").split("/")[-1])

    coat = catalog.find_item("Coat", "clothing_adult")
    response = csrf_client.post(
        f"/api/batch/{batch_id}/line",
        json={"item_id": coat.id, "quantity": 1, "condition": "used"},
        headers={"X-CSRFToken": token},
    )

    assert response.status_code == 200
    assert response.get_json()["line"]["value"] == "45.00"


def test_a_stolen_token_from_another_session_does_not_work(csrf_app):
    """Roughly what a cross-site attempt looks like: a token that was not
    issued to this browser."""
    victim = csrf_app.test_client()
    attacker = csrf_app.test_client()

    stolen = token_from(attacker.get("/").get_data(as_text=True))
    response = victim.post("/batch/resume", data={"csrf_token": stolen})

    assert response.status_code == 400


def test_the_counting_screen_hands_the_token_to_the_javascript(csrf_client):
    page = csrf_client.get("/").get_data(as_text=True)
    redirect = csrf_client.post(
        "/batch/resume", data={"csrf_token": token_from(page)}
    )
    entry = csrf_client.get(redirect.headers["Location"]).get_data(as_text=True)

    assert "data-csrf-token=" in entry


# --- Every form carries a token ---------------------------------------------


def test_every_post_form_in_every_template_has_a_csrf_token():
    """A form added later without a token would fail at the worst moment --
    in front of The Center Director. This catches it here instead."""
    form_tag = re.compile(r"<form\b[^>]*>", re.IGNORECASE | re.DOTALL)
    missing = []

    for path in sorted(TEMPLATES.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        for match in form_tag.finditer(text):
            if 'method="post"' not in match.group(0).lower():
                continue
            # The token must appear before the form closes.
            rest = text[match.end():]
            body = rest[: rest.lower().find("</form>")]
            if 'name="csrf_token"' not in body:
                line = text[: match.start()].count("\n") + 1
                missing.append(f"{path.relative_to(PROJECT_ROOT)}:{line}")

    assert not missing, "POST forms with no CSRF token: " + ", ".join(missing)


# --- The manual review, as tests --------------------------------------------


def python_files():
    for target in SOURCE_DIRS:
        if target.is_file():
            yield target
        else:
            for path in target.rglob("*.py"):
                yield path


def test_no_raw_sql_anywhere():
    """SQLAlchemy's ORM parameterises for us. A raw text() query is where
    injection would live, so there should not be one."""
    offenders = []
    for path in python_files():
        source = path.read_text(encoding="utf-8")
        if re.search(r"\bfrom sqlalchemy import .*\btext\b", source) or re.search(
            r"\bsqlalchemy\.text\(", source
        ):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))
        if re.search(r"\.execute\(\s*[\"'f]", source):
            offenders.append(str(path.relative_to(PROJECT_ROOT)) + " (execute)")

    assert not offenders, "raw SQL found in: " + ", ".join(offenders)


def test_no_template_turns_off_escaping():
    """|safe, autoescape false and Markup all disable Jinja's escaping, which
    is what stops a stray note field turning into script."""
    offenders = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        source = path.read_text(encoding="utf-8")
        for pattern in (r"\|\s*safe\b", r"autoescape\s+false", r"\bMarkup\("):
            if re.search(pattern, source):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)} ({pattern})")

    assert not offenders, "escaping disabled in: " + ", ".join(offenders)


def test_user_supplied_text_is_escaped_on_the_page(client, seeded_app):
    """The proof rather than the promise: a note with markup in it comes back
    escaped, not as live HTML."""
    from app.extensions import db as database
    from app.models import ServiceType
    from app.services import batches

    batch = batches.open_batch(service_type_id=ServiceType.query.first().id)
    batches.add_custom_line(
        batch, name="<script>alert(1)</script>", quantity=1, note="<b>bold</b>"
    )
    database.session.commit()

    page = client.get(f"/batch/{batch.id}/review").get_data(as_text=True)

    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page
    assert "<b>bold</b>" not in page


def test_the_signing_key_is_not_written_in_the_source():
    """A key committed to a repository is not a secret."""
    assert Config.SECRET_KEY is None


def test_a_generated_key_is_reused_across_restarts(tmp_path):
    """Stable, so a form The Center Director already has open keeps working after the
    app is restarted."""
    first = resolve_secret_key(str(tmp_path))
    second = resolve_secret_key(str(tmp_path))

    assert len(first) >= 32
    assert first == second


def test_a_generated_key_is_different_on_a_different_machine(tmp_path):
    elsewhere = tmp_path / "another-install"
    elsewhere.mkdir()

    assert resolve_secret_key(str(tmp_path)) != resolve_secret_key(str(elsewhere))


def test_the_key_file_is_readable_only_by_this_user(tmp_path):
    resolve_secret_key(str(tmp_path))
    mode = os.stat(tmp_path / "secret_key").st_mode

    assert not mode & stat.S_IRGRP
    assert not mode & stat.S_IROTH


def test_the_environment_variable_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("FOCUS_SECRET_KEY", "from-the-environment")
    assert resolve_secret_key(str(tmp_path)) == "from-the-environment"
    assert not (tmp_path / "secret_key").exists()


def test_the_debugger_is_off_unless_asked_for():
    """Flask's debugger is a remote code execution console. It must never be
    on by default, and run.py refuses to expose it to the network."""
    source = (PROJECT_ROOT / "run.py").read_text(encoding="utf-8")

    assert "debug=True" not in source
    assert 'FLASK_DEBUG' in source
    assert "REFUSING TO START" in source


def test_the_app_does_not_enable_debug_itself():
    app = create_app(TestConfig)
    assert not app.debug
    assert not app.config.get("DEBUG")


def test_the_database_and_key_are_not_committed():
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "instance/" in gitignore
    assert ".venv" in gitignore
