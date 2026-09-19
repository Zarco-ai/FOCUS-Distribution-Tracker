# FOCUS Distribution Tracker — handbook

A prototype for recording Gifts In Kind (GIK) as they go out the door, so the
monthly report for FOCUS North America and for donors can be produced from real
data instead of tally marks on paper.

Built for the Houston Center Director, who runs distribution days largely alone, standing up,
often holding a baby. Everything in here is shaped by that.

**This is a prototype, not production.** No authentication, no deployment, no
migrations. It runs on one laptop with a local SQLite file.

---

## Running it

You need Python 3.9 or newer.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python seed.py          # load the 119-item catalog
.venv/bin/python run.py           # start the app
```

Then open <http://127.0.0.1:5001>.

Port 5001 rather than Flask's usual 5000, because macOS uses 5000 for AirPlay
Receiver.

Environment variables, all optional:

| Variable | Default | What it does |
|---|---|---|
| `PORT` | `5001` | Which port to listen on |
| `HOST` | `0.0.0.0` | Which interface. Set `127.0.0.1` for this machine only |
| `FLASK_DEBUG` | off | Turns on Flask's debugger — **see below** |
| `FOCUS_SECRET_KEY` | generated | Signs session cookies and CSRF tokens |

**Debug mode is off by default and should stay that way.** Flask's debugger
lets anyone who can reach the app run arbitrary Python on this laptop through
the browser. Turning it on therefore also restricts the app to `127.0.0.1`, and
`run.py` refuses to start if you ask for both the debugger and a
network-reachable host.

If you do not set `FOCUS_SECRET_KEY`, a random one is generated on first run and
kept in `instance/secret_key`, which git ignores. Nothing secret lives in the
source.

### Using it from a phone

The app listens on all interfaces, so a phone on the same wifi can reach it.
Find your computer's IP (`ipconfig getifaddr en0` on a Mac) and open
`http://<that-ip>:5001` on the phone. This is worth doing before the demo —
it is the only way to find out whether the counting screen really works in
someone's hand.

### Running the tests

```bash
.venv/bin/python -m pytest
```

176 tests, about 10 seconds. They cover both used rates, the freezing of
committed values, the diaper/clothing separation, every form's validation, and
the security properties in `tests/test_security.py`.

See [SECURITY.md](SECURITY.md) for what has been checked, what was fixed, and
what is deliberately not done.

### Reseeding

```bash
.venv/bin/python seed.py           # add anything missing, leave existing alone
.venv/bin/python seed.py --reset   # wipe everything first (asks to confirm)
```

`seed.py` without `--reset` is safe to run any time. It matches items on
(name, category) and skips ones that already exist, so a price The Center Director has
corrected in the app is never overwritten by the CSV.

`--reset` deletes every batch that has been entered. It exists for development.

---

## The valuation rule

This is the thing to get right. Everything else is plumbing.

```
line_value = quantity × unit_price_new × (used_multiplier if condition == "used" else 1.0)
```

**The used multiplier is stored per item and is never hardcoded.** FOCUS values
used goods at half price in most categories and at three quarters for clothing:

| Category | Used rate |
|---|---|
| Baby essentials, women's hygiene, home goods, baby/mom items | 0.50 |
| All clothing (adult, children, infant) | 0.75 |

Both rates come out of the `used_multiplier` column in the seed CSV and live on
the `item` row. `app/services/valuation.py` contains no `0.5` and no `0.75`,
and `tests/test_valuation.py` has a test that changes a seeded rate to 0.9 and
asserts the answer follows it — that test fails the moment anyone hardcodes a
rate.

Checkable against The Center Director's own sheets:

| Item | New | Qty | Condition | Value |
|---|---|---|---|---|
| Coat · Adult | $60 | 1 | used | $45.00 |
| Blood Pressure Monitor | $75 | 1 | used | $37.50 |
| Swaddle · Infant | $5 | 1 | used | $3.75 |
| Pack 'N Play | $65 | 2 | used | $65.00 |

### Why committed numbers never move

