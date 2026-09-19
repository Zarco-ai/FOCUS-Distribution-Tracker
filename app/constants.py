"""Shared vocabulary for the whole app.

Everything in here is a *label* or an *enum-ish string*. No prices, no rates.
The used multiplier lives on each item row in the database and is never
hardcoded anywhere in this codebase -- see app/services/valuation.py.
"""

# --- Condition of the goods being distributed -------------------------------

CONDITION_NEW = "new"
CONDITION_USED = "used"
CONDITIONS = (CONDITION_NEW, CONDITION_USED)

# --- How an item's price is decided at entry time ---------------------------

PRICE_ENTRY_FIXED = "fixed"  # trust unit_price_new from the catalog
PRICE_ENTRY_MANUAL = "manual"  # The Center Director types the price for this instance
PRICE_ENTRY_CHOICES = (PRICE_ENTRY_FIXED, PRICE_ENTRY_MANUAL)

# --- Batch lifecycle --------------------------------------------------------

STATUS_DRAFT = "draft"
STATUS_COMMITTED = "committed"
STATUSES = (STATUS_DRAFT, STATUS_COMMITTED)

# A draft older than this many days gets an "Unfinished" banner on the home
# screen. Nothing is ever auto-deleted or auto-committed.
STALE_DRAFT_DAYS = 1

# --- Commit modes -----------------------------------------------------------
# The Center Director picks one of these at the demo. All three work today.
#
#   per_batch  Review -> Approve -> back to the home screen. (default)
#   per_mother Same gate, but approving immediately opens a fresh empty batch
#              on the entry screen so she can keep going without stopping.
#   auto       No approve step. Quantities land in today's committed batch as
#              they are entered.
#
# In every mode a manual-price line without a price is held back from the
# commit, so "no committed line is ever missing a price" is always true.

COMMIT_MODE_PER_BATCH = "per_batch"
COMMIT_MODE_PER_MOTHER = "per_mother"
COMMIT_MODE_AUTO = "auto"
COMMIT_MODES = (COMMIT_MODE_PER_BATCH, COMMIT_MODE_PER_MOTHER, COMMIT_MODE_AUTO)

COMMIT_MODE_LABELS = {
    COMMIT_MODE_PER_BATCH: "Review and approve each batch",
    COMMIT_MODE_PER_MOTHER: "Approve, then start the next one right away",
    COMMIT_MODE_AUTO: "Save entries automatically, no approval step",
}

COMMIT_MODE_HELP = {
    COMMIT_MODE_PER_BATCH: (
        "You count everything, look it over on the review screen, then approve. "
        "Approving takes you back to the home screen."
    ),
    COMMIT_MODE_PER_MOTHER: (
        "Same as above, but approving opens a new empty batch straight away. "
        "Good if you want one batch per person."
    ),
    COMMIT_MODE_AUTO: (
        "Counts are saved as you enter them, with no review step. Items that "
        "need a typed price are still held until you type one."
    ),
}

# --- Report buckets ---------------------------------------------------------
# Each catalog item maps to exactly one bucket. Buckets are what the monthly
# report is built from. Diapers and food are deliberately their own buckets and
# never roll into clothing/hygiene/household.

BUCKET_FORMULA = "formula"
BUCKET_FOOD = "food"
BUCKET_DIAPERS = "diapers"
BUCKET_CLOTHING = "clothing"
BUCKET_HYGIENE = "hygiene"
BUCKET_HOUSEHOLD = "household"

REPORT_BUCKETS = (
    BUCKET_FORMULA,
    BUCKET_FOOD,
    BUCKET_DIAPERS,
    BUCKET_CLOTHING,
    BUCKET_HYGIENE,
    BUCKET_HOUSEHOLD,
)

BUCKET_LABELS = {
    BUCKET_FORMULA: "Baby Formula",
    BUCKET_FOOD: "Food (GIK)",
    BUCKET_DIAPERS: "Individual Diapers",
    BUCKET_CLOTHING: "Clothing",
    BUCKET_HYGIENE: "Hygiene",
    BUCKET_HOUSEHOLD: "Household Goods",
}

# The three buckets that FOCUS North America reports as one combined
# "Clothing / Hygiene / Household Goods" column. Diapers, formula and food are
# reported separately and must never be added into this group.
COMBINED_GOODS_BUCKETS = (BUCKET_CLOTHING, BUCKET_HYGIENE, BUCKET_HOUSEHOLD)

# --- Categories -------------------------------------------------------------
# Categories come from the data, not from this file. These are display labels
# only; an unknown category still works and just gets a title-cased label.
# That is what lets The Center Director add a "diapers" category herself.

CATEGORY_ORDER = (
    "baby_essentials",
    "womens_hygiene",
    "home_goods",
    "baby_mom_items",
    "clothing_adult",
    "clothing_children",
    "clothing_infant",
)

CATEGORY_LABELS = {
    "baby_essentials": "Baby Essentials",
    "womens_hygiene": "Women's Hygiene",
    "home_goods": "Home Goods",
    "baby_mom_items": "Baby & Mom Items",
    "clothing_adult": "Clothing — Adult",
    "clothing_children": "Clothing — Children",
    "clothing_infant": "Clothing — Infant",
}

# Shorter version used on item rows, e.g. "Coat . Adult". Names repeat across
# categories, so this suffix is the only way to tell a $60 adult coat from a
# $15 infant one.
CATEGORY_SHORT_LABELS = {
    "baby_essentials": "Baby",
    "womens_hygiene": "Women's",
    "home_goods": "Home",
    "baby_mom_items": "Baby & Mom",
    "clothing_adult": "Adult",
    "clothing_children": "Children",
    "clothing_infant": "Infant",
}


def category_label(slug):
    """Full display name for a category slug."""
    if slug in CATEGORY_LABELS:
        return CATEGORY_LABELS[slug]
    return (slug or "").replace("_", " ").title()


def category_short_label(slug):
    """Short display name used as a suffix on item rows."""
    if slug in CATEGORY_SHORT_LABELS:
        return CATEGORY_SHORT_LABELS[slug]
    return category_label(slug)


def bucket_label(slug):
    """Display name for a report bucket."""
    if slug in BUCKET_LABELS:
        return BUCKET_LABELS[slug]
    return (slug or "").replace("_", " ").title()


def sort_categories(slugs):
    """Known categories in their intended order, then anything new, A-Z."""
    known = [c for c in CATEGORY_ORDER if c in slugs]
    unknown = sorted(s for s in slugs if s not in CATEGORY_ORDER)
    return known + unknown
