"""Review and approve a batch, and work through the review queue."""

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.constants import (
    COMMIT_MODE_PER_MOTHER,
    CONDITIONS,
    REPORT_BUCKETS,
)
from app.extensions import db
from app.models import Batch, Item, LineItem, get_commit_mode
from app.services import batches as batch_service
from app.services import catalog
from app.services import review as review_service
from app.services.valuation import parse_price


review_bp = Blueprint("review", __name__)


@review_bp.route("/batch/<int:batch_id>/review")
def review_screen(batch_id):
    """Every line, its quantity, condition, unit price and value, plus the
    batch total. Everything on this page is editable."""
    batch = db.get_or_404(Batch, batch_id)

    from app.models import ServiceType

    return render_template(
        "review/review.html",
        batch=batch,
        lines=batch.active_lines,
        blocking_reasons=batch_service.blocking_reasons(batch),
        service_types=ServiceType.query.filter_by(active=True)
        .order_by(ServiceType.name)
        .all(),
    )


@review_bp.route("/batch/<int:batch_id>/review/lines", methods=["POST"])
def edit_lines(batch_id):
    """Save the whole review table at once.

    One form covers every line, so the fields are named quantity-<line id>,
    condition-<line id> and unit_price-<line id>. The Remove buttons submit the
    same form with remove=<line id>.
    """
    batch = db.get_or_404(Batch, batch_id)

    remove_id = request.form.get("remove")
    if remove_id:
        line = LineItem.query.filter_by(
            id=int(remove_id), batch_id=batch.id
        ).first_or_404()
        try:
            batch_service.remove_line(line)
            db.session.commit()
            flash("Line removed.", "success")
        except ValueError as error:
            flash(str(error), "error")
        return redirect(url_for("review.review_screen", batch_id=batch.id))

    for line in list(batch.lines):
        quantity = request.form.get(f"quantity-{line.id}")
        condition = request.form.get(f"condition-{line.id}")
        unit_price = parse_price(request.form.get(f"unit_price-{line.id}"))

        if condition and condition not in CONDITIONS:
            flash("Unknown condition.", "error")
            return redirect(url_for("review.review_screen", batch_id=batch.id))

        try:
            _apply_line_edit(batch, line, quantity, condition, unit_price)
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("review.review_screen", batch_id=batch.id))

    db.session.commit()
    flash("Saved.", "success")
    return redirect(url_for("review.review_screen", batch_id=batch.id))


def _apply_line_edit(batch, line, quantity, condition, unit_price):
    """One line's worth of edits, taking the committed/draft difference into
    account."""
    if batch.is_committed:
        # Goes through the audit log.
        batch_service.correct_line(
            line, quantity=quantity, condition=condition, unit_price=unit_price
        )
        return

    # Edits this exact line rather than looking one up by condition, because
    # here The Center Director is correcting the row she is looking at.
    batch_service.update_draft_line(
        line, quantity=quantity, condition=condition, unit_price=unit_price
    )


@review_bp.route("/batch/<int:batch_id>/attendance", methods=["POST"])
def set_attendance(batch_id):
    """Head counts. Counts only -- no names anywhere on this form."""
    batch = db.get_or_404(Batch, batch_id)
    batch_service.set_attendance(
        batch,
        individuals=request.form.get("individuals_served", 0),
        children=request.form.get("children_served", 0),
        education=request.form.get("education_participants", 0),
    )
    db.session.commit()
    flash("Counts saved.", "success")
    return redirect(url_for("review.review_screen", batch_id=batch.id))


@review_bp.route("/batch/<int:batch_id>/note", methods=["POST"])
def set_note(batch_id):
    batch = db.get_or_404(Batch, batch_id)
    batch.note = (request.form.get("note") or "").strip() or None
    db.session.commit()
    return redirect(url_for("review.review_screen", batch_id=batch.id))


@review_bp.route("/batch/<int:batch_id>/approve", methods=["POST"])
def approve(batch_id):
    """Commit the batch. What happens next depends on the commit mode."""
    batch = db.get_or_404(Batch, batch_id)

    try:
        batch_service.commit_batch(batch)
    except batch_service.BatchNotReady as not_ready:
        for reason in not_ready.reasons:
            flash(reason, "error")
        return redirect(url_for("review.review_screen", batch_id=batch.id))

    flash(f"Batch approved. {batch.item_count} items, ${batch.total_value:,.2f}.",
          "success")

    if get_commit_mode() == COMMIT_MODE_PER_MOTHER:
        # Straight into the next one without going back to the home screen.
        next_batch = batch_service.open_batch(service_type_id=batch.service_type_id)
        db.session.commit()
        return redirect(url_for("entry.entry_screen", batch_id=next_batch.id))

    return redirect(url_for("home.index"))


# --- The review queue ------------------------------------------------------


@review_bp.route("/review-queue")
def queue():
    """Custom items waiting to be turned into real catalog entries."""
    return render_template(
        "review/queue.html",
        lines=review_service.flagged_lines(),
        items=catalog.active_items(),
        categories=catalog.categories_in_use(),
        report_buckets=REPORT_BUCKETS,
    )


@review_bp.route("/review-queue/<int:line_id>/resolve", methods=["POST"])
def resolve(line_id):
    line = db.get_or_404(LineItem, line_id)

    item = None
    item_id = request.form.get("item_id")
    new_item_fields = None

    if item_id:
        item = db.session.get(Item, int(item_id))
    elif request.form.get("new_name"):
        new_item_fields = {
            "name": request.form.get("new_name"),
            "category": request.form.get("new_category"),
            "report_bucket": request.form.get("new_report_bucket"),
            "used_multiplier": request.form.get("new_used_multiplier"),
            "price_entry": request.form.get("new_price_entry", "fixed"),
            "unit_price_new": request.form.get("new_unit_price"),
            "note": request.form.get("new_note"),
        }

    try:
        review_service.resolve_line(
            line,
            item=item,
            unit_price=parse_price(request.form.get("unit_price")),
            new_item_fields=new_item_fields,
        )
    except (ValueError, catalog.CatalogError) as error:
        flash(str(error), "error")
        return redirect(url_for("review.queue"))

    flash(f"Resolved as {line.display_name}.", "success")
    return redirect(url_for("review.queue"))