Every line stores `unit_price_at_time` **and** `used_multiplier_at_time`. Once a
batch is approved those are frozen and nothing recomputes them from the catalog.
Change a price next year and last year's report still adds up to last year's
number.

While a batch is still a draft its lines do follow the catalog, because a draft
is still being written. The switch happens at approval.

---

## The screens

| Screen | What it is for |
|---|---|
| **Home** `/` | Start counting. Unfinished batches from earlier days are flagged here. |
| **Counting** `/batch/<id>` | The screen that matters. Categories collapse, search filters, `+`/`−` and a keypad set quantities, New/Used sets condition, values update live. |
| **Review** `/batch/<id>/review` | Every line, editable, with the batch total. Approve from here. |
| **Batch detail** `/batches/<id>` | An approved batch, read-only, with its correction history. |
| **Totals** `/totals` | Date-range totals by report bucket, plus CSV export. |
| **Review queue** `/review-queue` | Custom items waiting to be matched to real catalog entries, and to be given a real price. |
| **Items** `/admin/items` | Add, rename, deactivate, change a price, change a used rate. |
| **Needs a price** `/admin/needs-price` | Every manual-price item and the note explaining why. |
| **Settings** `/admin/settings` | Which of the three commit modes to use. |
| **Change history** `/admin/audit` | Every change to approved data and to the catalog. |

---

## The tables

| Table | What it holds |
|---|---|
| `service_type` | The kind of session a batch belongs to — Diaper Distribution, Walk-in, ESL Class, and so on. Seeded with nine. |
| `item` | One line of the catalog: name, category, report bucket, its own used rate, whether its price is trusted, and a note. **Unique on (name, category), not name.** |
| `item_price` | An item's new-condition price and the date it took effect. A separate table so changing a price adds a row instead of overwriting history. A NULL price is legal and means "we do not know yet". |
| `batch` | One distribution session: date, service type, note, draft or committed, and when it was approved. |
| `line_item` | One item at one quantity in one condition, with the price and rate it was valued at frozen on it. `item_id` is NULL for a custom item until the review queue resolves it. |
| `attendance` | Head counts for a session. **Counts only — there are no name fields here and there must never be any.** |
| `audit_log` | Every change to committed data and to the catalog: what table, what record, what field, from what, to what, when. |
| `app_setting` | One key/value row. Currently just which commit mode is in use. |

### A note on how money is stored

Dollar amounts are stored as **whole cents in an INTEGER column** and handed to
Python as `Decimal` dollars. Floats cannot hold `0.10` exactly, and a month of
donated goods added up in floats slowly drifts — a donor report is not a place
for drift.

The one consequence: if you open the database by hand you will see `4500`, not
`45.00`. That is $45.00 in cents. See `app/models/money.py`.

---

## Report buckets

`report_bucket` is the field that makes the monthly report possible. Every item
maps to exactly one bucket:

| Bucket | Feeds report column | In the seed CSV |
|---|---|---|
| `formula` | # of Baby Formula Containers | yes — 4 items |
| `food` | Value ($) of Food Distributed (GIK) | no — Center Director adds these |
| `diapers` | # and Value ($) of Individual Diapers | no — Center Director adds these |
| `clothing` | part of Clothing / Hygiene / Household | yes — 27 items |
| `hygiene` | part of Clothing / Hygiene / Household | yes — 30 items |
| `household` | part of Clothing / Hygiene / Household | yes — 58 items |

**Diapers, formula and food are reported in their own columns and never roll
into the combined goods column.** `app/services/totals.py` builds the combined
column by naming those three buckets explicitly, and
`tests/test_totals.py::test_diapers_do_not_roll_into_the_combined_goods_column`
proves a batch of diapers plus hygiene produces two totals that do not overlap.

### Adding diapers and food

There are none in the catalog, and diapers are the single most frequent item in
The Center Director's records. Adding them takes no code change and no schema change:

**Items → Add an item**, name `Diapers Size 3`, category `diapers`, report
bucket `diapers`, used rate `0.5`, price `0.25`. It appears on the counting
screen immediately and lands in the diapers column of the totals.

This is worth doing live in front of The Center Director at the demo. If she has to call
Christopher to add a diaper, the system has failed.

