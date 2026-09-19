"""The batch lifecycle: counting, blocking, approving, freezing, correcting."""

import datetime
from decimal import Decimal

import pytest

from app.constants import (
    COMMIT_MODE_AUTO,
    COMMIT_MODE_PER_BATCH,
    COMMIT_MODE_PER_MOTHER,
)
from app.extensions import db
from app.models import ServiceType, set_commit_mode
from app.services import audit, batches, catalog


def a_batch(with_service_type=True):
    service = ServiceType.query.first() if with_service_type else None
    return batches.open_batch(service_type_id=service.id if service else None)


def item(name, category):
    return catalog.find_item(name, category)


# --- Counting ---------------------------------------------------------------


def test_a_line_is_valued_as_it_is_counted(seeded_app):
    batch = a_batch()
    line = batches.set_line(batch, item("Coat", "clothing_adult"), quantity=1,
                            condition="used")

    assert line.computed_value == Decimal("45.00")
    assert line.unit_price_at_time == Decimal("60.00")
    assert line.used_multiplier_at_time == 0.75


def test_quantity_never_goes_below_zero(seeded_app):
    batch = a_batch()
    coat = item("Coat", "clothing_adult")

    batches.set_line(batch, coat, quantity=1)
    line = batches.set_line(batch, coat, quantity=-5)

    assert line.quantity == 0


def test_a_zero_quantity_line_is_not_in_the_batch(seeded_app):
    batch = a_batch()
    coat = item("Coat", "clothing_adult")

    batches.set_line(batch, coat, quantity=3)
    assert batch.item_count == 3

    batches.set_line(batch, coat, quantity=0)
    assert batch.item_count == 0
    assert batch.active_lines == []
    assert batch.total_value == Decimal("0.00")


def test_zero_quantity_lines_are_dropped_at_approval(seeded_app):
    batch = a_batch()
    batches.set_line(batch, item("Coat", "clothing_adult"), quantity=0)
    batches.set_line(batch, item("Socks", "clothing_adult"), quantity=2)

    batches.commit_batch(batch)

    assert len(batch.lines) == 1
    assert batch.lines[0].item.name == "Socks"


def test_the_same_item_can_be_counted_new_and_used_in_one_batch(seeded_app):
    """Lines are keyed on (item, condition). Counting used ones must not
    disturb the new ones already counted."""
    batch = a_batch()
    coat = item("Coat", "clothing_adult")

    batches.set_line(batch, coat, quantity=3, condition="new")
    batches.set_line(batch, coat, quantity=2, condition="used")

    assert len(batch.active_lines) == 2
    assert batch.item_count == 5
    # 3 x 60 = 180, plus 2 x 60 x 0.75 = 90
    assert batch.total_value == Decimal("270.00")

    new_line = batches.find_line(batch, coat.id, "new")
    used_line = batches.find_line(batch, coat.id, "used")
    assert new_line.quantity == 3
    assert used_line.quantity == 2
    assert new_line.id != used_line.id


def test_counting_used_does_not_reset_the_new_ones(seeded_app):
    """The bug this replaced: adding a used one used to overwrite the new
    line's condition and lose the count."""
    batch = a_batch()
    bottles = item("Bottles", "baby_essentials")

    batches.set_line(batch, bottles, quantity=1, condition="new")
    batches.set_line(batch, bottles, quantity=1, condition="used")

    assert batches.find_line(batch, bottles.id, "new").quantity == 1
    assert batches.find_line(batch, bottles.id, "used").quantity == 1
    # $7.00 new plus $3.50 used
    assert batch.total_value == Decimal("10.50")


def test_each_condition_carries_its_own_typed_price(seeded_app):
    """A used stroller is not simply a fraction of whatever she typed for a new
    one -- they are separate goods with separate values."""
    batch = a_batch()
    stroller = item("Stroller", "baby_mom_items")

    batches.set_line(batch, stroller, quantity=1, condition="new",
                     unit_price="300.00")
    batches.set_line(batch, stroller, quantity=1, condition="used",
                     unit_price="40.00")

    new_line = batches.find_line(batch, stroller.id, "new")
    used_line = batches.find_line(batch, stroller.id, "used")

    assert new_line.unit_price_at_time == Decimal("300.00")
    assert new_line.computed_value == Decimal("300.00")
    assert used_line.unit_price_at_time == Decimal("40.00")
    assert used_line.computed_value == Decimal("20.00")  # 40 x 0.50


