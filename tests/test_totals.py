"""Totals, report buckets, and the CSV export.

The central test here is the one proving diapers and clothing/hygiene/household
produce independent totals. Diapers are the item The Center Director hands out most, and
FOCUS North America reports them in their own column. If a diaper count ever
leaks into the combined goods column, every monthly report is wrong.
"""

import datetime
from decimal import Decimal

from app.constants import COMBINED_GOODS_BUCKETS
from app.models import ServiceType
from app.services import batches, catalog, totals


def add_committed_batch(lines, date=None):
    """lines is [(item, quantity, condition), ...]"""
    batch = batches.open_batch(
        date=date or datetime.date.today(),
        service_type_id=ServiceType.query.first().id,
    )
    for item, quantity, condition in lines:
        batches.set_line(batch, item, quantity=quantity, condition=condition)
    batches.commit_batch(batch)
    return batch


def a_diaper():
    """Diapers are not in the seed CSV -- The Center Director adds them herself. That is
    exactly what this proves works."""
    return catalog.create_item(
        name="Diapers Size 3",
        category="diapers",
        report_bucket="diapers",
        used_multiplier=0.5,
        price_entry="fixed",
        unit_price_new=0.25,
    )


def range_today():
    today = datetime.date.today()
    return today, today


# --- The one that matters ---------------------------------------------------


def test_diapers_and_hygiene_produce_two_independent_totals(seeded_app):
    """A batch containing diapers and hygiene items gives two totals that do
    not overlap."""
    diaper = a_diaper()
    wipes = catalog.find_item("Individual Pack of Wipes", "baby_essentials")

    add_committed_batch([(diaper, 100, "new"), (wipes, 4, "new")])

    start, end = range_today()
    buckets = totals.bucket_totals(start, end)

    assert buckets["diapers"]["quantity"] == 100
    assert buckets["diapers"]["value"] == Decimal("25.00")

    assert buckets["hygiene"]["quantity"] == 4
    assert buckets["hygiene"]["value"] == Decimal("12.00")

    # Neither bucket contains any part of the other.
    assert buckets["diapers"]["quantity"] != buckets["hygiene"]["quantity"]
    assert "diapers" not in COMBINED_GOODS_BUCKETS


def test_diapers_do_not_roll_into_the_combined_goods_column(seeded_app):
    diaper = a_diaper()
    wipes = catalog.find_item("Individual Pack of Wipes", "baby_essentials")
    coat = catalog.find_item("Coat", "clothing_adult")

    add_committed_batch(
        [(diaper, 100, "new"), (wipes, 4, "new"), (coat, 1, "new")]
    )

    start, end = range_today()
    summary = totals.summary(start, end)

    # Combined goods is clothing + hygiene + household only.
    assert summary["combined_goods"]["quantity"] == 5  # 4 wipes + 1 coat
    assert summary["combined_goods"]["value"] == Decimal("72.00")  # 12 + 60

    # The grand total does include the diapers.
    assert summary["total_quantity"] == 105
    assert summary["total_value"] == Decimal("97.00")  # 72 + 25


def test_formula_and_food_are_also_separate_columns(seeded_app):
    formula = catalog.find_item("Formula - Similac 7oz", "baby_essentials")
    food = catalog.create_item(
        name="Food Box",
        category="food",
        report_bucket="food",
        used_multiplier=0.5,
        price_entry="fixed",
        unit_price_new=35,
    )
    wipes = catalog.find_item("Individual Pack of Wipes", "baby_essentials")

    add_committed_batch([(formula, 2, "new"), (food, 1, "new"), (wipes, 1, "new")])

    start, end = range_today()
    buckets = totals.bucket_totals(start, end)
    summary = totals.summary(start, end)

    assert buckets["formula"]["quantity"] == 2
    assert buckets["food"]["quantity"] == 1
    assert summary["combined_goods"]["quantity"] == 1  # only the wipes


