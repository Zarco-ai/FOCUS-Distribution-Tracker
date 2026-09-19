# FOCUS Distribution Tracker

Recording donated goods as they go out the door at FOCUS Houston, so the
monthly Gifts In Kind report for FOCUS North America can be built from real
data instead of tally marks on paper.

One director runs distribution days largely alone — standing up, often holding
a baby. Every decision in here is shaped by that.

> **Prototype.** Local SQLite, no deployment, no authentication. Built unpaid
> as a first client engagement.

---

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python seed.py      # load the 119-item catalog
.venv/bin/python run.py       # http://127.0.0.1:5001
```

Tests: `.venv/bin/python -m pytest` — 176 tests, about 10 seconds.

The app listens on your network so it can be used from a phone on the same
wifi, which is the only honest way to test it. Flask's debugger is off by
default and `run.py` refuses to expose it.

## What it does

- **Counting screen built for a phone** — collapsible categories, search,
  `+`/`−`, a custom numeric keypad for "120 diapers", New/Used per row, and a
  running total that updates as you go.
- **Valuation that matches their sheets.** Used goods are worth a fraction of
  new, and FOCUS uses two different rates — 0.50 for goods, 0.75 for clothing.
  Each item carries its own rate; nothing is hardcoded.
- **History that stays put.** A committed line freezes the price and rate it
  was valued at, so changing the catalog never moves a report already filed.
- **Reporting buckets** that keep diapers, formula and food in their own
  columns, never rolled into clothing/hygiene/household.
- **Item management in the UI.** Adding a diaper size takes thirty seconds and
  no developer.

**It stores no personal information about the people it serves.** No name
fields anywhere; attendance is counts only. That is deliberate and load-bearing.

## Built with

Python 3 · Flask · SQLAlchemy · SQLite · server-rendered Jinja · vanilla
JavaScript · plain CSS · pytest. No build step, no framework, no deployment.

## More

| | |
|---|---|
| [HANDBOOK.md](HANDBOOK.md) | How it works, every table, the valuation rule, open questions |
| [SECURITY.md](SECURITY.md) | What was checked, what was fixed, what deliberately was not |

## License

The code is MIT licensed — see [LICENSE](LICENSE).

`(C) FOCUS Item Catalog Seed.csv` is FOCUS Houston's own data, included so the
app can be seeded and run. It is not covered by the MIT grant.