---

## Manual prices

Some source rows had a hole: no price, a range instead of a price, the same item
listed twice at different prices, or a used value that did not match the stated
rate. Those items are marked `price_entry = manual`.

There are **10 of them**, and they split into two kinds. Seven have no price at
all and show a red `price required` tag with an empty box. Three have a
trustworthy new price but a used value that does not follow the stated rate, so
they show an amber `confirm price` tag with the box pre-filled and editable:

| No price at all | Pre-filled, needs confirming |
|---|---|
| Baby Wash/Shampoo 2-in-1 | Small Rideable Toy Cars ($50) |
| Disposable Underwear | Big Rideable Toy Cars ($200) |
| Reusable Nursing Pads | Crib Wind Chime ($22) |
| Toys Large | |
| Toys Small | |
| Stroller | |
| Booster Seat 2-in-1 | |

How they behave:

- They appear in the normal list and use `+`/`−` and the keypad like anything else
- A price box appears on the row the moment the quantity goes above zero
- The `notes` column from the CSV is shown as help text next to the box
- **A batch cannot be approved while any manual line is missing a price**
- The typed price is stored on the line only. **The catalog is not modified.**
- The used multiplier still applies to the typed price
- **New and used carry separate prices.** A used stroller is not simply a
  fraction of whatever she typed for a new one, so each condition has its own
  box. The box says which one it belongs to.
- **The same item can be recorded twice at two different values.** "+ Add
  another at a different price" under the price box adds a second line for that
  item, with its own quantity and its own price — a $40 umbrella stroller and a
  $300 travel system in the same batch. Each extra line blocks approval until
  it is priced, exactly like the first, and the `×` removes it. Fixed-price
  items do not get this: their value comes from the catalog, so two of them are
  simply a quantity of two.

This applies only to catalog items marked `manual`. A **custom item** added
through "Add item not on this list" defaults its price to **0.00** instead, and
never blocks approval — see below.

The typed price staying on the line is deliberate. `/admin/needs-price` is the
list of items still needing a real value, and it shrinks only when The Center Director
supplies one through **Items → Edit → Set new price** and switches the item to
`fixed`.

---

## Custom items ("Add item not on this list")

Something arrives that is not in the catalog. She types a name, a quantity and
moves on — she is not going to stop and pick a report bucket while someone is
waiting.

**The price box defaults to 0.00 and is not optional.** She can type a real
value if she knows one, but leaving it at zero is a legitimate answer and the
batch approves either way. The alternative — making her invent a number before
she can finish — would be worse: invented numbers end up in a donor report.

The line is flagged `needs_review`, shows a marker everywhere it appears, keeps
the date of the batch it was entered in, and lands in `/review-queue`, where it
can be matched to a catalog item or turned into a new one and given a real
price. Until then it counts towards the item total and contributes $0.00 to the
value total, under its own "Not yet sorted" bucket rather than quietly joining
clothing/hygiene/household.

Resolving one deliberately refuses to reuse a zero price as if it were real: if
the item it is matched to has no catalog price either, it asks for one.

---

## Commit modes

We do not yet know whether the Center Director wants to approve after every mother, after
a batch of mothers, or not at all. All three work today, switchable at
`/admin/settings`:

| Mode | What happens |
|---|---|
| `per_batch` (default) | Count → Review → Approve → back to the home screen. |
| `per_mother` | Same, but approving opens a fresh empty batch straight away. |
| `auto` | No approval step. Counts save into today's batch as they are entered. |

In **every** mode, a manual-price line with no price and a batch with no service
type are held back rather than saved. "No committed line is ever missing a
price" is true in all three, and there is a test that checks all three.

The switch is one setting read in one place (`app/services/batches.py`), so
changing this after the demo is a small edit.

---

## Item names repeat across categories

`Pants`, `Coat`, `Socks`, `Shoes`, `Belt` and `Light Jacket` each exist in more
than one clothing category at different prices. **Uniqueness is
`(name, category)`, never name alone.**

There are three different `Pants`: adult $20, children $18, infant $7. An adult
coat is $60 and an infant coat is $15.

