"""How a line of donated goods turns into a dollar figure.

    line_value = quantity x unit_price_new x (used_multiplier if used else 1.0)

The used multiplier is NOT a constant. FOCUS values used goods at half price
in most categories and at three quarters for clothing, and those rates are
theirs to change. So the rate always arrives here as an argument, read from
the item row it belongs to.

There is no 0.5 and no 0.75 anywhere in this file, and there must never be.
tests/test_valuation.py has a test that changes a seeded rate and asserts the
answer follows it -- that test fails the moment anyone hardcodes one.
"""

from decimal import Decimal

from app.constants import CONDITION_NEW, CONDITION_USED
from app.models.money import to_money

ZERO = Decimal("0.00")

# Goods in new condition are worth their full fair market value.
NEW_CONDITION_MULTIPLIER = Decimal("1")


def effective_multiplier(condition, used_multiplier):
    """The multiplier to apply for this condition.

    New goods are worth full value. Used goods are worth whatever rate the
    item itself carries.
    """
    if condition == CONDITION_USED:
        if used_multiplier is None:
            raise ValueError(
                "A used line needs a used_multiplier. It comes from the item, "
                "never from a constant."
            )
        return Decimal(str(used_multiplier))

    if condition != CONDITION_NEW:
        raise ValueError(f"Unknown condition: {condition!r}")

    return NEW_CONDITION_MULTIPLIER


def line_value(quantity, unit_price, used_multiplier, condition):
    """Dollar value of one line, rounded to the cent.

    Returns None when the price is not known yet -- that is the normal state
    of a manual-price line before The Center Director types a value, and it is what
    stops the batch from being approved.
    """
    if unit_price is None:
        return None
    if not quantity:
        return ZERO

    # Zero dollars is zero dollars whether the goods are new or used, so this
    # does not need a rate. That is what lets a custom item be recorded at a
    # price of zero before anyone has decided which category -- and therefore
    # which used rate -- it belongs to.
    if Decimal(str(unit_price)) == 0:
        return ZERO

    multiplier = effective_multiplier(condition, used_multiplier)
    raw = Decimal(int(quantity)) * Decimal(str(unit_price)) * multiplier
    return to_money(raw)


def clamp_quantity(value):
    """Quantities are whole numbers and never negative.

    Anything unparseable becomes zero rather than raising, because this runs on
    input coming from a phone in someone's hand.
    """
    try:
        quantity = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, quantity)


def parse_price(raw):
    """Read a price out of a box that is allowed to be empty.

    Returns None for anything that is not a usable price -- blank, a stray
    dollar sign, or someone typing "twenty". None means "no price yet", which
    is what keeps the batch from being approved, so guessing here would be
    worse than returning nothing.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = raw.strip().replace("$", "").replace(",", "")
        if not raw:
            return None
    try:
        price = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, price)


def total_value(lines):
    """Sum of computed values, skipping lines that have no price yet."""
    total = ZERO
    for line in lines:
        if line.computed_value is not None:
            total += line.computed_value
    return total


def total_quantity(lines):
    return sum(line.quantity for line in lines)