def test_setting_a_used_quantity_leaves_the_new_price_alone(seeded_app):
    batch = a_batch()
    stroller = item("Stroller", "baby_mom_items")

    batches.set_line(batch, stroller, quantity=1, condition="new",
                     unit_price="300.00")
    batches.set_line(batch, stroller, quantity=2, condition="used")

    assert batches.find_line(
        batch, stroller.id, "new"
    ).unit_price_at_time == Decimal("300.00")
    assert batches.find_line(batch, stroller.id, "used").unit_price_at_time is None


def test_an_empty_second_condition_is_dropped_at_approval(seeded_app):
    """Flipping the toggle to look at Used and flipping back must not leave an
    empty used line in the approved batch."""
    batch = a_batch()
    coat = item("Coat", "clothing_adult")

    batches.set_line(batch, coat, quantity=2, condition="new")
    batches.set_line(batch, coat, quantity=0, condition="used")

    batches.commit_batch(batch)

    assert len(batch.lines) == 1
    assert batch.lines[0].condition == "new"
    assert batch.total_value == Decimal("120.00")


def test_changing_a_condition_from_the_review_screen_edits_that_line(seeded_app):
    """update_draft_line() mutates the line in front of her, rather than
    looking one up by condition the way the counting screen does."""
    batch = a_batch()
    coat = item("Coat", "clothing_adult")
    line = batches.set_line(batch, coat, quantity=1, condition="new")

    batches.update_draft_line(line, condition="used")

    assert len(batch.lines) == 1
    assert line.condition == "used"
    assert line.computed_value == Decimal("45.00")


def test_review_refuses_a_condition_change_that_would_collide(seeded_app):
    batch = a_batch()
    coat = item("Coat", "clothing_adult")
    new_line = batches.set_line(batch, coat, quantity=1, condition="new")
    batches.set_line(batch, coat, quantity=2, condition="used")

    with pytest.raises(ValueError, match="already has a used line"):
        batches.update_draft_line(new_line, condition="used")


def test_the_batch_total_adds_up_across_both_rates(seeded_app):
    batch = a_batch()
    batches.set_line(batch, item("Coat", "clothing_adult"), quantity=1,
                     condition="used")  # 60 * 0.75 = 45.00
    batches.set_line(batch, item("Blood Pressure Monitor", "womens_hygiene"),
                     quantity=1, condition="used")  # 75 * 0.50 = 37.50

    assert batch.total_value == Decimal("82.50")
    assert batch.item_count == 2


def test_the_date_defaults_to_today_and_is_never_typed(seeded_app):
    batch = a_batch()
    assert batch.date == datetime.date.today()


# --- Manual prices ----------------------------------------------------------


def test_a_manual_item_starts_with_no_price(seeded_app):
    batch = a_batch()
    line = batches.set_line(batch, item("Stroller", "baby_mom_items"), quantity=1)

    assert line.unit_price_at_time is None
    assert line.computed_value is None


def test_a_batch_with_an_unpriced_manual_line_cannot_be_approved(seeded_app):
    batch = a_batch()
    batches.set_line(batch, item("Stroller", "baby_mom_items"), quantity=1)

    assert not batches.can_commit(batch)
    with pytest.raises(batches.BatchNotReady) as raised:
        batches.commit_batch(batch)

    assert any("need a price" in reason for reason in raised.value.reasons)
    assert batch.is_draft


def test_typing_a_price_unblocks_the_batch(seeded_app):
    batch = a_batch()
    stroller = item("Stroller", "baby_mom_items")

    batches.set_line(batch, stroller, quantity=1)
    batches.set_line(batch, stroller, unit_price="250.00")

    assert batches.can_commit(batch)
    batches.commit_batch(batch)
    assert batch.total_value == Decimal("250.00")


def test_the_used_rate_still_applies_to_a_typed_price(seeded_app):
    batch = a_batch()
    stroller = item("Stroller", "baby_mom_items")

    line = batches.set_line(batch, stroller, quantity=1, condition="used",
                            unit_price="250.00")

    assert line.computed_value == Decimal("125.00")  # 250 * 0.50


def test_a_typed_price_does_not_change_the_catalog(seeded_app):
    """The price lands on the line only. The Center Director fills the catalog in from
    the item admin screen, deliberately."""
    batch = a_batch()
    stroller = item("Stroller", "baby_mom_items")

    batches.set_line(batch, stroller, quantity=1, unit_price="250.00")

    assert stroller.current_price() is None
    assert stroller.price_entry == "manual"
    assert len(stroller.prices) == 1


