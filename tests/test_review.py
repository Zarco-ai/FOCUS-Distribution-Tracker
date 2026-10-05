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


# --- Pricing a catalog line that was approved without one -------------------


def test_an_approved_unpriced_line_waits_in_the_queue(seeded_app):
    batch = a_batch()
    line = batches.set_line(
        batch, catalog.find_item("Stroller", "baby_mom_items"), quantity=1
    )
    batches.commit_batch(batch)

    assert review.flagged_lines() == [line]
    # It needs a price, not an identity -- it already has a catalog item.
    assert not line.is_custom
    assert line.needs_price


def test_pricing_a_line_puts_the_value_into_its_own_batch(seeded_app):
    """The whole point of flagging instead of blocking: the value lands on the
    batch it was counted in, not the one open when it was priced."""
    entered_on = datetime.date.today() - datetime.timedelta(days=10)
    batch = a_batch(date=entered_on)
    line = batches.set_line(
        batch, catalog.find_item("Stroller", "baby_mom_items"), quantity=2
    )
    batches.commit_batch(batch)

    assert batch.total_value == Decimal("0.00")

    review.price_line(line, unit_price=150)

    assert not line.needs_review
    assert line.reviewed_at is not None
    assert line.unit_price_at_time == Decimal("150.00")
    assert line.computed_value == Decimal("300.00")
    assert batch.total_value == Decimal("300.00")
    assert batch.date == entered_on


def test_pricing_a_used_line_applies_the_items_own_rate(seeded_app):
    batch = a_batch()
    line = batches.set_line(
        batch, catalog.find_item("Stroller", "baby_mom_items"), quantity=1,
        condition="used",
    )
    batches.commit_batch(batch)

    review.price_line(line, unit_price=200)

    # The stroller's own rate, read from the item, not a constant.
    assert line.used_multiplier_at_time == 0.5
    assert line.computed_value == Decimal("100.00")


def test_pricing_later_uses_the_rate_frozen_at_approval(seeded_app):
    """Only the price was missing. Changing the catalog rate in between must
    not move the value of something already committed."""
    batch = a_batch()
    stroller = catalog.find_item("Stroller", "baby_mom_items")
    line = batches.set_line(batch, stroller, quantity=1, condition="used")
    batches.commit_batch(batch)

    catalog.update_item(stroller, used_multiplier=0.9)

    review.price_line(line, unit_price=200)

    assert line.used_multiplier_at_time == 0.5
    assert line.computed_value == Decimal("100.00")


def test_pricing_a_committed_line_is_written_to_the_audit_log(seeded_app):
    from app.services import audit

    batch = a_batch()
    line = batches.set_line(
        batch, catalog.find_item("Stroller", "baby_mom_items"), quantity=1
    )
    batches.commit_batch(batch)

    review.price_line(line, unit_price=150)

    history = audit.history_for("line_item", line.id)
    assert any(entry.field == "unit_price_at_time" for entry in history)
    assert any(entry.field == "computed_value" for entry in history)


def test_pricing_a_draft_line_is_not_audited(seeded_app):
    from app.services import audit

    batch = a_batch()
    line = batches.set_line(
        batch, catalog.find_item("Stroller", "baby_mom_items"), quantity=1
    )

    review.price_line(line, unit_price=150)

    assert audit.history_for("line_item", line.id) == []


def test_pricing_with_no_number_and_no_catalog_price_asks_for_one(seeded_app):
    batch = a_batch()
    line = batches.set_line(
        batch, catalog.find_item("Stroller", "baby_mom_items"), quantity=1
    )
    batches.commit_batch(batch)

    with pytest.raises(ValueError, match="Type a price"):
        review.price_line(line)

    assert line.needs_review


def test_pricing_falls_back_to_the_catalog_price_when_there_is_one(seeded_app):
    """Small Rideable Toy Cars are manual-price but do have a trustworthy new
    price, so leaving the box empty confirms it rather than failing."""
    batch = a_batch()
    cars = catalog.find_item("Small Rideable Toy Cars", "home_goods")
    line = batches.set_line(batch, cars, quantity=1)
    batches.commit_batch(batch)

    review.price_line(line)

    assert line.unit_price_at_time == cars.current_price()
    assert not line.needs_review


def test_a_catalog_line_is_not_sent_through_the_custom_item_path(seeded_app):
    batch = a_batch()
    line = batches.set_line(
        batch, catalog.find_item("Stroller", "baby_mom_items"), quantity=1
    )
    batches.commit_batch(batch)

    with pytest.raises(ValueError, match="already in the catalog"):
        review.resolve_line(line, item=catalog.find_item("Coat", "clothing_adult"))


def test_a_custom_line_is_not_sent_through_the_pricing_path(seeded_app):
    batch = a_batch()
    line = batches.add_custom_line(batch, name="Mystery", quantity=1)

    with pytest.raises(ValueError, match="not in the catalog"):
        review.price_line(line, unit_price=10)


# --- A price of zero is not a price -----------------------------------------
#
# Zero means "nobody has decided yet", so a line recorded at zero belongs in the
# queue no matter which screen put it there or how many times it has been round
# already. These tests walk that round trip in both directions.


def a_committed_stroller_line():
    """One approved line with no price on it -- the plainest thing the queue
    exists for."""
    batch = a_batch()
    line = batches.set_line(
        batch, catalog.find_item("Stroller", "baby_mom_items"), quantity=1
    )
    batches.commit_batch(batch)
    return line


