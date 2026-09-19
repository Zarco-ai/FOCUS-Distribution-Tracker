"""Custom items and the review queue."""

import datetime
from decimal import Decimal

import pytest

from app.models import ServiceType
from app.services import batches, catalog, review


def a_batch(date=None):
    return batches.open_batch(
        date=date, service_type_id=ServiceType.query.first().id
    )


# --- Adding something not on the list --------------------------------------


def test_a_custom_line_is_flagged_for_review(seeded_app):
    batch = a_batch()
    line = batches.add_custom_line(batch, name="Bike helmet", quantity=1,
                                   unit_price=25)

    assert line.needs_review
    assert line.is_custom
    assert line.item_id is None
    assert line.custom_name == "Bike helmet"
    assert line.computed_value == Decimal("25.00")


def test_a_custom_line_keeps_the_batch_date(seeded_app):
    """The date is never typed by hand, and resolving the line later must not
    move it into the month it was resolved in."""
    entered_on = datetime.date.today() - datetime.timedelta(days=10)
    batch = a_batch(date=entered_on)
    line = batches.add_custom_line(batch, name="Bike helmet", quantity=1,
                                   unit_price=25)
    batches.commit_batch(batch)

    review.resolve_line(
        line,
        new_item_fields={
            "name": "Bike Helmet",
            "category": "home_goods",
            "report_bucket": "household",
            "used_multiplier": 0.5,
            "price_entry": "fixed",
            "unit_price_new": 25,
        },
    )

    assert line.batch.date == entered_on


def test_a_custom_line_can_be_committed_with_the_batch(seeded_app):
    batch = a_batch()
    batches.add_custom_line(batch, name="Bike helmet", quantity=1, unit_price=25)

    batches.commit_batch(batch)

    assert batch.is_committed
    assert batch.total_value == Decimal("25.00")
    assert batch.flagged_lines


def test_a_custom_line_defaults_to_a_price_of_zero(seeded_app):
    """She is adding this mid-distribution without knowing what it is worth.
    Making her invent a number before she can approve would be worse than
    recording zero and pricing it properly in the review queue."""
    batch = a_batch()
    line = batches.add_custom_line(batch, name="Mystery item", quantity=1)

    assert line.unit_price_at_time == Decimal("0.00")
    assert line.computed_value == Decimal("0.00")
    assert line.needs_review


def test_a_custom_line_with_no_price_does_not_block_approval(seeded_app):
    batch = a_batch()
    batches.add_custom_line(batch, name="Mystery item", quantity=1)

    assert batches.can_commit(batch)
    batches.commit_batch(batch)

    assert batch.is_committed
    assert batch.total_value == Decimal("0.00")
    assert batch.item_count == 1


def test_a_used_custom_line_at_zero_is_worth_zero(seeded_app):
    """It has no category yet and therefore no used rate, but zero dollars is
    zero dollars either way."""
    batch = a_batch()
    line = batches.add_custom_line(
        batch, name="Mystery item", quantity=3, condition="used"
    )

    assert line.used_multiplier_at_time is None
    assert line.computed_value == Decimal("0.00")
    assert batches.can_commit(batch)


def test_a_custom_line_still_takes_a_price_when_one_is_typed(seeded_app):
    batch = a_batch()
    line = batches.add_custom_line(
        batch, name="Bike helmet", quantity=2, unit_price=25
    )

    assert line.unit_price_at_time == Decimal("25.00")
    assert line.computed_value == Decimal("50.00")


def test_a_custom_line_needs_a_name(seeded_app):
    batch = a_batch()
    with pytest.raises(ValueError, match="name"):
        batches.add_custom_line(batch, name="   ", quantity=1)


def test_a_custom_note_is_kept(seeded_app):
    batch = a_batch()
    line = batches.add_custom_line(
        batch, name="Bike helmet", quantity=1, unit_price=25,
        note="blue, child size",
    )
    assert line.custom_note == "blue, child size"


def test_a_custom_line_is_shown_as_not_in_catalog(seeded_app):
    """Every place an item is displayed has to say what it is. An unresolved
    custom line has no category yet, so it says so."""
    batch = a_batch()
    line = batches.add_custom_line(batch, name="Bike helmet", quantity=1)
    assert "not in catalog" in line.display_name


# --- Resolving --------------------------------------------------------------


def test_resolving_against_an_existing_item_picks_up_its_rate(seeded_app):
    batch = a_batch()
    line = batches.add_custom_line(batch, name="A coat", quantity=1,
                                   condition="used")

    coat = catalog.find_item("Coat", "clothing_adult")
    review.resolve_line(line, item=coat)

    assert not line.needs_review
    assert line.reviewed_at is not None
    assert line.item_id == coat.id
    assert line.used_multiplier_at_time == 0.75
    assert line.computed_value == Decimal("45.00")


def test_resolving_can_create_a_new_catalog_item(seeded_app):
    batch = a_batch()
    line = batches.add_custom_line(batch, name="Diapers Size 3", quantity=100)

    review.resolve_line(
        line,
        new_item_fields={
            "name": "Diapers Size 3",
            "category": "diapers",
            "report_bucket": "diapers",
            "used_multiplier": 0.5,
            "price_entry": "fixed",
            "unit_price_new": 0.25,
        },
    )

    assert not line.needs_review
    assert line.report_bucket == "diapers"
    assert line.computed_value == Decimal("25.00")
    assert catalog.find_item("Diapers Size 3", "diapers") is not None


def test_resolving_a_committed_line_is_written_to_the_audit_log(seeded_app):
    from app.services import audit

    batch = a_batch()
    line = batches.add_custom_line(batch, name="A coat", quantity=1, unit_price=60)
    batches.commit_batch(batch)

    review.resolve_line(line, item=catalog.find_item("Coat", "clothing_adult"))

    history = audit.history_for("line_item", line.id)
    assert history
    assert any(entry.field == "item_id" for entry in history)


def test_resolving_a_draft_line_is_not_audited(seeded_app):
    from app.services import audit

    batch = a_batch()
    line = batches.add_custom_line(batch, name="A coat", quantity=1)

    review.resolve_line(line, item=catalog.find_item("Coat", "clothing_adult"))

    assert audit.history_for("line_item", line.id) == []


def test_resolving_without_an_item_is_refused(seeded_app):
    batch = a_batch()
    line = batches.add_custom_line(batch, name="Mystery", quantity=1)

    with pytest.raises(ValueError, match="Pick an item"):
        review.resolve_line(line)


def test_resolving_to_an_item_with_no_price_asks_for_one(seeded_app):
    batch = a_batch()
    line = batches.add_custom_line(batch, name="A stroller", quantity=1)
    stroller = catalog.find_item("Stroller", "baby_mom_items")

    with pytest.raises(ValueError, match="no price on file"):
        review.resolve_line(line, item=stroller)

    review.resolve_line(line, item=stroller, unit_price=300)
    assert line.computed_value == Decimal("300.00")


def test_the_queue_lists_only_unresolved_lines(seeded_app):
    batch = a_batch()
    keep = batches.add_custom_line(batch, name="Mystery", quantity=1, unit_price=5)
    resolve_me = batches.add_custom_line(batch, name="A coat", quantity=1)

    assert review.flagged_count() == 2

    review.resolve_line(resolve_me, item=catalog.find_item("Coat", "clothing_adult"))

    assert review.flagged_count() == 1
    assert review.flagged_lines() == [keep]
