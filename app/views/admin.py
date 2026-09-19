"""Item management, the "Needs a price" list, settings, and the audit log.

The Center Director runs this herself. Adding a diaper is a form on this screen, not a
phone call to Christopher.
"""

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.constants import (
    CATEGORY_ORDER,
    COMMIT_MODES,
    PRICE_ENTRY_CHOICES,
    REPORT_BUCKETS,
)
from app.extensions import db
from app.models import Item, get_commit_mode, set_commit_mode
from app.services import audit, catalog

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/items")
def items():
    """The whole catalog, including deactivated items."""
    search = (request.args.get("q") or "").strip().lower()
    all_items = catalog.all_items()

    if search:
        all_items = [
            item
            for item in all_items
            if search in item.name.lower() or search in item.category.lower()
        ]

    return render_template(
        "admin/items.html",
        items=all_items,
        search=search,
        needs_price_count=len(catalog.items_needing_a_price()),
    )


@admin_bp.route("/items/new", methods=["GET", "POST"])
def new_item():
    if request.method == "POST":
        try:
            item = catalog.create_item(
                name=request.form.get("name"),
                category=request.form.get("category"),
                report_bucket=request.form.get("report_bucket"),
                used_multiplier=request.form.get("used_multiplier"),
                price_entry=request.form.get("price_entry"),
                unit_price_new=request.form.get("unit_price_new"),
                note=request.form.get("note"),
            )
        except catalog.CatalogError as error:
            flash(str(error), "error")
            return render_template(
                "admin/item_form.html",
                item=None,
                form=request.form,
                categories=_category_choices(),
                report_buckets=REPORT_BUCKETS,
                price_entry_choices=PRICE_ENTRY_CHOICES,
            )

        flash(f"Added {item.display_name}.", "success")
        return redirect(url_for("admin.items"))

    return render_template(
        "admin/item_form.html",
        item=None,
        form={},
        categories=_category_choices(),
        report_buckets=REPORT_BUCKETS,
        price_entry_choices=PRICE_ENTRY_CHOICES,
    )


@admin_bp.route("/items/<int:item_id>", methods=["GET", "POST"])
def edit_item(item_id):
    item = db.get_or_404(Item, item_id)

    if request.method == "POST":
        try:
            catalog.update_item(
                item,
                name=request.form.get("name"),
                category=request.form.get("category"),
                report_bucket=request.form.get("report_bucket"),
                used_multiplier=request.form.get("used_multiplier"),
                price_entry=request.form.get("price_entry"),
                note=request.form.get("note"),
                active=request.form.get("active") == "on",
            )
        except catalog.CatalogError as error:
            flash(str(error), "error")
        else:
            flash(f"Saved {item.display_name}.", "success")
            return redirect(url_for("admin.items"))

    return render_template(
        "admin/item_form.html",
        item=item,
        form={},
        categories=_category_choices(),
        report_buckets=REPORT_BUCKETS,
        price_entry_choices=PRICE_ENTRY_CHOICES,
        history=audit.history_for("item", item.id),
    )


@admin_bp.route("/items/<int:item_id>/price", methods=["POST"])
def change_price(item_id):
    """Set a new price. Adds a row to item_price -- old batches keep their
    old numbers."""
    item = db.get_or_404(Item, item_id)

    try:
        catalog.change_price(item, request.form.get("unit_price_new"))
    except catalog.CatalogError as error:
        flash(str(error), "error")
    else:
        flash(
            f"New price for {item.display_name}. Batches approved before today "
            f"keep the price they were approved at.",
            "success",
        )

    return redirect(request.referrer or url_for("admin.items"))


@admin_bp.route("/needs-price")
def needs_price():
    """Every manual-price item and the note explaining why.

    This list is the agenda for the next conversation with The Center Director. It should
    shrink as she supplies real values.
    """
    return render_template(
        "admin/needs_price.html",
        items=catalog.items_needing_a_price(),
    )


@admin_bp.route("/settings", methods=["GET", "POST"])
def settings():
    """Right now: which commit mode to use. All three work."""
    if request.method == "POST":
        mode = request.form.get("commit_mode")
        if mode in COMMIT_MODES:
            set_commit_mode(mode)
            db.session.commit()
            flash("Saved.", "success")
        else:
            flash("Unknown mode.", "error")
        return redirect(url_for("admin.settings"))

    return render_template("admin/settings.html", current_mode=get_commit_mode())


@admin_bp.route("/audit")
def audit_log():
    return render_template("admin/audit.html", entries=audit.recent_changes(200))


def _category_choices():
    """Categories already in use, plus the standard ones, so a new category is
    still possible by typing one."""
    in_use = catalog.categories_in_use()
    extra = [slug for slug in CATEGORY_ORDER if slug not in in_use]
    return in_use + extra
