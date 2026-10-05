# FOCUS Distribution Tracker — what it does, and what it does not

A plain-language list of everything this prototype can do today, and everything
it deliberately or not-yet cannot. Nothing here is a promise about a future
version; it is a description of the software as it currently stands.

Last updated: September 28, 2026.

---

## In one paragraph

It replaces the paper tally and the spreadsheet. Someone stands at the table
with a phone or a laptop, taps quantities as goods go out, and approves the
session at the end. The app values everything from a catalog of 119 items,
keeps used goods at the right fraction of new, adds up the month by report
bucket, and exports a CSV. It stores **no personal information about the people
served** — attendance is counts only, and that is a deliberate design boundary,
not an oversight.

---

## What it has

### Counting

- **A catalog of 119 items**, loaded from the FOCUS item sheet, grouped into
  collapsible categories with a search box.
- **Tap counting.** `+` / `−` buttons and a large numeric keypad, sized for a
  phone held in one hand. Every control is at least 44×44 pixels.
- **New / Used per item.** The same item can be counted both ways in one
  session; each side keeps its own quantity and its own price, and a chip under
  the row shows what is counted on the side you are not looking at.
- **Live totals.** Item count and dollar value update at the bottom of the
  screen as you count, without reloading the page.
- **Manual prices** for items whose value varies (strollers, car seats, toys).
  The price box appears when the quantity goes above zero.
- **The same item twice at two different values.** A $40 umbrella stroller and a
  $300 travel system in the same session are two separate lines.
- **"Add item not on this list."** A name, a quantity, an optional price and an
  optional note. It is recorded immediately and sorted out later.
- **Search** that filters as you type and opens whichever category it finds.

### Valuing

- **Fair market value per item**, from the catalog, frozen onto each line the
  moment a session is approved. Changing a price in the catalog afterwards never
  moves a number that has already been reported.
- **Used goods valued at each item's own rate** (0.50 for most goods, 0.75 for
  clothing). The rates live in the data, never in the code, so they can be
  changed per item without a developer.
- **Money stored in whole cents**, so a month of additions never drifts by a
  penny.
- **Price history.** Changing an item's price adds a new price with a start
  date; it does not overwrite the old one.

### Reviewing and approving

- **A review screen** listing every line with its quantity, condition, unit
  price, used rate and value, all editable, with the session total.
- **Attendance:** individuals, children and class participants. **Counts only.**
- **A note field** for the session, with a printed reminder not to write names.
- **Three approval modes**, switchable in Settings: approve each batch, approve
  and immediately start the next one, or save automatically with no approval
  step at all.
- **Nothing is ever held up over a missing price.** A session approves with the
  quantities intact, and anything not yet valued goes to the review queue.
- **Corrections to an approved session are written to a change log** — old
  value, new value, when — and shown on the batch's own page.

### The review queue

- **One list of everything unfinished**, in two parts: catalog items approved
  before anyone knew their price, and custom items waiting to be matched to a
  real catalog entry.
- **A $0.00 line is always in the queue**, however it got there — never priced,
  priced at zero, or corrected back down to zero later, as many times as it
  happens. Zero means "nobody has decided yet", not "free".
- **Finishing a line puts the value back into the session it was counted in**,
  on the date it was counted, so last month's report does not change because
  something was priced this month.
- **An approved session still holding a $0.00 line is flagged on the home
  screen** with a "Needs Review" marker, under *Recently approved*.

### Reporting

- **Totals for any date range**, by report bucket, with the combined
  Clothing / Hygiene / Household Goods column FOCUS North America asks for.
  Diapers, formula and food stay in their own columns and are never rolled in.
- **CSV export** of every line in the range, including the frozen price and used
  rate each line was valued at.
- **Draft sessions are never counted** in totals until approved.
- **Custom items that have not been sorted yet are shown separately** rather
  than being dropped or guessed into a bucket.

### Managing the catalog

- **Add, rename, deactivate items**; change a price; change a used rate.
- **"Needs a price"** — the list of items with no trustworthy value yet, each
  with the note explaining what was wrong in the source sheet.
- **Item names that repeat across categories are always shown with their
  category** (`Coat · Adult` vs `Coat · Infant`), everywhere, without exception.
- **A change history** of every edit to approved data and to the catalog.

### Practical

- **Works on a phone** over the office wifi, and on a laptop, from the same
  install.
- **Unfinished sessions from an earlier day** are flagged on the home screen with
  Resume and Discard. Nothing is ever deleted automatically.
- **No internet connection required.** It runs on one machine.
- **220 automated tests** covering valuation, the approval rules, the review
  queue, the screens and the privacy boundary.

---

## What it does not have

### Deliberately not, and should stay that way

- **Any personal information about the people served.** No names, no client
  records, no addresses, no demographics. Attendance is counts only and the
  database has no column to put a name in. This is the point, not a gap.
- **Anything AI-powered.**
- **Donor-facing pages.**

### Not yet, and would need a decision first

- **No login.** Anyone who can reach the app can use all of it. On a private
  office network with one person using it that is a reasonable trade; the moment
  it is reachable from anywhere else it is not. There is also therefore no
  record of *who* made a change — only what changed and when.
- **No hosting.** It runs on one laptop, started by hand. There is no server, no
  domain, no app store.
- **No backups.** The whole database is a single file; copying it somewhere safe
  is currently a manual job.
- **The full monthly report table.** Totals shows report buckets and the
  combined column; the real FOCUS North America form has more columns and we do
  not have all of them yet.
- **No way to add a service type from the screen.** The nine that exist
  (Diaper Distribution, Early Distribution, ESL Class, Nutrition Class, Intake,
  Walk-in, Volunteer Help, Bike Giveaway, Transportation) are set up at install
  time. A tenth needs a developer.
- **No editing of report buckets or categories as a list.** Categories are typed
  per item, and report buckets are fixed at the six FOCUS reports on.
- **No printing or PDF.** Export the CSV and print from a spreadsheet.
- **No photos** of donated items.
- **No inventory on hand.** It records what went *out*; it does not track what
  is in the closet, what came in, or what is running low.
- **No multi-site support.** One location, one catalog, one set of totals.
- **No undo.** A correction to an approved session is logged, not reversible in
  one click, and a discarded draft is gone.
- **No offline queue.** If the laptop running it is off, the phone cannot count.
- **No scheduled or emailed reports.**
- **English only.**

---

## The numbers as they stand

| | |
|---|---|
| Catalog items | 119 |
| Items still needing a real price | 10 (listed at *Needs a price*) |
| Report buckets | 6 |
| Service types | 9 |
| Approval modes | 3 |
| Automated tests | 220 |

---

Questions worth asking before this goes any further are in
[POTENTIAL_ISSUES.md](POTENTIAL_ISSUES.md). How it all works, in detail, is in
[HANDBOOK.md](HANDBOOK.md).