def test_pricing_a_line_at_zero_leaves_it_in_the_queue(seeded_app):
    line = a_committed_stroller_line()

    review.price_line(line, unit_price=0)

    assert line.unit_price_at_time == Decimal("0.00")
    assert line.needs_review
    assert line.needs_price
    assert review.flagged_lines() == [line]


def test_a_priced_line_put_back_to_zero_returns_to_the_queue(seeded_app):
    """The reported bug: price it from the queue, then take it back to zero on
    the review screen, and it has to come back."""
    line = a_committed_stroller_line()

    review.price_line(line, unit_price=5)
    assert not line.needs_review

    batches.correct_line(line, unit_price=0)

    assert line.computed_value == Decimal("0.00")
    assert line.needs_review
    assert review.flagged_lines() == [line]
    # And it has not been reviewed, whatever the earlier pricing said.
    assert line.reviewed_at is None


def test_the_zero_round_trip_can_be_repeated(seeded_app):
    """Not a one-shot flag. Each time the value goes away it comes back to the
    queue, and each time a real value arrives it leaves again."""
    line = a_committed_stroller_line()

    for unit_price, expected in [(5, False), (0, True), (25, False), (0, True)]:
        batches.correct_line(line, unit_price=unit_price)
        assert line.needs_review is expected, unit_price
        assert (line in review.flagged_lines()) is expected, unit_price


def test_a_zero_priced_line_is_flagged_when_the_batch_is_approved(seeded_app):
    """Typed as zero on the counting screen, never touched again. Approving has
    to notice, the same as it does for a line with no price at all."""
    batch = a_batch()
    line = batches.set_line(
        batch, catalog.find_item("Stroller", "baby_mom_items"), quantity=2,
        unit_price=0,
    )

    assert batches.can_commit(batch)
    batches.commit_batch(batch)

    assert line.needs_review
    assert batch.flagged_lines == [line]
    assert batch.needs_review
    # The quantity is still recorded in full. That is the whole point.
    assert batch.item_count == 2


def test_a_draft_line_is_not_put_in_the_queue_mid_count(seeded_app):
    """She is still typing. The queue is for lines that got away, not for rows
    she has had open for four seconds -- approval is what sweeps them up."""
    batch = a_batch()
    line = batches.set_line(
        batch, catalog.find_item("Stroller", "baby_mom_items"), quantity=1,
        unit_price=0,
    )

    assert line.needs_price
    assert not line.needs_review
    assert review.flagged_lines() == []


def test_resolving_a_custom_line_at_zero_keeps_it_in_the_queue(seeded_app):
    """It has an identity now, so it is no longer waiting for a catalog match --
    but it is still worth nothing, so it is still waiting."""
    batch = a_batch()
    line = batches.add_custom_line(batch, name="A stroller", quantity=1)
    batches.commit_batch(batch)

    review.resolve_line(
        line, item=catalog.find_item("Stroller", "baby_mom_items"), unit_price=0
    )

    assert line.item_id is not None
    assert not line.is_custom
    assert line.needs_review
    # It moved sections: it is waiting for a price now, not for a match.
    assert review.flagged_lines() == [line]


def test_a_resolved_line_leaves_the_queue_once_it_is_worth_something(seeded_app):
    batch = a_batch()
    line = batches.add_custom_line(batch, name="A stroller", quantity=1)
    batches.commit_batch(batch)

    review.resolve_line(
        line, item=catalog.find_item("Stroller", "baby_mom_items"), unit_price=0
    )
    review.price_line(line, unit_price=300)

    assert not line.needs_review
    assert line.reviewed_at is not None
    assert line.computed_value == Decimal("300.00")
    assert review.flagged_lines() == []


def test_a_zero_line_going_back_to_the_queue_is_written_to_the_audit_log(seeded_app):
    """Un-finishing a line on an approved batch is a change to reported data
    like any other."""
    from app.services import audit

    line = a_committed_stroller_line()
    review.price_line(line, unit_price=5)

    batches.correct_line(line, unit_price=0)

    history = audit.history_for("line_item", line.id)
    flag_entries = [entry for entry in history if entry.field == "needs_review"]
    assert flag_entries
    assert flag_entries[0].old_value == "no"
    assert flag_entries[0].new_value == "yes"


def test_a_zero_quantity_line_is_not_in_the_queue(seeded_app):
    """A line counted back down to zero is not waiting for anything -- it is not
    in the batch at all, and approval drops it."""
    batch = a_batch()
    stroller = catalog.find_item("Stroller", "baby_mom_items")
    line = batches.set_line(batch, stroller, quantity=1, unit_price=0)
    batches.set_line(batch, stroller, quantity=0)
    batches.set_line(batch, catalog.find_item("Coat", "clothing_adult"), quantity=1)

    assert not line.needs_price

    batches.commit_batch(batch)

    assert review.flagged_lines() == []
    assert not batch.needs_review


def test_the_queue_lists_only_unresolved_lines(seeded_app):
    batch = a_batch()
    keep = batches.add_custom_line(batch, name="Mystery", quantity=1, unit_price=5)
    resolve_me = batches.add_custom_line(batch, name="A coat", quantity=1)

    assert review.flagged_count() == 2

    review.resolve_line(resolve_me, item=catalog.find_item("Coat", "clothing_adult"))

    assert review.flagged_count() == 1
    assert review.flagged_lines() == [keep]
