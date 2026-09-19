"""The valuation rule.

    line_value = quantity x unit_price_new x (used_multiplier if used else 1)

These are the numbers Christopher can check against The Center Director's own sheets. If
any of them move, the monthly report is wrong.
"""

from decimal import Decimal

import pytest

from app.services import catalog, valuation


def value_for(name, category, quantity, condition):
    """Look an item up by name AND category, then value it. Never by name
    alone -- there are three different Pants."""
    item = catalog.find_item(name, category)
    assert item is not None, f"{name} / {category} is not in the seeded catalog"
    return valuation.line_value(
        quantity=quantity,
        unit_price=item.current_price(),
        used_multiplier=item.used_multiplier,
        condition=condition,
    )


# --- The four fixtures from the spec ---------------------------------------


def test_adult_coat_used_is_45(seeded_app):
    """$60 new at the clothing rate of 0.75."""
    assert value_for("Coat", "clothing_adult", 1, "used") == Decimal("45.00")


def test_blood_pressure_monitor_used_is_37_50(seeded_app):
    """$75 new at the goods rate of 0.50."""
    assert value_for(
        "Blood Pressure Monitor", "womens_hygiene", 1, "used"
    ) == Decimal("37.50")


def test_infant_swaddle_used_is_3_75(seeded_app):
    """$5 new at the clothing rate of 0.75."""
    assert value_for("Swaddle", "clothing_infant", 1, "used") == Decimal("3.75")


def test_pack_n_play_two_used_is_65(seeded_app):
    """$65 new, quantity 2, at the goods rate of 0.50."""
    assert value_for("Pack 'N Play", "baby_mom_items", 2, "used") == Decimal("65.00")


# --- New condition is always full value ------------------------------------


def test_new_condition_ignores_the_used_rate(seeded_app):
    assert value_for("Coat", "clothing_adult", 1, "new") == Decimal("60.00")
    assert value_for("Pack 'N Play", "baby_mom_items", 2, "new") == Decimal("130.00")


# --- The rate is never hardcoded -------------------------------------------


def test_used_rate_comes_from_the_item_not_from_a_constant(seeded_app):
    """The test that fails if anyone hardcodes 0.5 or 0.75.

    Change an item's rate to a value that appears nowhere in the codebase and
    the answer has to follow it.
    """
    from app.extensions import db

    coat = catalog.find_item("Coat", "clothing_adult")
    coat.used_multiplier = 0.9
    db.session.flush()

    assert value_for("Coat", "clothing_adult", 1, "used") == Decimal("54.00")


def test_both_rates_are_live_in_the_catalog(seeded_app):
    """Two different rates really are in use. A single hardcoded constant
    could not produce both of these."""
    clothing = catalog.find_item("Coat", "clothing_adult")
    goods = catalog.find_item("Blood Pressure Monitor", "womens_hygiene")

    assert clothing.used_multiplier != goods.used_multiplier
    assert value_for("Coat", "clothing_adult", 1, "used") == Decimal("45.00")
    assert value_for(
        "Blood Pressure Monitor", "womens_hygiene", 1, "used"
    ) == Decimal("37.50")


def test_every_clothing_item_uses_the_same_rate_as_every_other(seeded_app):
    """All clothing shares one rate and all non-clothing shares another, but
    both are read per item."""
    from app.models import Item

    clothing_rates = {
        item.used_multiplier
        for item in Item.query.all()
        if item.category.startswith("clothing_")
    }
    goods_rates = {
        item.used_multiplier
        for item in Item.query.all()
        if not item.category.startswith("clothing_")
    }

    assert len(clothing_rates) == 1
    assert len(goods_rates) == 1
    assert clothing_rates != goods_rates


# --- Quantity ---------------------------------------------------------------


def test_quantity_never_goes_negative():
    assert valuation.clamp_quantity(-1) == 0
    assert valuation.clamp_quantity(-999) == 0
    assert valuation.clamp_quantity(0) == 0
    assert valuation.clamp_quantity(12) == 12


def test_unparseable_quantity_becomes_zero_rather_than_crashing():
    """This runs on input from a phone in someone's hand."""
    assert valuation.clamp_quantity(None) == 0
    assert valuation.clamp_quantity("") == 0
    assert valuation.clamp_quantity("abc") == 0


def test_zero_quantity_is_worth_nothing(seeded_app):
    assert value_for("Coat", "clothing_adult", 0, "used") == Decimal("0.00")


# --- Missing prices ---------------------------------------------------------


def test_no_price_means_no_value_rather_than_zero():
    """A missing price is unknown, not free. Returning None is what stops the
    batch from being approved."""
    assert valuation.line_value(1, None, 0.5, "used") is None


def test_used_without_a_rate_is_refused():
    with pytest.raises(ValueError):
        valuation.line_value(1, 10, None, "used")


def test_a_price_of_zero_is_worth_zero_without_needing_a_rate():
    """Zero dollars is zero dollars new or used. This is what lets a custom
    item be recorded at zero before anyone has decided its category."""
    assert valuation.line_value(3, 0, None, "used") == Decimal("0.00")
    assert valuation.line_value(3, 0, None, "new") == Decimal("0.00")
    assert valuation.line_value(3, "0.00", 0.5, "used") == Decimal("0.00")


def test_unknown_condition_is_refused():
    with pytest.raises(ValueError):
        valuation.line_value(1, 10, 0.5, "refurbished")


# --- Rounding ---------------------------------------------------------------


def test_value_is_rounded_to_the_cent(seeded_app):
    """Nutribullet Baby is $50.99; half of it is $25.495."""
    assert value_for("Nutribullet Baby", "baby_mom_items", 1, "used") == Decimal(
        "25.50"
    )


def test_money_does_not_drift_when_added_up():
    """Ten dimes are worth exactly one dollar. With floats they would not be."""
    total = valuation.ZERO
    for _ in range(10):
        total += valuation.line_value(1, "0.10", 1.0, "new")
    assert total == Decimal("1.00")
