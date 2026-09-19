"""Loading the catalog CSV.

The row count is read from the file rather than hardcoded, so these tests stay
true when Christopher edits the CSV. (For the record: the file shipped with
this project has 119 item rows, not the 120 the brief estimated.)
"""

import csv

import pytest

from app.models import Item, ItemPrice, ServiceType
from app.services import catalog, seeding


def rows_in_file(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return [row for row in csv.DictReader(handle) if row["item_name"].strip()]


def test_every_row_in_the_csv_becomes_an_item(app, csv_path):
    expected = len(rows_in_file(csv_path))

    summary = seeding.seed_all(csv_path)

    assert summary["rows_read"] == expected
    assert summary["items_added"] == expected
    assert Item.query.count() == expected


def test_blank_prices_load_as_no_price_rather_than_zero(app, csv_path):
    """Several source rows have no price at all. Zero would be a lie -- a
    stroller is not free."""
    seeding.seed_all(csv_path)

    stroller = catalog.find_item("Stroller", "baby_mom_items")
    assert stroller is not None
    assert stroller.current_price() is None
    assert stroller.price_entry == "manual"

    # The price row still exists, recording "as of this date, no price known".
    assert len(stroller.prices) == 1
    assert stroller.prices[0].unit_price_new is None


def test_items_with_a_blank_price_are_counted(app, csv_path):
    blanks = [
        row for row in rows_in_file(csv_path) if not row["unit_price_new"].strip()
    ]
    summary = seeding.seed_all(csv_path)
    assert summary["blank_prices"] == len(blanks)
    assert summary["blank_prices"] > 0


def test_every_item_gets_a_price_row(app, csv_path):
    seeding.seed_all(csv_path)
    assert ItemPrice.query.count() == Item.query.count()


def test_service_types_are_seeded(app, csv_path):
    seeding.seed_all(csv_path)
    names = {service.name for service in ServiceType.query.all()}
    assert "Diaper Distribution" in names
    assert "Bike Giveaway" in names
    assert len(names) == len(seeding.SERVICE_TYPES)


def test_used_multipliers_come_from_the_file(app, csv_path):
    """The rate on each item matches its row in the CSV, not a constant."""
    seeding.seed_all(csv_path)

    for row in rows_in_file(csv_path):
        item = catalog.find_item(row["item_name"].strip(), row["category"].strip())
        assert item is not None
        assert item.used_multiplier == pytest.approx(float(row["used_multiplier"]))


def test_reseeding_does_not_duplicate_or_overwrite(app, csv_path):
    """Running seed.py twice is safe, and it does not undo a price The Center Director
    has corrected in the app."""
    seeding.seed_all(csv_path)
    count = Item.query.count()

    coat = catalog.find_item("Coat", "clothing_adult")
    catalog.change_price(coat, 99.00)

    summary = seeding.seed_all(csv_path)

    assert Item.query.count() == count
    assert summary["items_added"] == 0
    assert summary["items_skipped"] == count
    assert catalog.find_item("Coat", "clothing_adult").current_price() == 99


def test_a_bad_report_bucket_is_refused(app, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text(
        "item_name,category,report_bucket,unit_price_new,used_multiplier,"
        "price_entry,notes\n"
        "Thing,home_goods,not_a_bucket,5.00,0.5,fixed,\n"
    )
    with pytest.raises(seeding.SeedError, match="report_bucket"):
        seeding.read_catalog_csv(str(bad))


def test_a_missing_used_rate_is_refused(app, tmp_path):
    """An item with no rate cannot be valued used, so it must not load."""
    bad = tmp_path / "bad.csv"
    bad.write_text(
        "item_name,category,report_bucket,unit_price_new,used_multiplier,"
        "price_entry,notes\n"
        "Thing,home_goods,household,5.00,,fixed,\n"
    )
    with pytest.raises(seeding.SeedError, match="used_multiplier"):
        seeding.read_catalog_csv(str(bad))


def test_a_missing_column_is_refused(app, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("item_name,category\nThing,home_goods\n")
    with pytest.raises(seeding.SeedError, match="missing columns"):
        seeding.read_catalog_csv(str(bad))