def test_every_line_lands_in_exactly_one_bucket(seeded_app):
    """Belt and braces: the sum of the buckets equals the grand total."""
    diaper = a_diaper()
    add_committed_batch(
        [
            (diaper, 50, "new"),
            (catalog.find_item("Coat", "clothing_adult"), 2, "used"),
            (catalog.find_item("Individual Pack of Wipes", "baby_essentials"), 3,
             "new"),
            (catalog.find_item("Crib", "baby_mom_items"), 1, "new"),
        ]
    )

    start, end = range_today()
    summary = totals.summary(start, end)

    assert sum(b["quantity"] for b in summary["buckets"]) == summary["total_quantity"]
    assert sum(
        (b["value"] for b in summary["buckets"]), Decimal("0.00")
    ) == summary["total_value"]


# --- Drafts and date ranges -------------------------------------------------


def test_drafts_are_not_counted(seeded_app):
    coat = catalog.find_item("Coat", "clothing_adult")

    draft = batches.open_batch(service_type_id=ServiceType.query.first().id)
    batches.set_line(draft, coat, quantity=5)

    start, end = range_today()
    assert totals.summary(start, end)["total_quantity"] == 0


def test_approving_a_batch_makes_it_appear_in_the_totals(seeded_app):
    coat = catalog.find_item("Coat", "clothing_adult")
    start, end = range_today()

    assert totals.summary(start, end)["total_quantity"] == 0

    add_committed_batch([(coat, 2, "new")])

    assert totals.summary(start, end)["total_quantity"] == 2
    assert totals.summary(start, end)["total_value"] == Decimal("120.00")


def test_a_batch_outside_the_range_is_not_counted(seeded_app):
    coat = catalog.find_item("Coat", "clothing_adult")
    last_month = datetime.date.today() - datetime.timedelta(days=45)

    add_committed_batch([(coat, 2, "new")], date=last_month)

    start, end = range_today()
    assert totals.summary(start, end)["total_quantity"] == 0
    assert totals.summary(last_month, last_month)["total_quantity"] == 2


def test_month_range_covers_the_whole_month():
    start, end = totals.month_range(2026, 2)
    assert start == datetime.date(2026, 2, 1)
    assert end == datetime.date(2026, 2, 28)

    start, end = totals.month_range(2026, 12)
    assert end == datetime.date(2026, 12, 31)


# --- Custom lines are never silently dropped --------------------------------

def test_an_unsorted_custom_line_still_shows_up_in_the_totals(seeded_app):
    batch = batches.open_batch(service_type_id=ServiceType.query.first().id)
    batches.add_custom_line(batch, name="Mystery Box", quantity=2, unit_price=10)
    batches.commit_batch(batch)

    start, end = range_today()
    summary = totals.summary(start, end)

    labels = [bucket["label"] for bucket in summary["buckets"]]
    assert totals.UNSORTED_LABEL in labels
    assert summary["total_quantity"] == 2
    assert summary["total_value"] == Decimal("20.00")
    # It must not be counted as clothing/hygiene/household.
    assert summary["combined_goods"]["quantity"] == 0


# --- CSV export -------------------------------------------------------------


def test_the_export_always_shows_the_category(seeded_app):
    """Without it there is no way to tell a $60 adult coat from a $15 infant
    one."""
    add_committed_batch(
        [
            (catalog.find_item("Coat", "clothing_adult"), 1, "new"),
            (catalog.find_item("Coat", "clothing_infant"), 1, "new"),
        ]
    )

    start, end = range_today()
    csv_text = totals.export_csv(start, end)

    assert "clothing_adult" in csv_text
    assert "clothing_infant" in csv_text
    assert "60.00" in csv_text
    assert "15.00" in csv_text


def test_the_export_records_the_frozen_price_and_rate(seeded_app):
    coat = catalog.find_item("Coat", "clothing_adult")
    add_committed_batch([(coat, 1, "used")])

    catalog.change_price(coat, 999.00)

    start, end = range_today()
    csv_text = totals.export_csv(start, end)

    assert "60.00" in csv_text
    assert "0.75" in csv_text
    assert "999" not in csv_text


def test_the_export_has_one_row_per_line_plus_a_header(seeded_app):
    add_committed_batch(
        [
            (catalog.find_item("Coat", "clothing_adult"), 1, "new"),
            (catalog.find_item("Socks", "clothing_adult"), 2, "new"),
        ]
    )

    start, end = range_today()
    rows = [row for row in totals.export_csv(*range_today()).splitlines() if row]

    assert len(rows) == 3
    assert rows[0].startswith("batch_date,batch_id,service_type,item_name,category")
