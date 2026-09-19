"""Loading the catalog from the seed CSV.

The CSV is The Center Director's spreadsheet, cleaned up. Its columns are:

    item_name, category, report_bucket, unit_price_new, used_multiplier,
    price_entry, notes

A blank unit_price_new is expected and normal -- several items in the source
sheet have no price at all, or a range instead of a price. Those come in as
price_entry=manual with no price, and The Center Director types a value at entry time.

seed.py at the project root is the command-line wrapper around this.
"""

import csv
import datetime

from app.constants import (
    PRICE_ENTRY_CHOICES,
    PRICE_ENTRY_FIXED,
    REPORT_BUCKETS,
)
from app.extensions import db
from app.models import Item, ServiceType

# The kinds of session a batch can belong to.
SERVICE_TYPES = [
    "Diaper Distribution",
    "Early Distribution",
    "ESL Class",
    "Nutrition Class",
    "Intake",
    "Walk-in",
    "Volunteer Help",
    "Bike Giveaway",
    "Transportation",
]

REQUIRED_COLUMNS = {
    "item_name",
    "category",
    "report_bucket",
    "unit_price_new",
    "used_multiplier",
    "price_entry",
    "notes",
}


class SeedError(Exception):
    """The CSV could not be read. The message says which row and why."""


def _clean(value):
    """Trim whitespace and turn an empty cell into None."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_price(value, row_number):
    """A price cell. Blank is allowed and means 'we do not know'."""
    value = _clean(value)
    if value is None:
        return None
    value = value.replace("$", "").replace(",", "")
    try:
        return float(value)
    except ValueError:
        raise SeedError(f"Row {row_number}: '{value}' is not a price.")


def _parse_multiplier(value, row_number):
    """The used rate. Required -- an item with no rate cannot be valued used."""
    value = _clean(value)
    if value is None:
        raise SeedError(f"Row {row_number}: used_multiplier is required.")
    try:
        multiplier = float(value)
    except ValueError:
        raise SeedError(f"Row {row_number}: '{value}' is not a used rate.")
    if not 0 < multiplier <= 1:
        raise SeedError(
            f"Row {row_number}: used rate {multiplier} is outside 0 to 1."
        )
    return multiplier


def read_catalog_csv(csv_path):
    """Read the CSV into a list of plain dicts. No database involved.

    Kept separate from the loading so a bad file fails before anything is
    written.
    """
    rows = []
    # utf-8-sig strips the byte order mark Excel likes to add.
    with open(csv_path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)

        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise SeedError(
                f"{csv_path} is missing columns: {', '.join(sorted(missing))}"
            )

        # Row 1 is the header, so data starts at row 2.
        for row_number, row in enumerate(reader, start=2):
            name = _clean(row["item_name"])
            if name is None:
                continue  # blank line at the end of the file

            category = _clean(row["category"])
            if category is None:
                raise SeedError(f"Row {row_number}: '{name}' has no category.")

            bucket = _clean(row["report_bucket"])
            if bucket not in REPORT_BUCKETS:
                raise SeedError(
                    f"Row {row_number}: '{name}' has report_bucket "
                    f"'{bucket}', which is not one of {', '.join(REPORT_BUCKETS)}."
                )

            price_entry = _clean(row["price_entry"]) or PRICE_ENTRY_FIXED
            if price_entry not in PRICE_ENTRY_CHOICES:
                raise SeedError(
                    f"Row {row_number}: '{name}' has price_entry "
                    f"'{price_entry}', expected fixed or manual."
                )

            rows.append(
                {
                    "row_number": row_number,
                    "name": name,
                    "category": category,
                    "report_bucket": bucket,
                    "unit_price_new": _parse_price(row["unit_price_new"], row_number),
                    "used_multiplier": _parse_multiplier(
                        row["used_multiplier"], row_number
                    ),
                    "price_entry": price_entry,
                    "note": _clean(row["notes"]),
                }
            )

    return rows


def seed_service_types():
    """Add any service type that is not already there. Never removes one."""
    added = 0
    for name in SERVICE_TYPES:
        existing = ServiceType.query.filter_by(name=name).one_or_none()
        if existing is None:
            db.session.add(ServiceType(name=name, active=True))
            added += 1
    db.session.flush()
    return added


def seed_catalog(csv_path, effective_from=None):
    """Load the catalog. Items are matched on (name, category).

    An item that already exists is left alone -- if The Center Director has corrected a
    price in the app, reseeding must not undo her work. Use reset_database()
    first if you want a clean slate.

    Returns a summary dict so the caller (and the tests) can report on it.
    """
    effective_from = effective_from or datetime.date.today()
    rows = read_catalog_csv(csv_path)

    summary = {
        "rows_read": len(rows),
        "items_added": 0,
        "items_skipped": 0,
        "prices_added": 0,
        "blank_prices": 0,
    }

    for row in rows:
        existing = Item.query.filter_by(
            name=row["name"], category=row["category"]
        ).one_or_none()

        if existing is not None:
            summary["items_skipped"] += 1
            continue

        item = Item(
            name=row["name"],
            category=row["category"],
            report_bucket=row["report_bucket"],
            used_multiplier=row["used_multiplier"],
            price_entry=row["price_entry"],
            note=row["note"],
            active=True,
        )
        db.session.add(item)

        # Every item gets a price row, even when the price is unknown. A row
        # with a NULL price records "as of this date we have no price", which
        # is different from having no history at all.
        item.set_price(row["unit_price_new"], effective_from=effective_from)
        summary["prices_added"] += 1
        if row["unit_price_new"] is None:
            summary["blank_prices"] += 1

        summary["items_added"] += 1

    db.session.flush()
    return summary


def reset_database():
    """Drop every table and recreate them empty."""
    db.drop_all()
    db.create_all()


def seed_all(csv_path, reset=False):
    """Everything: optional wipe, service types, then the catalog."""
    if reset:
        reset_database()

    service_types_added = seed_service_types()
    summary = seed_catalog(csv_path)
    summary["service_types_added"] = service_types_added

    db.session.commit()
    return summary
