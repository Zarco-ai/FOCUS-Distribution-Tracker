"""The review queue: turning "something not on the list" into real data.

When The Center Director adds a custom item during a distribution she types a name and
moves on -- she is not going to stop and pick a report bucket while someone is
waiting. The line is flagged needs_review and lands here, where it can be
matched to a catalog item (or become a new one) later, without ever changing
the date it was entered on.
"""

import datetime

from app.constants import CONDITION_USED
from app.extensions import db
from app.models import LineItem
from app.models.money import to_money
from app.services import audit, catalog


def flagged_lines():
    """Everything still waiting to be sorted out, oldest first, because the
    oldest ones are the ones she is most likely to have forgotten."""
    return (
        LineItem.query.filter_by(needs_review=True)
        .join(LineItem.batch)
        .order_by(LineItem.id)
        .all()
    )


def flagged_count():
    return LineItem.query.filter_by(needs_review=True).count()


def resolve_line(line, item=None, unit_price=None, new_item_fields=None):
    """Finish a flagged line.

    Give it either an existing catalog `item`, or `new_item_fields` to create
    one. Either way the line picks up that item's used rate, gets a price, and
    stops being flagged. The batch date is untouched -- it keeps the day it was
    entered on.
    """
    if item is None and new_item_fields:
        item = catalog.create_item(**new_item_fields)

    if item is None:
        raise ValueError("Pick an item to match this to, or create a new one.")

    was_committed = line.batch.is_committed
    label = f"custom line '{line.custom_name}' in batch {line.batch_id}"

    if unit_price is None:
        unit_price = item.current_price()
    if unit_price is None and line.unit_price_at_time:
        # Deliberately falsy rather than "is not None": a custom line's price
        # defaults to zero meaning "nobody has decided yet", so falling back to
        # it would quietly record the goods as worthless. Better to ask.
        unit_price = line.unit_price_at_time

    if unit_price is None:
        raise ValueError(
            f"{item.display_name} has no price on file, so type one here."
        )

    old_value = line.computed_value

    line.item_id = item.id
    line.used_multiplier_at_time = item.used_multiplier
    line.unit_price_at_time = to_money(unit_price)
    line.needs_review = False
    line.reviewed_at = datetime.datetime.now()
    line.recalculate()

    # Only audit when this changes data that has already been reported on.
    if was_committed:
        audit.record_change(
            table_name="line_item",
            record_id=line.id,
            field="item_id",
            old_value=None,
            new_value=item.display_name,
            description=f"Resolved {label}",
        )
        audit.record_change(
            table_name="line_item",
            record_id=line.id,
            field="computed_value",
            old_value=old_value,
            new_value=line.computed_value,
            description=f"Resolved {label}",
        )

    db.session.commit()
    return line


def can_value_used(line):
    """A used custom line has no rate until it is matched to an item, so its
    value is unknown rather than wrong."""
    return not (line.condition == CONDITION_USED and line.used_multiplier_at_time is None)
