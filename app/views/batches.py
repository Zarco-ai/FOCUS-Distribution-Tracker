"""Looking at batches that have already been approved."""

from flask import Blueprint, render_template

from app.extensions import db
from app.models import Batch
from app.services import audit

batches_bp = Blueprint("batches", __name__)


@batches_bp.route("/batches")
def list_batches():
    return render_template(
        "batches/list.html",
        batches=Batch.query.order_by(Batch.date.desc(), Batch.id.desc()).all(),
    )


@batches_bp.route("/batches/<int:batch_id>")
def view_batch(batch_id):
    """One committed batch, with its correction history.

    Lines are still editable from the review screen; every change made here
    after approval shows up in the history at the bottom of the page.
    """
    batch = db.get_or_404(Batch, batch_id)

    history = []
    for line in batch.lines:
        history.extend(audit.history_for("line_item", line.id))
    history.sort(key=lambda entry: entry.changed_at, reverse=True)

    return render_template("batches/detail.html", batch=batch, history=history)
