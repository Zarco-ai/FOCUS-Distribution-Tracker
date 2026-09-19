"""The core screen: counting items into a batch.

This is the screen The Center Director uses standing up, possibly holding a baby.
Everything else in the app is secondary to it.

The page is rendered server-side with every item and its current quantity.
The +/- buttons, the keypad and the New/Used toggle then talk to
update_line() below, which returns the new line value and the new batch total
as JSON so the footer can update without a page reload.
"""

import datetime

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from app.constants import (
    COMMIT_MODE_AUTO,
    CONDITION_NEW,
    CONDITION_USED,
    CONDITIONS,
)
from app.extensions import db
from app.models import Batch, Item, LineItem, ServiceType, get_commit_mode
from app.services import batches as batch_service
from app.services import catalog
from app.services.valuation import parse_price

entry_bp = Blueprint("entry", __name__)


@entry_bp.route("/batch/<int:batch_id>")
def entry_screen(batch_id):
    batch = db.get_or_404(Batch, batch_id)

    if batch.is_committed and not _auto_mode_today(batch):
        # Approved batches are read-only. Corrections happen on the batch page
        # so they go through the audit log.
        return redirect(url_for("batches.view_batch", batch_id=batch.id))

    items = catalog.active_items()
    rows_by_item = _rows_for(batch, items)

    return render_template(
        "entry/entry.html",
        batch=batch,
        groups=[
            (slug, [rows_by_item[item.id] for item in group_items])
            for slug, group_items in catalog.group_by_category(items)
        ],
        service_types=ServiceType.query.filter_by(active=True)
        .order_by(ServiceType.name)
        .all(),
        blocking_reasons=batch_service.blocking_reasons(batch),
    )


@entry_bp.route("/api/batch/<int:batch_id>/line", methods=["POST"])
def update_line(batch_id):
    """Set the quantity, condition or price of one item. Returns JSON.

    Every +, -, keypad OK, toggle flip and price keystroke lands here.
    """
    batch = db.get_or_404(Batch, batch_id)
    payload = request.get_json(silent=True) or {}

    item = db.session.get(Item, payload.get("item_id"))
    if item is None:
        return jsonify({"ok": False, "error": "That item no longer exists."}), 404

    condition = payload.get("condition")
    if condition is not None and condition not in CONDITIONS:
        return jsonify({"ok": False, "error": "Unknown condition."}), 400

    try:
        line = batch_service.set_line(
            batch,
            item,
            quantity=payload.get("quantity"),
            condition=condition,
            unit_price=parse_price(payload.get("unit_price")),
        )
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400

    db.session.commit()
    saved = batch_service.maybe_autocommit(batch)

    return jsonify(
        {
            "ok": True,
            "line": _line_json(line),
            "batch": _batch_json(batch),
            "auto_saved": saved,
        }
    )


@entry_bp.route("/api/batch/<int:batch_id>/line/<int:line_id>", methods=["POST"])
def update_line_by_id(batch_id, line_id):
    """Set the quantity or price of one specific line.

    Used by the extra price groups on a manual-price row, where "the Stroller
    line" is ambiguous -- there may be one at $40 and another at $300.
    """
    batch = db.get_or_404(Batch, batch_id)
    line = LineItem.query.filter_by(id=line_id, batch_id=batch.id).first_or_404()

    payload = request.get_json(silent=True) or {}

    try:
        batch_service.update_draft_line(
            line,
            quantity=payload.get("quantity"),
            unit_price=parse_price(payload.get("unit_price")),
        )
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400

    db.session.commit()
    saved = batch_service.maybe_autocommit(batch)

    return jsonify(
        {
            "ok": True,
            "line": _line_json(line),
            "batch": _batch_json(batch),
            "auto_saved": saved,
        }
    )


@entry_bp.route("/batch/<int:batch_id>/price-group", methods=["POST"])
def add_price_group(batch_id):
    """Record the same item again at a different value."""
    batch = db.get_or_404(Batch, batch_id)

    item = db.session.get(Item, _as_int(request.form.get("item_id")))
    if item is None:
        flash("That item no longer exists.", "error")
        return redirect(url_for("entry.entry_screen", batch_id=batch.id))

    try:
        batch_service.add_price_group(
            batch, item, condition=request.form.get("condition") or CONDITION_NEW
        )
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("entry.entry_screen", batch_id=batch.id))

    db.session.commit()
    return redirect(
        url_for("entry.entry_screen", batch_id=batch.id) + f"#item-{item.id}"
    )


@entry_bp.route("/batch/<int:batch_id>/price-group/<int:line_id>/remove",
                methods=["POST"])