def test_changing_the_quantity_does_not_wipe_a_typed_price(seeded_app):
    batch = a_batch()
    stroller = item("Stroller", "baby_mom_items")

    batches.set_line(batch, stroller, quantity=1, unit_price="250.00")
    line = batches.set_line(batch, stroller, quantity=2)

    assert line.unit_price_at_time == Decimal("250.00")
    assert line.computed_value == Decimal("500.00")


def test_the_same_manual_item_can_be_recorded_at_two_prices(seeded_app):
    """Two strollers worth $40 and $300 cannot share one price."""
    batch = a_batch()
    stroller = item("Stroller", "baby_mom_items")

    batches.set_line(batch, stroller, quantity=1, unit_price="300.00")
    cheap = batches.add_price_group(batch, stroller)
    batches.update_draft_line(cheap, unit_price="40.00")

    assert len(batch.active_lines) == 2
    assert batch.item_count == 2
    assert batch.total_value == Decimal("340.00")


def test_extra_prices_are_kept_apart_per_condition(seeded_app):
    batch = a_batch()
    stroller = item("Stroller", "baby_mom_items")

    batches.set_line(batch, stroller, quantity=1, condition="new",
                     unit_price="300.00")
    batches.set_line(batch, stroller, quantity=1, condition="used",
                     unit_price="80.00")
    extra = batches.add_price_group(batch, stroller, condition="used")
    batches.update_draft_line(extra, unit_price="40.00")

    assert len(batches.lines_for(batch, stroller.id, "new")) == 1
    assert len(batches.lines_for(batch, stroller.id, "used")) == 2
    # 300 new, plus 80 x 0.50 and 40 x 0.50 used
    assert batch.total_value == Decimal("360.00")


def test_the_main_row_still_edits_the_first_line(seeded_app):
    """Adding a second price must not make the +/- buttons ambiguous."""
    batch = a_batch()
    stroller = item("Stroller", "baby_mom_items")

    first = batches.set_line(batch, stroller, quantity=1, unit_price="300.00")
    batches.add_price_group(batch, stroller)

    again = batches.set_line(batch, stroller, quantity=4)

    assert again.id == first.id
    assert again.unit_price_at_time == Decimal("300.00")


def test_an_unpriced_extra_blocks_approval_like_any_other(seeded_app):
    batch = a_batch()
    stroller = item("Stroller", "baby_mom_items")

    batches.set_line(batch, stroller, quantity=1, unit_price="300.00")
    batches.add_price_group(batch, stroller)

    assert not batches.can_commit(batch)
    with pytest.raises(batches.BatchNotReady):
        batches.commit_batch(batch)


def test_a_fixed_price_item_is_refused_a_second_price(seeded_app):
    """Its value comes from the catalog, so two of them are a quantity of
    two."""
    batch = a_batch()
    with pytest.raises(ValueError, match="set price"):
        batches.add_price_group(batch, item("Coat", "clothing_adult"))


def test_an_extra_price_can_be_removed(seeded_app):
    batch = a_batch()
    stroller = item("Stroller", "baby_mom_items")

    batches.set_line(batch, stroller, quantity=1, unit_price="300.00")
    extra = batches.add_price_group(batch, stroller)
    batches.update_draft_line(extra, unit_price="40.00")
    assert batch.total_value == Decimal("340.00")

    batches.remove_line(extra)

    assert len(batch.active_lines) == 1
    assert batch.total_value == Decimal("300.00")


def test_both_prices_freeze_independently_at_approval(seeded_app):
    batch = a_batch()
    stroller = item("Stroller", "baby_mom_items")

    batches.set_line(batch, stroller, quantity=1, unit_price="300.00")
    extra = batches.add_price_group(batch, stroller)
    batches.update_draft_line(extra, unit_price="40.00")
    batches.commit_batch(batch)

    prices = sorted(line.unit_price_at_time for line in batch.active_lines)
    assert prices == [Decimal("40.00"), Decimal("300.00")]

    catalog.change_price(stroller, 999.00)
    assert batch.total_value == Decimal("340.00")


def test_a_prefilled_manual_item_keeps_its_suggested_price(seeded_app):
    """Small Rideable Toy Cars has a trustworthy new price but a used value
    that does not follow the rate, so it is pre-filled and editable."""
    cars = item("Small Rideable Toy Cars", "home_goods")
    assert cars.price_entry == "manual"
    assert cars.current_price() == Decimal("50.00")


