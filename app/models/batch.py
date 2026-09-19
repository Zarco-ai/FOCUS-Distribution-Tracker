"""What went out, on what day.

  batch      One distribution session. Starts as a draft, becomes committed
             when approved. The date defaults to today and is never typed by
             hand.

  line_item  One item at one quantity in one condition. When a batch is
             committed the line freezes BOTH the unit price and the used
             multiplier it was valued at, so last year's report still adds up
             to last year's number after the catalog changes.

  attendance Head counts for the session. Counts only -- no names, ever.
"""

import datetime

from sqlalchemy import CheckConstraint

from app.constants import (
    CONDITION_NEW,
    STALE_DRAFT_DAYS,
    STATUS_COMMITTED,
    STATUS_DRAFT,
    category_short_label,
)
from app.extensions import db
from app.models.money import Money
from app.services import valuation


class Batch(db.Model):
    __tablename__ = "batch"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(
        db.Date, nullable=False, default=datetime.date.today, index=True
    )
    service_type_id = db.Column(
        db.Integer, db.ForeignKey("service_type.id"), nullable=True
    )

    # Free text about the goods or the session. NOT for names -- the entry
    # form says so out loud and the README explains why.
    note = db.Column(db.Text, nullable=True)

    status = db.Column(
        db.String(20), nullable=False, default=STATUS_DRAFT, index=True
    )
    committed_at = db.Column(db.DateTime, nullable=True)

    service_type = db.relationship("ServiceType")
    lines = db.relationship(
        "LineItem",
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="LineItem.id",
    )
    attendance = db.relationship(
        "Attendance",
        back_populates="batch",
        uselist=False,
        cascade="all, delete-orphan",
    )

    # --- Status ------------------------------------------------------------

    @property
    def is_draft(self):
        return self.status == STATUS_DRAFT

    @property
    def is_committed(self):
        return self.status == STATUS_COMMITTED

    @property
    def is_stale(self):
        """A draft left over from a previous distribution day. Flagged on the
        home screen, never auto-deleted and never auto-approved."""
        if not self.is_draft:
            return False
        cutoff = datetime.date.today() - datetime.timedelta(days=STALE_DRAFT_DAYS)
        return self.date <= cutoff

    # --- Contents ----------------------------------------------------------

    @property
    def active_lines(self):
        """Lines that actually count. A quantity of zero contributes nothing
        and does not appear in the batch."""
        return [line for line in self.lines if line.quantity > 0]

    @property
    def item_count(self):
        return sum(line.quantity for line in self.active_lines)

    @property
    def total_value(self):
        total = valuation.ZERO
        for line in self.active_lines:
            if line.computed_value is not None:
                total += line.computed_value
        return total

    @property
    def unpriced_lines(self):
        """Lines with a quantity but no price yet. These block approval."""
        return [line for line in self.active_lines if line.unit_price_at_time is None]

    @property
    def flagged_lines(self):
        return [line for line in self.active_lines if line.needs_review]

    def __repr__(self):
        return f"<Batch {self.id} {self.date} {self.status}>"


class LineItem(db.Model):
    __tablename__ = "line_item"
    __table_args__ = (
        # Belt and braces. The service layer clamps at zero too.
        CheckConstraint("quantity >= 0", name="ck_line_item_quantity_not_negative"),
    )

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(
        db.Integer, db.ForeignKey("batch.id"), nullable=False, index=True
    )

    # Null for a custom "not on this list" item until someone resolves it in
    # the review queue.
    item_id = db.Column(db.Integer, db.ForeignKey("item.id"), nullable=True)
    custom_name = db.Column(db.String(200), nullable=True)
    custom_note = db.Column(db.Text, nullable=True)

    quantity = db.Column(db.Integer, nullable=False, default=0)
    condition = db.Column(db.String(10), nullable=False, default=CONDITION_NEW)

    # Frozen at commit. Never look these up from the catalog afterwards.
    unit_price_at_time = db.Column(Money, nullable=True)
    used_multiplier_at_time = db.Column(db.Float, nullable=True)
    computed_value = db.Column(Money, nullable=True)

    needs_review = db.Column(db.Boolean, nullable=False, default=False, index=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    batch = db.relationship("Batch", back_populates="lines")
    item = db.relationship("Item")

    # --- Display -----------------------------------------------------------

    @property
    def is_custom(self):
        return self.item_id is None

    @property
    def display_name(self):
        """Name plus category, everywhere, always. On an unresolved custom
        line there is no category yet, so say so."""
        if self.item is not None:
            return self.item.display_name
        return f"{self.custom_name} · not in catalog"

    @property
    def category(self):
        return self.item.category if self.item else None

    @property
    def category_short(self):
        return category_short_label(self.item.category) if self.item else None

    @property
    def report_bucket(self):
        """None for a custom line nobody has sorted yet. The totals view shows
        those separately rather than dropping them."""
        return self.item.report_bucket if self.item else None

    @property
    def is_priced(self):
        return self.unit_price_at_time is not None

    # --- Valuation ---------------------------------------------------------

    def recalculate(self):
        """Recompute computed_value from what is stored ON THIS LINE.

        This deliberately does not consult the catalog. Whoever changes the
        price is responsible for putting it on the line first, which keeps
        committed history frozen.
        """
        self.computed_value = valuation.line_value(
            quantity=self.quantity,
            unit_price=self.unit_price_at_time,
            used_multiplier=self.used_multiplier_at_time,
            condition=self.condition,
        )
        return self.computed_value

    def __repr__(self):
        return f"<LineItem {self.display_name} x{self.quantity} {self.condition}>"


class Attendance(db.Model):
    """Head counts for a session.

    Counts only. There is no name field here and there must never be one --
    FOCUS does not need identities to report, and not storing them is the
    safest way to protect the mothers who come through the door.
    """

    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(
        db.Integer, db.ForeignKey("batch.id"), nullable=False, unique=True
    )

    individuals_served = db.Column(db.Integer, nullable=False, default=0)
    children_served = db.Column(db.Integer, nullable=False, default=0)
    education_participants = db.Column(db.Integer, nullable=False, default=0)

    batch = db.relationship("Batch", back_populates="attendance")

    def __repr__(self):
        return f"<Attendance batch={self.batch_id}>"
