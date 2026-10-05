"""The review queue: finishing lines that were counted before they were known.

Two kinds of line end up here, and they need different things:

  A custom item -- "not on this list". She types a name mid-distribution and
  moves on; she is not going to stop and pick a report bucket while someone is
  waiting. It needs an identity: a catalog item, and with it a category, a
  report bucket and a used rate. resolve_line() does that.

  A catalog item approved without a price -- a stroller whose value nobody knew
  at the time. It already has its identity. All it needs is the number.
  price_line() does that.

Either way the batch keeps the date it was entered on. Finishing a line here
never moves it into the month it was finished in.

And either way, a line is only finished once it is worth something. A price of
zero leaves it on this list, however it got there -- see LineItem.needs_price.
"""

from app.constants import CONDITION_USED
from app.extensions import db
from app.models import LineItem
from app.models.money import to_money
from app.services import audit
from app.services import batches as batch_service
from app.services import catalog


def flagged_lines():
    """Everything still waiting to be finished, oldest first, because the
    oldest ones are the ones she is most likely to have forgotten."""
    return (
        LineItem.query.filter_by(needs_review=True)
        .join(LineItem.batch)
        .order_by(LineItem.id)
        .all()
    )


def flagged_count():
    return LineItem.query.filter_by(needs_review=True).count()


def price_line(line, unit_price=None):
    """Put a price on a catalog line that was approved without one.

    This is the other half of approving a batch with an unpriced item in it: the
    quantity was recorded then, the value is recorded now, and it lands on the
    line in the batch it was counted in, so that batch's total and the month it
    belongs to both pick it up.
    """
    if line.is_custom:
        raise ValueError(
            "This item is not in the catalog yet, so match it to one first."
        )

    if unit_price is None:
        unit_price = line.item.current_price()
    if unit_price is None:
        raise ValueError(f"Type a price for {line.display_name}.")

    was_committed = line.batch.is_committed
    label = f"{line.display_name} in batch {line.batch_id}"

    old_price = line.unit_price_at_time
    old_value = line.computed_value

    line.unit_price_at_time = to_money(unit_price)
    # Only the price was missing. The rate was snapshotted when the item was
    # counted and stays snapshotted -- re-reading it here would let a catalog
    # change move the value of something already committed. The fallback is for
    # a line that somehow never got one.
    if line.used_multiplier_at_time is None:
        line.used_multiplier_at_time = line.item.used_multiplier
    line.recalculate()
    # A real number finishes the line and takes it out of the queue. A zero does
    # not, so it stays on this list until it has a value -- the one rule, in the
    # one place, whichever screen the number was typed on.
    batch_service.sync_review_flag(line)

    # Only audit when this changes data that has already been reported on.
    if was_committed:
        audit.record_change(
            table_name="line_item",
            record_id=line.id,
            field="unit_price_at_time",
            old_value=old_price,
            new_value=line.unit_price_at_time,
            description=f"Priced {label}",
        )
        audit.record_change(
            table_name="line_item",
            record_id=line.id,
            field="computed_value",
            old_value=old_value,
            new_value=line.computed_value,
            description=f"Priced {label}",
        )

    db.session.commit()
    return line


def resolve_line(line, item=None, unit_price=None, new_item_fields=None):
    """Finish a custom line by giving it an identity.

    Give it either an existing catalog `item`, or `new_item_fields` to create
    one. Either way the line picks up that item's used rate, gets a price, and
    stops being flagged. The batch date is untouched -- it keeps the day it was
    entered on.

    A catalog line already has its identity; use price_line() for those.
    """
    if not line.is_custom:
        raise ValueError(
            f"{line.display_name} is already in the catalog. It is waiting for a "
            f"price, not for an item to match."
        )

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
    line.recalculate()
    # It has an identity now, so the only thing that can still hold it in the
    # queue is having no value -- same rule as a catalog line.
    batch_service.sync_review_flag(line)

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