def remove_price_group(batch_id, line_id):
    batch = db.get_or_404(Batch, batch_id)
    line = LineItem.query.filter_by(id=line_id, batch_id=batch.id).first_or_404()
    item_id = line.item_id

    try:
        batch_service.remove_line(line)
        db.session.commit()
    except ValueError as error:
        flash(str(error), "error")

    anchor = f"#item-{item_id}" if item_id else ""
    return redirect(url_for("entry.entry_screen", batch_id=batch.id) + anchor)


@entry_bp.route("/batch/<int:batch_id>/service-type", methods=["POST"])
def set_service_type(batch_id):
    """Pick the kind of session. Optional while counting, required to approve."""
    batch = db.get_or_404(Batch, batch_id)

    raw = request.form.get("service_type_id") or request.json.get("service_type_id")
    batch.service_type_id = int(raw) if raw else None
    db.session.commit()

    batch_service.maybe_autocommit(batch)

    if request.is_json:
        return jsonify({"ok": True, "batch": _batch_json(batch)})
    return redirect(url_for("entry.entry_screen", batch_id=batch.id))


@entry_bp.route("/batch/<int:batch_id>/custom-item", methods=["POST"])
def add_custom_item(batch_id):
    """Add something that is not in the catalog.

    Separate from the keypad: the keypad sets a quantity for an item that
    already exists, this creates a line for one that does not.
    """
    batch = db.get_or_404(Batch, batch_id)

    try:
        batch_service.add_custom_line(
            batch,
            name=request.form.get("custom_name"),
            quantity=request.form.get("quantity", 1),
            unit_price=parse_price(request.form.get("unit_price")),
            note=request.form.get("note"),
            condition=request.form.get("condition", CONDITION_NEW),
        )
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("entry.entry_screen", batch_id=batch.id))

    db.session.commit()
    flash("Added. It is marked for review so you can fill in the details later.",
          "success")
    return redirect(url_for("entry.entry_screen", batch_id=batch.id))


# --- Helpers ---------------------------------------------------------------


def _auto_mode_today(batch):
    """In auto mode today's batch stays open for more counting even though it
    has already been saved."""
    return (
        get_commit_mode() == COMMIT_MODE_AUTO
        and batch.date == datetime.date.today()
    )


def _rows_for(batch, items):
    """One view-model per catalog item, carrying whatever this batch already
    has for it -- in BOTH conditions.

    An item can be counted new and used in the same batch, so each row holds a
    quantity, a price and a value for each condition. The row shows one at a
    time and the New/Used toggle switches between them.
    """
    rows = {}
    for item in items:
        catalog_price = item.current_price()

        by_condition = {}
        for condition in CONDITIONS:
            found = batch_service.lines_for(batch, item.id, condition)
            line = found[0] if found else None

            by_condition[condition] = {
                "quantity": line.quantity if line else 0,
                # A manual item with a price on file is pre-filled and
                # editable. One with no price starts empty.
                "unit_price": line.unit_price_at_time if line else catalog_price,
                "value": line.computed_value if line else None,
                # Everything after the first line: the same item recorded again
                # at a different value. Only manual-price items get these.
                "extras": [
                    {
                        "id": extra.id,
                        "quantity": extra.quantity,
                        "unit_price": extra.unit_price_at_time,
                        "value": extra.computed_value,
                    }
                    for extra in found[1:]
                ],
            }

        # Which condition the row shows on arrival: whichever one she has
        # actually counted, preferring New when both or neither are counted.
        shown = CONDITION_NEW
        if (
            by_condition[CONDITION_NEW]["quantity"] == 0
            and by_condition[CONDITION_USED]["quantity"] > 0
        ):
            shown = CONDITION_USED

        rows[item.id] = {
            "item": item,
            "by_condition": by_condition,
            "shown": shown,
            "catalog_price": catalog_price,
            "manual": item.needs_manual_price,
            # A manual item with a price on file needs confirming rather than
            # typing from scratch. The row says which.
            "prefilled": item.needs_manual_price and catalog_price is not None,
        }
    return rows


def _line_json(line):
    return {
        "id": line.id,
        "item_id": line.item_id,
        "quantity": line.quantity,
        "condition": line.condition,
        "unit_price": _decimal_str(line.unit_price_at_time),
        "value": _decimal_str(line.computed_value),
        "needs_price": line.unit_price_at_time is None and line.quantity > 0,
    }


def _batch_json(batch):
    reasons = batch_service.blocking_reasons(batch)
    return {
        "item_count": batch.item_count,
        "total_value": _decimal_str(batch.total_value),
        "ready": not reasons,
        "reasons": reasons,
        "status": batch.status,
    }


def _decimal_str(value):
    """Decimals do not survive JSON. Send them as strings so no rounding
    happens on the way to the browser."""
    return None if value is None else f"{value:.2f}"


def _as_int(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
