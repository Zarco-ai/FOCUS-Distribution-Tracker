"""Opening, filling in, and approving a batch.

The rule that shapes this whole module: a committed line never changes by
accident. While a batch is a draft its lines follow the catalog, because a
draft is still being written. The moment it is committed, the price and the
used rate on every line are frozen, and the only way to change them afterwards
is a correction that writes to the audit log.
"""

import datetime

from app.constants import (
    COMMIT_MODE_AUTO,
    CONDITION_NEW,
    CONDITIONS,
    STATUS_COMMITTED,
    STATUS_DRAFT,
)
from app.extensions import db
from app.models import Attendance, Batch, Item, LineItem, get_commit_mode
from app.models.money import to_money
from app.services import audit, valuation


class BatchNotReady(Exception):
    """Raised when a batch cannot be approved yet. Carries the reasons."""

    def __init__(self, reasons):
        self.reasons = reasons
        super().__init__("; ".join(reasons))


# --- Finding and opening batches -------------------------------------------


def open_batch(date=None, service_type_id=None, note=None):
    """Start a new draft. The date defaults to today and is never typed."""
    batch = Batch(
        date=date or datetime.date.today(),
        service_type_id=service_type_id,
        note=note,
        status=STATUS_DRAFT,
    )
    db.session.add(batch)
    db.session.flush()
    return batch


def draft_batches():
    """Every unfinished batch, newest first."""
    return (
        Batch.query.filter_by(status=STATUS_DRAFT)
        .order_by(Batch.date.desc(), Batch.id.desc())
        .all()
    )


def stale_draft_batches():
    """Drafts left over from a previous day. Flagged, never auto-removed."""
    return [batch for batch in draft_batches() if batch.is_stale]


def todays_working_batch():
    """The batch the entry screen should open.

    In auto mode that is today's batch whether or not it has been saved
    already, because in auto mode entries keep flowing into the same session.
    Otherwise it is the newest draft dated today, if there is one.
    """
    today = datetime.date.today()

    if get_commit_mode() == COMMIT_MODE_AUTO:
        batch = (
            Batch.query.filter_by(date=today)
            .order_by(Batch.id.desc())
            .first()
        )
        if batch is not None:
            return batch
    else:
        batch = (
            Batch.query.filter_by(date=today, status=STATUS_DRAFT)
            .order_by(Batch.id.desc())
            .first()
        )
        if batch is not None:
            return batch

    return None


def get_or_start_todays_batch():
    return todays_working_batch() or open_batch()


# --- Editing lines ----------------------------------------------------------


def lines_for(batch, item_id, condition):
    """Every line for one item in one condition, oldest first.

    Usually there is one. A manual-price item can have several: two strollers
    worth $40 and $300 are two lines, because one quantity and one price cannot
    describe both. Fixed-price items never need this -- their value comes from
    the catalog, so two of them are just a quantity of two.
    """
    matches = [
        line
        for line in batch.lines
        if line.item_id == item_id and line.condition == condition
    ]
    # New lines have no id until the session flushes, so keep those last rather
    # than blowing up on a None comparison.
    matches.sort(key=lambda line: (line.id is None, line.id or 0))
    return matches


def find_line(batch, item_id, condition):
    """The first line for one item and condition -- the one the main row on the
    counting screen edits. Extra prices hang off it and are edited by id."""
    matches = lines_for(batch, item_id, condition)
    return matches[0] if matches else None


def lines_for_item(batch, item_id):
    """Every line this batch has for one item, keyed by condition."""
    found = {}
    for line in batch.lines:
        if line.item_id == item_id:
            found.setdefault(line.condition, []).append(line)
    return found


def add_price_group(batch, item, condition=None, quantity=1):
    """Record the same item a second time at a different value.

    Only for manual-price items. A fixed-price item is worth what the catalog
    says, so two of them are a quantity of two, not two lines.
    """
    _prepare_for_edit(batch)

    condition = condition or CONDITION_NEW
    if condition not in CONDITIONS:
        raise ValueError(f"Unknown condition: {condition!r}")

    if not item.needs_manual_price:
        raise ValueError(
            f"{item.display_name} has a set price, so use the quantity instead "
            f"of adding a second price."
        )

    line = LineItem(
        batch=batch,
        item_id=item.id,
        quantity=valuation.clamp_quantity(quantity),
        condition=condition,
        used_multiplier_at_time=item.used_multiplier,
        # No price yet. The Center Director types this one, and it blocks approval until
        # she does -- exactly like the first one.
        unit_price_at_time=None,
    )
    db.session.add(line)
    line.recalculate()
    db.session.flush()
    return line


