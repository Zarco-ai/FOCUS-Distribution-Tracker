# Security

**Last reviewed: 17 September 2026**

This is a **prototype**, built unpaid as a first client engagement, and it is
honest about what that means. It runs on one laptop, stores data in a local
SQLite file, and is not deployed anywhere. There has been **no third-party
security review** — everything below was done by the developer with automated
tooling and a manual pass.

If this ever becomes something FOCUS Houston relies on day to day, the
"Deliberately not done" section is the work that has to happen first.

---

## What was checked

| Area | How | Result |
|---|---|---|
| Python source | `bandit -r . -x ./.venv,./tests` | **Clean** — 0 issues |
| Dependencies | `pip-audit` and `pip-audit -r requirements.txt` | **Clean** — 0 known vulnerabilities |
| SQL injection | Manual grep + a test | No raw SQL exists |
| Template escaping | Manual grep + a test | Escaping never disabled |
| CSRF | Manual review | Was missing — **now fixed** |
| Debug mode | Manual review | Was on — **now fixed** |
| Secrets in git history | `git log` | **No history existed.** The repo was initialised after this review, so nothing was ever committed containing a secret |

Reproduce the scans:

```bash
.venv/bin/pip install bandit pip-audit
.venv/bin/bandit -r . -x ./.venv,./tests
.venv/bin/pip-audit
```

Install them into `.venv`, not system Python. `pip-audit` audits whichever
environment it runs in, so running the system copy tells you nothing about this
project.

The security properties are also asserted in `tests/test_security.py`, so a
regression fails the suite rather than going unnoticed.

---

## What was found and fixed

### 1. Flask's debugger was on, and the app listened on every interface

**Was:** `app.run(host="0.0.0.0", port=port, debug=True)`

`debug=True` enables the Werkzeug interactive debugger. Anyone who can reach
the app and trigger an unhandled exception gets a browser console that executes
arbitrary Python **on the laptop running it**. Combined with `0.0.0.0`, that was
offered to everyone on the same wifi. At the FOCUS centre, on a shared network,
during a live demo where an exception is entirely plausible, that is a real
hole rather than a theoretical one.

**Now:** the debugger is off unless `FLASK_DEBUG=1` is set, and turning it on
also restricts the app to `127.0.0.1`. `run.py` refuses to start if you ask for
both the debugger and a network-reachable host.

Binding to `0.0.0.0` with the debugger off is retained deliberately — it is how
The Center Director reaches the app from her phone, which is the point of the prototype.
That is an accepted, documented risk on a trusted network, marked `# nosec B104`
in `run.py` with the reasoning next to it.

### 2. The signing key was hardcoded in the source

**Was:** `SECRET_KEY = "focus-houston-local-prototype"` in `app/config.py`.

A key committed to a repository is not a secret. It was low impact at the time
(no login, no sessions worth forging) but it signs CSRF tokens now, and it is
exactly the kind of thing that silently becomes serious later.

**Now:** `resolve_secret_key()` in `app/__init__.py` takes it from
`FOCUS_SECRET_KEY`, or generates a random 64-character key on first run and
stores it in `instance/secret_key` with owner-only permissions. `instance/` is
in `.gitignore`. Nothing secret is in the source tree.

### 3. No CSRF protection

**Was:** none. Flask does not do this by default.

The usual framing is that CSRF only matters once you have logins — an attacker
rides a session they cannot read. That reasoning does **not** hold here, and
that is worth understanding rather than repeating:

Because there is no authentication and the app listens on the network, *any*
web page The Center Director visits while the server is running could silently POST to
it. No session to steal, because none is needed. A malicious or merely
compromised page could discard a draft batch, approve one early, add junk
items, or change the commit mode — and she would have no idea why her numbers
were wrong.

**Now:** Flask-WTF's `CSRFProtect` is active globally. All 15 POST forms carry
a token, and the counting screen's `fetch()` calls send it as an `X-CSRFToken`
header. `tests/test_security.py` proves both that valid requests succeed and
that tokenless ones are rejected with 400, including a token issued to a
different session.

### 4. Dependency advisories

| Package | Advisory | Action |
|---|---|---|
| flask 3.1.0 | PYSEC-2026-1377 — fallback signing keys used in reverse order | Upgraded to **3.1.3** |
| flask 3.1.0 | PYSEC-2026-2151 — missing `Vary: Cookie` on some session access | Upgraded to **3.1.3** |
| pytest 8.3.4 | PYSEC-2026-1845 — predictable `/tmp/pytest-of-{user}` path | Upgraded to **9.0.3**; all 176 tests pass on it |

Neither Flask advisory was exploitable here (no fallback keys configured, no
cache in front of the app), and the pytest one is dev-only. All three were free
to fix, so they were fixed rather than argued with.

---

## What was checked and found already sound

**No raw SQL.** Every query goes through the SQLAlchemy ORM, which
parameterises. There is no `text()`, no string-built SQL, no `.execute()` on a
literal. `test_no_raw_sql_anywhere` fails if one appears.

**Template escaping is never disabled.** No `|safe`, no `{% autoescape false %}`,
no `Markup()`. Jinja escapes everything, which matters because item names and
notes are free text typed by a user. `test_no_template_turns_off_escaping` and
`test_user_supplied_text_is_escaped_on_the_page` cover it — the second actually
stores `<script>alert(1)</script>` as an item name and asserts it comes back
escaped.

**No secrets in git history.** There is no history to audit. The project was
never a repository before this review; the first commit was made afterwards,
with `instance/` already ignored.

**No personal data.** This is a design decision, not an accident, and it is the
strongest security property the system has: the biggest risk in software for a
nonprofit serving vulnerable people is leaking who they are. There is no name
field anywhere. Attendance is counts only. `test_the_attendance_table_has_no_name_column`
asserts the schema stays that way. The two free-text fields (a batch note and a
custom item note) both carry on-screen warnings not to type names into them —
that is a human control, not a technical one, and The Center Director needs to be told
about it directly.

---

## Deliberately not done

These are gaps, stated plainly, not oversights.

**No authentication.** Anyone who can reach the app can use it and change
anything. Acceptable because it runs on one laptop on a trusted network.
Required before any deployment, and it is the first thing that must be built if
this becomes a real system.

**No HTTPS.** Traffic between the phone and the laptop is plaintext over local
wifi. No credentials cross the wire, because there are none.

**No rate limiting, no lockout, no audit of who did what.** The audit log
records *what* changed, not *who* changed it, because there is no concept of a
user.

**Running on Flask's development server.** Werkzeug's built-in server is not
built for production use — it says so itself on startup. A real deployment needs
a WSGI server behind a reverse proxy.

**No dependency pinning beyond direct requirements.** `requirements.txt` pins
direct dependencies only; transitive ones float. A production build wants a
lockfile.

**No automated security scanning in CI.** There is no CI. The scans above are
run by hand, and the date at the top of this file is when that last happened.

**No third-party review.** Nobody but the developer has looked at this.

---

## If you deploy this

In rough priority order:

1. Add authentication, and put a real user behind the audit log.
2. Serve it over HTTPS with a real WSGI server, never `run.py`.
3. Set `FOCUS_SECRET_KEY` from the deployment environment.
4. Confirm `FLASK_DEBUG` is unset, and check the startup banner says
   `Debug mode: off`.
5. Move off SQLite if more than one person will ever write at once.
6. Re-run `bandit` and `pip-audit`, and put both in CI.
7. Get someone who is not the author to review it.

## Reporting a problem

This is a two-person project. Email Christopher, or open an issue on the
repository.