# --- Service type -----------------------------------------------------------


def test_items_can_be_added_before_a_service_type_is_picked(seeded_app):
    batch = a_batch(with_service_type=False)
    line = batches.set_line(batch, item("Coat", "clothing_adult"), quantity=1)

    assert line.quantity == 1
    assert batch.service_type_id is None


def test_a_batch_without_a_service_type_cannot_be_approved(seeded_app):
    batch = a_batch(with_service_type=False)
    batches.set_line(batch, item("Coat", "clothing_adult"), quantity=1)

    with pytest.raises(batches.BatchNotReady) as raised:
        batches.commit_batch(batch)
    assert any("service type" in reason for reason in raised.value.reasons)


def test_an_empty_batch_cannot_be_approved(seeded_app):
    batch = a_batch()
    with pytest.raises(batches.BatchNotReady) as raised:
        batches.commit_batch(batch)
    assert any("at least one item" in reason for reason in raised.value.reasons)


# --- Freezing at approval ---------------------------------------------------


def test_a_later_catalog_price_change_does_not_move_a_committed_total(seeded_app):
    """Last year's report must reproduce last year's numbers."""
    batch = a_batch()
    coat = item("Coat", "clothing_adult")
    batches.set_line(batch, coat, quantity=1, condition="used")
    batches.commit_batch(batch)

    assert batch.total_value == Decimal("45.00")

    catalog.change_price(coat, 200.00)

    assert coat.current_price() == Decimal("200.00")
    assert batch.total_value == Decimal("45.00")
    assert batch.lines[0].unit_price_at_time == Decimal("60.00")


def test_a_later_used_rate_change_does_not_move_a_committed_total(seeded_app):
    batch = a_batch()
    coat = item("Coat", "clothing_adult")
    batches.set_line(batch, coat, quantity=1, condition="used")
    batches.commit_batch(batch)

    catalog.update_item(coat, used_multiplier=0.25)

    assert coat.used_multiplier == 0.25
    assert batch.lines[0].used_multiplier_at_time == 0.75
    assert batch.total_value == Decimal("45.00")


def test_deactivating_an_item_does_not_move_a_committed_total(seeded_app):
    batch = a_batch()
    coat = item("Coat", "clothing_adult")
    batches.set_line(batch, coat, quantity=2, condition="new")
    batches.commit_batch(batch)

    catalog.set_active(coat, False)

    assert batch.total_value == Decimal("120.00")


def test_a_draft_still_follows_the_catalog_price(seeded_app):
    """A draft is still being written, so it is not history yet."""
    batch = a_batch()
    coat = item("Coat", "clothing_adult")
    batches.set_line(batch, coat, quantity=1)

    catalog.change_price(coat, 80.00)
    batches.set_line(batch, coat, quantity=1)

    assert batch.total_value == Decimal("80.00")


def test_approving_records_when_it_happened(seeded_app):
    batch = a_batch()
    batches.set_line(batch, item("Coat", "clothing_adult"), quantity=1)
    batches.commit_batch(batch)

    assert batch.is_committed
    assert batch.committed_at is not None


# --- Corrections and the audit log -----------------------------------------


def test_a_committed_batch_cannot_be_edited_without_the_audit_log(seeded_app):
    batch = a_batch()
    coat = item("Coat", "clothing_adult")
    batches.set_line(batch, coat, quantity=1)
    batches.commit_batch(batch)

    with pytest.raises(ValueError, match="audit log"):
        batches.set_line(batch, coat, quantity=5)


def test_correcting_a_committed_line_writes_to_the_audit_log(seeded_app):
    batch = a_batch()
    batches.set_line(batch, item("Coat", "clothing_adult"), quantity=1,
                     condition="new")
    batches.commit_batch(batch)
    line = batch.lines[0]

    batches.correct_line(line, quantity=3)

    assert line.quantity == 3
    assert line.computed_value == Decimal("180.00")

    history = {entry.field: entry for entry in audit.history_for("line_item", line.id)}
    assert history["quantity"].old_value == "1"
    assert history["quantity"].new_value == "3"
    assert history["computed_value"].old_value == "60.00"
    assert history["computed_value"].new_value == "180.00"


def test_correcting_to_the_same_value_logs_nothing(seeded_app):
    batch = a_batch()
    batches.set_line(batch, item("Coat", "clothing_adult"), quantity=1)
    batches.commit_batch(batch)
    line = batch.lines[0]

    batches.correct_line(line, quantity=1)

    assert audit.history_for("line_item", line.id) == []