def set_line(batch, item, quantity=None, condition=None, unit_price=None):
    """Set the quantity and (for manual items) the price of one item in one
    condition.

    The condition selects WHICH line is being edited, it does not change an
    existing line's condition -- counting a used one never disturbs the new
    ones already counted. Defaults to new.

    Passing None for quantity or price leaves that part alone. Returns the
    line, which may have a quantity of zero; zero lines are kept while drafting
    so the screen remembers a typed price, and are dropped at approval.
    """
    _prepare_for_edit(batch)

    condition = condition or CONDITION_NEW
    if condition not in CONDITIONS:
        raise ValueError(f"Unknown condition: {condition!r}")

    line = find_line(batch, item.id, condition)
    if line is None:
        # Passing batch=batch puts the line into batch.lines for us. Do not
        # also append it -- that would make it show up twice and double the
        # batch total.
        line = LineItem(
            batch=batch,
            item_id=item.id,
            quantity=0,
            condition=condition,
        )
        db.session.add(line)

    if quantity is not None:
        line.quantity = valuation.clamp_quantity(quantity)

    # The used rate always comes from the item, and is re-snapshotted on every
    # edit while the batch is a draft.
    line.used_multiplier_at_time = item.used_multiplier

    if item.needs_manual_price:
        # The Center Director types this one. Only overwrite when a price was actually
        # supplied, so changing the quantity does not wipe the price she typed.
        # Each condition holds its own price -- a used stroller is not simply
        # half of whatever she typed for a new one.
        if unit_price is not None:
            line.unit_price_at_time = to_money(unit_price)
    else:
        # Trusted catalog price, refreshed while the batch is still a draft.
        line.unit_price_at_time = item.current_price()

    line.recalculate()
    db.session.flush()
    return line


def update_draft_line(line, quantity=None, condition=None, unit_price=None):
    """Edit one specific draft line in place.

    This is what the review screen uses. Unlike set_line() it changes the line
    you hand it rather than looking one up by condition, because on the review
    screen The Center Director is correcting a line she is looking at.
    """
    batch = line.batch
    _prepare_for_edit(batch)

    if condition is not None and condition != line.condition:
        if condition not in CONDITIONS:
            raise ValueError(f"Unknown condition: {condition!r}")
        if line.item_id is not None:
            clash = find_line(batch, line.item_id, condition)
            if clash is not None:
                raise ValueError(
                    f"This batch already has a {condition} line for "
                    f"{line.display_name}. Change the quantity on that one "
                    f"instead."
                )
        line.condition = condition

    if quantity is not None:
        line.quantity = valuation.clamp_quantity(quantity)

    if line.item is not None:
        line.used_multiplier_at_time = line.item.used_multiplier
        if line.item.needs_manual_price:
            if unit_price is not None:
                line.unit_price_at_time = to_money(unit_price)
        else:
            line.unit_price_at_time = line.item.current_price()
    elif unit_price is not None:
        # A custom line has no catalog item to read a price or rate from.
        line.unit_price_at_time = to_money(unit_price)

    line.recalculate()
    db.session.flush()
    return line


def set_line_price(line, unit_price):
    """Type a price onto one line. Used by the entry screen and by review."""
    _prepare_for_edit(line.batch)
    line.unit_price_at_time = to_money(unit_price) if unit_price is not None else None
    line.recalculate()
    db.session.flush()
    return line


def add_custom_line(batch, name, quantity=1, unit_price=None, note=None,
                    condition=CONDITION_NEW):
    """Add something that is not in the catalog.

    The line is flagged needs_review and shows up in the review queue, where a
    name, category and price can be filled in later. It keeps the date of the
    batch it was entered in -- the date is never typed by hand.

    The price defaults to zero rather than to nothing. A custom item is
    something The Center Director is adding mid-distribution without knowing what it is
    worth, so making her invent a number before she can approve the batch would
    be worse than recording it at zero and pricing it properly in the review
    queue afterwards.
    """
    _prepare_for_edit(batch)

    name = (name or "").strip()
    if not name:
        raise ValueError("A custom item needs a name.")
    if condition not in CONDITIONS:
        raise ValueError(f"Unknown condition: {condition!r}")

    line = LineItem(
        batch=batch,
        item_id=None,
        custom_name=name,
        custom_note=(note or "").strip() or None,
        quantity=valuation.clamp_quantity(quantity),
        condition=condition,
        unit_price_at_time=to_money(unit_price if unit_price is not None else 0),
        # No catalog item means no used rate of its own yet. The review queue
        # assigns one along with the category. Until then a zero price is worth
        # zero whatever the condition, which is what keeps this line from
        # blocking approval.
        used_multiplier_at_time=None,
        needs_review=True,
    )
    db.session.add(line)
    line.recalculate()

    db.session.flush()
    return line