Every screen that shows an item shows its category too — the counting screen
(`Coat · Adult`), the review table, the batch detail page, the review queue
dropdown, and the CSV export. `Item.display_name` is the helper that does this;
use it rather than `item.name`.

---

## How the code is laid out

```
run.py                  start the app
seed.py                 load the catalog CSV
requirements.txt
(C) FOCUS Item Catalog Seed.csv

app/
  __init__.py           the application factory — everything is wired here
  config.py             configuration (and the test configuration)
  constants.py          shared vocabulary: conditions, statuses, buckets, labels
  extensions.py         the SQLAlchemy object, alone so nothing imports in a circle

  models/               the tables, one file per group
    catalog.py            service_type, item, item_price
    batch.py              batch, line_item, attendance
    audit.py              audit_log
    setting.py            app_setting, and the commit mode helpers
    money.py              the cents-in-an-integer column type

  services/             all the thinking. No Flask, no request objects.
    valuation.py          the valuation rule. The most important file here.
    batches.py            opening, filling in, approving, correcting
    catalog.py            reading and managing items
    review.py             the review queue
    totals.py             adding up committed batches, and the CSV export
    audit.py              writing to the audit log
    seeding.py            reading the catalog CSV

  views/                one module per screen. Read the request, call a
    home.py               service, render a template. Nothing else.
    entry.py
    review.py
    batches.py
    totals.py
    admin.py

  templates/            Jinja, mirroring the views
  static/css/app.css    plain CSS, mobile first
  static/js/
    keypad.js             the numeric keypad, self-contained
    entry.js              the counting screen

tests/                  pytest
instance/focus.db       the database (created on first run, gitignored)
```

The rule: **services do the thinking, views do the plumbing.** If you find
yourself writing an `if` in a view about what something is worth, it belongs in
`app/services/`.

---

## What is deliberately not here

- **Authentication.** Nobody logs in. CSRF protection *is* in place despite
  that — see [SECURITY.md](SECURITY.md) for why it still matters here.
- **Any personal information about the people served.** No names, no client
  records, no "mother" table. Attendance is counts only. The two free-text
  fields that exist — a batch note and a custom item note — both say out loud
  not to write names in them. **This boundary is deliberate and should be held.**
- Deployment, Docker, CI.
- The full monthly report table. `/totals` is the simple version; the real one
  needs The Center Director's exact columns.
- Anything AI-powered.
- Donor-facing views.

---

## Known limitations, and questions for The Center Director

Things worth raising at the demo:

1. **Same item, both conditions.** A batch can hold 3 new Bottles and 2 used
   Bottles as two separate lines, each with its own price. On the counting
   screen the New/Used toggle switches which side the row is showing, and a
   chip underneath reads "also 2 used · $7.00" so nothing hides behind the
   toggle — tapping the chip flips to that side.
2. **The catalog CSV has 119 items, not the 120 the brief estimated.** The
   seeder tests count the rows in the file rather than hardcoding a number, so
   this stays correct if the CSV is edited.
3. **10 items still need a real price.** `/admin/needs-price` is the agenda for
   another conversation, with the source note for each one.
4. **`Evenflo Exersaucer Activity Center` and `Spectra Breast Pump` are filed
   under Women's Hygiene** in the source sheet, which is almost certainly a
   miscategorisation. Their notes say so. The Center Director can recategorise them
   herself in Items.
5. **`Baby Lotion or Shampoo (3.4oz)` overlaps** with the separate Baby Shampoo
   and Baby Lotion rows — confirm it is the travel size.
6. **Dollar values are visible during entry.** The Center Director may not want amounts on
   screen while a mother is standing there. If she says so, the fix is small:
   the entry template already computes the values, so hiding them is a CSS class
   and a setting.
7. **Drafts are never auto-deleted.** One from an earlier day gets an
   "Unfinished" banner on the home screen with Resume and Discard. Discard asks
   to confirm.
8. **The item list starts fully collapsed.** Sections holding counted items open
   themselves and stay open, and searching opens whatever it finds. Whether
   collapsed-by-default is right is a real question to watch her answer with her
   hands rather than her words.