def test_a_committed_batch_cannot_be_discarded(seeded_app):
    batch = a_batch()
    batches.set_line(batch, item("Coat", "clothing_adult"), quantity=1)
    batches.commit_batch(batch)

    with pytest.raises(ValueError):
        batches.discard_batch(batch)


# --- Stale drafts -----------------------------------------------------------


def test_a_draft_from_a_previous_day_is_flagged_not_deleted(seeded_app):
    batch = batches.open_batch(date=datetime.date.today() - datetime.timedelta(days=3))
    batches.set_line(batch, item("Coat", "clothing_adult"), quantity=1)
    db.session.commit()

    assert batch.is_stale
    assert batch in batches.stale_draft_batches()
    assert batch.is_draft  # still there, nothing was auto-removed


def test_todays_draft_is_not_stale(seeded_app):
    batch = a_batch()
    db.session.commit()
    assert not batch.is_stale


def test_a_committed_batch_is_never_stale(seeded_app):
    batch = batches.open_batch(
        date=datetime.date.today() - datetime.timedelta(days=30),
        service_type_id=ServiceType.query.first().id,
    )
    batches.set_line(batch, item("Coat", "clothing_adult"), quantity=1)
    batches.commit_batch(batch)

    assert not batch.is_stale


# --- Commit modes -----------------------------------------------------------


def test_per_batch_mode_leaves_the_batch_a_draft_until_approved(seeded_app):
    set_commit_mode(COMMIT_MODE_PER_BATCH)
    batch = a_batch()
    batches.set_line(batch, item("Coat", "clothing_adult"), quantity=1)

    assert not batches.maybe_autocommit(batch)
    assert batch.is_draft


def test_per_mother_mode_also_waits_for_approval(seeded_app):
    set_commit_mode(COMMIT_MODE_PER_MOTHER)
    batch = a_batch()
    batches.set_line(batch, item("Coat", "clothing_adult"), quantity=1)

    assert not batches.maybe_autocommit(batch)
    assert batch.is_draft


def test_auto_mode_saves_as_she_counts(seeded_app):
    set_commit_mode(COMMIT_MODE_AUTO)
    batch = a_batch()
    batches.set_line(batch, item("Coat", "clothing_adult"), quantity=1)

    assert batches.maybe_autocommit(batch)
    assert batch.is_committed
    assert batch.total_value == Decimal("60.00")


def test_auto_mode_can_keep_counting_into_the_same_batch(seeded_app):
    set_commit_mode(COMMIT_MODE_AUTO)
    batch = a_batch()

    batches.set_line(batch, item("Coat", "clothing_adult"), quantity=1)
    batches.maybe_autocommit(batch)

    batches.set_line(batch, item("Socks", "clothing_adult"), quantity=2)
    batches.maybe_autocommit(batch)

    assert batch.is_committed
    assert batch.item_count == 3
    assert batch.total_value == Decimal("66.00")  # 60 + 2*3


def test_auto_mode_holds_back_an_unpriced_manual_line(seeded_app):
    """'No committed line is ever missing a price' has to be true in every
    mode, including this one."""
    set_commit_mode(COMMIT_MODE_AUTO)
    batch = a_batch()
    batches.set_line(batch, item("Stroller", "baby_mom_items"), quantity=1)

    assert not batches.maybe_autocommit(batch)
    assert batch.is_draft

    batches.set_line(batch, item("Stroller", "baby_mom_items"), unit_price="250")

    assert batches.maybe_autocommit(batch)
    assert batch.is_committed


def test_auto_mode_waits_for_a_service_type(seeded_app):
    set_commit_mode(COMMIT_MODE_AUTO)
    batch = a_batch(with_service_type=False)
    batches.set_line(batch, item("Coat", "clothing_adult"), quantity=1)

    assert not batches.maybe_autocommit(batch)
    assert batch.is_draft


def test_no_committed_line_ever_lacks_a_price(seeded_app):
    """The invariant, checked across all three modes."""
    for mode in (COMMIT_MODE_PER_BATCH, COMMIT_MODE_PER_MOTHER, COMMIT_MODE_AUTO):
        set_commit_mode(mode)
        batch = a_batch()
        batches.set_line(batch, item("Stroller", "baby_mom_items"), quantity=1)
        batches.maybe_autocommit(batch)

        if batch.is_committed:
            for line in batch.active_lines:
                assert line.unit_price_at_time is not None
