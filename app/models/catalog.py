"""The catalog: what FOCUS gives out, and what it is worth.

Three tables live here.

  service_type  The kind of event a batch belongs to (Diaper Distribution,
                Walk-in, ESL Class ...).

  item          One line of The Center Director's catalog. Uniqueness is
                (name, category), NOT name -- "Pants" exists three times at
                three different prices. Each item carries its own
                used_multiplier, because FOCUS uses 0.50 for goods and 0.75
                for clothing and that rate can change per item.

  item_price    An item's new-condition price, with the date it took effect.
                Prices live in their own table so changing a price adds a row
                instead of overwriting history.
"""

import datetime

from sqlalchemy import UniqueConstraint

from app.constants import (
    PRICE_ENTRY_FIXED,
    PRICE_ENTRY_MANUAL,
    category_label,
    category_short_label,
)
from app.extensions import db
from app.models.money import Money


class ServiceType(db.Model):
    __tablename__ = "service_type"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    active = db.Column(db.Boolean, nullable=False, default=True)

    def __repr__(self):
        return f"<ServiceType {self.name}>"


class Item(db.Model):
    __tablename__ = "item"
    __table_args__ = (
        # The whole reason a $60 adult coat and a $15 infant coat can coexist.
        UniqueConstraint("name", "category", name="uq_item_name_category"),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100), nullable=False)
    report_bucket = db.Column(db.String(50), nullable=False)

    # The used rate for THIS item, read from the seed CSV. Never hardcoded.
    used_multiplier = db.Column(db.Float, nullable=False)

    price_entry = db.Column(db.String(20), nullable=False, default=PRICE_ENTRY_FIXED)

    # Where the source data was unclear, this explains why. Shown to The Center Director
    # as help text next to the price box.
    note = db.Column(db.Text, nullable=True)

    active = db.Column(db.Boolean, nullable=False, default=True)

    prices = db.relationship(
        "ItemPrice",
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="ItemPrice.effective_from",
    )

    # --- Display -----------------------------------------------------------

    @property
    def display_name(self):
        """Always name + category. Never show an item name on its own."""
        return f"{self.name} · {category_short_label(self.category)}"

    @property
    def category_label(self):
        return category_label(self.category)

    @property
    def category_short(self):
        return category_short_label(self.category)

    # --- Pricing -----------------------------------------------------------

    @property
    def needs_manual_price(self):
        return self.price_entry == PRICE_ENTRY_MANUAL

    def current_price(self, on_date=None):
        """The newest price that had taken effect by on_date (today by
        default). Returns None if this item has no price on file -- which is
        normal for the manual-price items whose source data had a hole."""
        on_date = on_date or datetime.date.today()
        best = None
        for price in self.prices:
            if price.effective_from <= on_date:
                if best is None or price.effective_from >= best.effective_from:
                    best = price
        return best.unit_price_new if best else None

    def set_price(self, unit_price_new, effective_from=None):
        """Record a new price. Adds a row, never edits an old one, so every
        previously committed line keeps reporting the number it was worth."""
        effective_from = effective_from or datetime.date.today()
        price = ItemPrice(
            item=self,
            unit_price_new=unit_price_new,
            effective_from=effective_from,
        )
        db.session.add(price)
        return price

    def __repr__(self):
        return f"<Item {self.name} ({self.category})>"


class ItemPrice(db.Model):
    __tablename__ = "item_price"

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(
        db.Integer, db.ForeignKey("item.id"), nullable=False, index=True
    )

    # Nullable on purpose. Several items in the source sheet have no price at
    # all (Stroller, Toys Large, Toys Small ...). A NULL row records "as of
    # this date we know of no price for this item", which is different from
    # having no row at all.
    unit_price_new = db.Column(Money, nullable=True)

    effective_from = db.Column(db.Date, nullable=False, default=datetime.date.today)

    item = db.relationship("Item", back_populates="prices")

    def __repr__(self):
        return f"<ItemPrice item={self.item_id} {self.unit_price_new} from {self.effective_from}>"


# Re-exported so callers can write `from app.models.catalog import ...` and get
# the price-entry vocabulary in the same import.
__all__ = [
    "ServiceType",
    "Item",
    "ItemPrice",
    "PRICE_ENTRY_FIXED",
    "PRICE_ENTRY_MANUAL",
]
