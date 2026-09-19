"""A column type for dollar amounts.

Money is stored in the database as a whole number of CENTS in an INTEGER
column, and handed to Python as a Decimal in dollars.

Why: floats cannot hold 0.10 exactly, so adding up a month of donated goods
with floats slowly drifts, and a donor report is not a place for drift.
Integers add up perfectly, and SQL SUM() still works on them.

The one thing to know when debugging: if you open the database by hand,

    sqlite3 instance/focus.db "select computed_value from line_item"

you will see 4500, not 45.00. That is $45.00 in cents. Divide by 100.
"""

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import types

CENTS = Decimal("100")
PENNY = Decimal("0.01")


def to_money(value):
    """Round any number-ish value to a 2 decimal place Decimal of dollars."""
    if value is None:
        return None
    return Decimal(str(value)).quantize(PENNY, rounding=ROUND_HALF_UP)


class Money(types.TypeDecorator):
    """Dollars in Python, whole cents in SQLite."""

    impl = types.Integer
    cache_ok = True

    def process_bind_param(self, value, dialect):
        """Python -> database."""
        if value is None:
            return None
        dollars = Decimal(str(value))
        return int((dollars * CENTS).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    def process_result_value(self, value, dialect):
        """Database -> Python."""
        if value is None:
            return None
        return (Decimal(value) / CENTS).quantize(PENNY)