def remove_line(line):
    """Take a line out of a draft entirely."""
    batch = line.batch
    _prepare_for_edit(batch)

    # Take it out of the batch's own list as well as the database. Deleting it
    # only from the session leaves it sitting in batch.lines until something
    # commits, and until then the batch total still counts it.
    if line in batch.lines:
        batch.lines.remove(line)

    db.session.delete(line)
    db.session.flush()


def set_attendance(batch, individuals=0, children=0, education=0):
    """Head counts for the session. Counts only -- there are no name fields
    here and there must never be any."""
    record = batch.attendance
    if record is None:
        record = Attendance(batch=batch)
        db.session.add(record)

    record.individuals_served = valuation.clamp_quantity(individuals)
    record.children_served = valuation.clamp_quantity(children)
    record.education_participants = valuation.clamp_quantity(education)
    db.session.flush()
    return record


# --- Approving --------------------------------------------------------------


def blocking_reasons(batch):
    """Everything standing between this batch and being approved.

    Returns a list of plain sentences, empty when the batch is ready.
    """
    reasons = []

    if batch.service_type_id is None:
        reasons.append("Pick a service type.")

    if not batch.active_lines:
        reasons.append("Add at least one item.")

    unpriced = batch.unpriced_lines
    if unpriced:
        names = ", ".join(line.display_name for line in unpriced)
        reasons.append(f"These items still need a price: {names}.")

    return reasons


def can_commit(batch):
    return not blocking_reasons(batch)


def commit_batch(batch, when=None):
    """Approve a batch.

    Drops any line whose quantity fell back to zero, freezes the price and the
    used rate on everything that is left, and marks the batch committed.
    """
    reasons = blocking_reasons(batch)
    if reasons:
        raise BatchNotReady(reasons)

    # A quantity of zero contributes nothing and does not appear in the batch.
    for line in list(batch.lines):
        if line.quantity == 0:
            db.session.delete(line)
            batch.lines.remove(line)

    # Freeze. From here on these numbers are history and are never looked up
    # from the catalog again.
    for line in batch.lines:
        line.recalculate()

    if batch.status != STATUS_COMMITTED:
        batch.status = STATUS_COMMITTED
        batch.committed_at = when or datetime.datetime.now()

    db.session.commit()
    return batch


def maybe_autocommit(batch):
    """In auto mode, save as she goes.

    If something is still missing -- no service type, or a manual item with no
    price -- the batch quietly stays a draft and the entry screen says why.
    That is what keeps 'no committed line is ever missing a price' true in
    every mode.
    """
    if get_commit_mode() != COMMIT_MODE_AUTO:
        return False
    if not can_commit(batch):
        return False
    commit_batch(batch)
    return True


def discard_batch(batch):
    """Throw away a draft. Committed batches are never deleted."""
    if batch.is_committed:
        raise ValueError("A committed batch cannot be discarded.")
    db.session.delete(batch)
    db.session.commit()


# --- Correcting committed data ---------------------------------------------


def correct_line(line, quantity=None, condition=None, unit_price=None):
    """Change a line on a batch that has already been approved.

    Every field that actually moves is written to the audit log, along with the
    recomputed value.
    """
    if not line.batch.is_committed:
        raise ValueError("Use set_line() for a draft batch.")

    label = f"{line.display_name} in batch {line.batch_id}"
    changed = False

    if quantity is not None:
        changed |= audit.apply_change(
            line, "quantity", valuation.clamp_quantity(quantity),
            table_name="line_item", description=label,
        )

    if condition is not None:
        if condition not in CONDITIONS:
            raise ValueError(f"Unknown condition: {condition!r}")
        changed |= audit.apply_change(
            line, "condition", condition, table_name="line_item", description=label,
        )

    if unit_price is not None:
        changed |= audit.apply_change(
            line, "unit_price_at_time", to_money(unit_price),
            table_name="line_item", description=label,
        )

    if changed:
        old_value = line.computed_value
        line.recalculate()
        audit.record_change(
            table_name="line_item",
            record_id=line.id,
            field="computed_value",
            old_value=old_value,
            new_value=line.computed_value,
            description=label,
        )
        db.session.commit()

    return line


def _prepare_for_edit(batch):
    """Make sure this batch is safe to write to, or refuse.

    A draft is always fine. A committed batch is not -- with one exception: in
    auto mode today's batch gets saved after every change, so the next item she
    counts has to be able to land in the same batch. Reopening it for a moment
    inside the same session is the honest way to do that, and it is re-saved
    before the request ends.
    """
    if not batch.is_committed:
        return

    if get_commit_mode() == COMMIT_MODE_AUTO and batch.date == datetime.date.today():
        batch.status = STATUS_DRAFT
        batch.committed_at = None
        return

    raise ValueError(
        "This batch has already been approved. Use correct_line() so the "
        "change is written to the audit log."
    )
