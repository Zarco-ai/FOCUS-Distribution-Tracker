"""The home screen: start counting, or pick up something unfinished."""

import datetime

from flask import Blueprint, redirect, render_template, request, url_for

from app.constants import STATUS_COMMITTED
from app.extensions import db
from app.models import Batch
from app.services import batches as batch_service

home_bp = Blueprint("home", __name__)


@home_bp.route("/")
def index():
    drafts = batch_service.draft_batches()

    recent = (
        Batch.query.filter_by(status=STATUS_COMMITTED)
        .order_by(Batch.committed_at.desc())
        .limit(5)
        .all()
    )

    return render_template(
        "home.html",
        stale_drafts=[b for b in drafts if b.is_stale],
        fresh_drafts=[b for b in drafts if not b.is_stale],
        recent_batches=recent,
        today=datetime.date.today(),
    )


@home_bp.route("/batch/new", methods=["POST"])
def new_batch():
    """Start counting. One tap -- the service type is picked later."""
    batch = batch_service.open_batch()
    db.session.commit()
    return redirect(url_for("entry.entry_screen", batch_id=batch.id))


@home_bp.route("/batch/resume", methods=["POST"])
def resume_today():
    """Open today's batch, starting one if there isn't one yet."""
    batch = batch_service.get_or_start_todays_batch()
    db.session.commit()
    return redirect(url_for("entry.entry_screen", batch_id=batch.id))


@home_bp.route("/batch/<int:batch_id>/discard", methods=["POST"])
def discard(batch_id):
    batch = db.get_or_404(Batch, batch_id)
    if batch.is_draft and request.form.get("confirm") == "yes":
        batch_service.discard_batch(batch)
    return redirect(url_for("home.index"))
