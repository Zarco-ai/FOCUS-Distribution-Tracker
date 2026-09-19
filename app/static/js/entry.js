/* The counting screen.
 *
 * Every +, -, keypad entry, New/Used flip and typed price posts to the server
 * and gets back the new line value and the new batch total. Nothing is kept
 * only in the browser -- close the tab mid-batch and everything counted so far
 * is still there.
 *
 * Plain JavaScript on purpose. No build step, no framework. If you can read
 * this file you can change this screen.
 */
(function (window, document) {
  "use strict";

  var list = document.getElementById("entry-list");
  if (!list) {
    return;
  }

  var LINE_URL = list.getAttribute("data-line-url");

  /* Proves the request came from this page and not from some other site the
     browser happens to have open. The server rejects any POST without it.
     Flask-WTF looks for exactly this header name. */
  var CSRF_TOKEN = list.getAttribute("data-csrf-token");

  var OPEN_CATEGORIES_KEY = "focus.openCategories";

  var searchInput = document.getElementById("item-search");
  var searchClear = document.getElementById("search-clear");
  var noResults = document.getElementById("no-results");
  var footerCount = document.getElementById("footer-count");
  var footerTotal = document.getElementById("footer-total");
  var errorBanner = document.getElementById("save-error");

  // --- Talking to the server ------------------------------------------------

  function sendUpdate(row, changes) {
    var payload = {
      item_id: parseInt(row.getAttribute("data-item-id"), 10)
    };
    for (var key in changes) {
      if (Object.prototype.hasOwnProperty.call(changes, key)) {
        payload[key] = changes[key];
      }
    }
    post(row, LINE_URL, payload, function (data) {
      applyLine(row, data.line);
    });
  }

  /* An extra price group is addressed by its own line id, because "the
     Stroller line" is ambiguous once there is one at $40 and one at $300. */
  function sendGroupUpdate(row, group, changes) {
    var url = LINE_URL + "/" + group.getAttribute("data-line-id");
    post(row, url, changes, function (data) {
      applyGroup(row, group, data.line);
    });
  }

  function post(row, url, payload, onLine) {
    row.classList.add("saving");

    fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": CSRF_TOKEN
      },
      body: JSON.stringify(payload)
    })
      .then(function (response) {
        return response.json().then(function (data) {
          if (!response.ok || !data.ok) {
            throw new Error(data.error || "Could not save that.");
          }
          return data;
        });
      })
      .then(function (data) {
        row.classList.remove("saving");
        hideError();
        onLine(data);
        applyBatch(data.batch);
      })
      .catch(function (error) {
        row.classList.remove("saving");
        row.classList.add("save-failed");
        showError(error.message + " Check that the app is still running.");
      });
  }

  function showError(message) {
    if (!errorBanner) {
      return;
    }
    errorBanner.textContent = message;
    errorBanner.hidden = false;
  }

  function hideError() {
    if (errorBanner) {
      errorBanner.hidden = true;
    }
  }

  // --- Putting the answer back on the screen --------------------------------

  /* Store what the server just told us about one condition of one item, then
     redraw the row. The row keeps both conditions at once. */
  function applyLine(row, line) {
    row.classList.remove("save-failed");
    row.setAttribute("data-quantity-" + line.condition, line.quantity);
    row.setAttribute(
      "data-value-" + line.condition,
      line.value === null ? "" : line.value
    );
    row.setAttribute(
      "data-price-" + line.condition,
      line.unit_price === null ? "" : line.unit_price
    );
    renderRow(row);
    updateCategoryBadge(categoryOf(row));
  }

  /* Same idea for one extra price group, which keeps its state on itself
     rather than on the row. */
  function applyGroup(row, group, line) {
    row.classList.remove("save-failed");
    group.setAttribute("data-quantity", line.quantity);
    group.setAttribute("data-value", line.value === null ? "" : line.value);

    var quantityButton = group.querySelector('[data-role="quantity"]');
    if (quantityButton) {
      quantityButton.textContent = line.quantity;
    }

    var valueEl = group.querySelector('[data-role="line-value"]');
    if (valueEl) {
      valueEl.textContent =
        line.quantity > 0 && line.value !== null ? formatMoney(line.value) : "";
    }

    var input = group.querySelector('[data-role="price-input"]');
    if (input && document.activeElement !== input) {
      input.value = line.unit_price === null ? "" : line.unit_price;
    }

    group.classList.toggle(
      "needs-price",
      line.quantity > 0 && line.unit_price === null
    );

    renderRow(row);
    updateCategoryBadge(categoryOf(row));
  }

  function groupsFor(row, condition) {
    var all = row.querySelectorAll('[data-role="price-group"]');
    var mine = [];
    for (var i = 0; i < all.length; i++) {
      if (
        !condition ||
        all[i].getAttribute("data-for-condition") === condition
      ) {
        mine.push(all[i]);
      }
    }
    return mine;
  }

  function groupQuantity(group) {
    return parseInt(group.getAttribute("data-quantity") || "0", 10) || 0;
  }

  function applyBatch(batch) {
    if (footerCount) {
      footerCount.textContent = batch.item_count;
      var word = footerCount.nextElementSibling;
      if (word) {
        word.textContent = batch.item_count === 1 ? "item" : "items";
      }
    }
    if (footerTotal) {
      footerTotal.textContent = formatMoney(batch.total_value);
    }

    var banner = document.getElementById("auto-banner");
    if (banner) {
      if (batch.reasons.length) {
        banner.textContent = "Not saved yet — " + batch.reasons.join(" ");
        banner.className = "banner banner-warn";
      } else {
        banner.textContent = "Saving as you go.";
        banner.className = "banner banner-ok";
      }
    }
  }

  function formatMoney(value) {
    if (value === null || value === undefined) {
      return "";
    }
    return "$" + Number(value).toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  }

  // --- Reading and writing a row's state ------------------------------------

  var CONDITIONS = ["new", "used"];

  /* Which condition the row is currently showing. The other one is still
     there, held in the row's data attributes. */
  function conditionOf(row) {
    return row.getAttribute("data-condition") || "new";
  }

  function otherConditionOf(row) {
    return conditionOf(row) === "new" ? "used" : "new";
  }

  function quantityOf(row, condition) {
    condition = condition || conditionOf(row);
    return parseInt(row.getAttribute("data-quantity-" + condition) || "0", 10) || 0;
  }

  function valueOf(row, condition) {
    return row.getAttribute("data-value-" + (condition || conditionOf(row))) || "";
  }

  function storedPriceOf(row, condition) {
    return row.getAttribute("data-price-" + (condition || conditionOf(row))) || "";
  }

  /* The row's own price box. Extra price groups come after it in the markup,
     so this always finds the main one. */
  function priceOf(row) {
    var input = row.querySelector('[data-role="price-input"]');
    return input ? input.value : null;
  }

  function groupPriceOf(group) {
    var input = group.querySelector('[data-role="price-input"]');
    return input ? input.value : null;
  }

  function isManual(row) {
    return row.getAttribute("data-manual") === "1";
  }

  /* Draw the row for whichever condition it is showing. Everything on screen
     comes from the data attributes, so this is the only place that decides
     what a row looks like. */
  function renderRow(row) {
    var condition = conditionOf(row);
    var other = otherConditionOf(row);
    var quantity = quantityOf(row, condition);
    var otherQuantity = quantityOf(row, other);

    var quantityButton = row.querySelector('[data-role="quantity"]');
    if (quantityButton) {
      quantityButton.textContent = quantity;
    }

    var buttons = row.querySelectorAll(".condition-toggle button");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].classList.toggle(
        "on",
        buttons[i].getAttribute("data-condition") === condition
      );
    }

    var valueEl = row.querySelector('[data-role="line-value"]');
    if (valueEl) {
      var value = valueOf(row, condition);
      valueEl.textContent = quantity > 0 && value !== "" ? formatMoney(value) : "";
    }

    // Extra price groups belong to one condition each. Show only the ones for
    // the side being displayed, and point the "add another" button at it.
    var allGroups = groupsFor(row);
    var extraHere = 0;
    var extraOther = 0;
    for (var g = 0; g < allGroups.length; g++) {
      var belongsTo = allGroups[g].getAttribute("data-for-condition");
      allGroups[g].hidden = belongsTo !== condition;
      if (belongsTo === condition) {
        extraHere += groupQuantity(allGroups[g]);
      } else {
        extraOther += groupQuantity(allGroups[g]);
      }
    }

    var addPriceCondition = row.querySelector('[data-role="add-price-condition"]');
    if (addPriceCondition) {
      addPriceCondition.value = condition;
    }

    // The row counts as "in the batch" if EITHER condition has a quantity,
    // including anything recorded at a second price.
    row.classList.toggle(
      "has-quantity",
      quantity + extraHere > 0 || otherQuantity + extraOther > 0
    );

    // What is counted on the other side, so the toggle never hides work.
    // Anything recorded there at a second price counts too.
    var otherEl = row.querySelector('[data-role="other-condition"]');
    if (otherEl) {
      var otherTotal = otherQuantity + extraOther;
      otherEl.hidden = otherTotal === 0;
      if (otherTotal > 0) {
        var otherValue = parseFloat(valueOf(row, other)) || 0;
        var otherGroups = groupsFor(row, other);
        for (var o = 0; o < otherGroups.length; o++) {
          otherValue += parseFloat(otherGroups[o].getAttribute("data-value")) || 0;
        }
        otherEl.textContent =
          "also " + otherTotal + " " + other + " · " + formatMoney(otherValue);
      }
    }

    // A manual item's price box appears the moment this condition has a
    // quantity, and each condition keeps its own price.
    var box = row.querySelector('[data-role="price-box"]');
    if (box) {
      // Stays open while a second price is recorded here, even if the first
      // one has been counted back down to zero -- otherwise dropping the main
      // quantity would hide real counted items.
      box.hidden = quantity <= 0 && extraHere === 0;

      var input = row.querySelector('[data-role="price-input"]');
      // Do not fight her fingers: leave the box alone while she is typing in
      // it, or a slow save would overwrite half-typed digits.
      if (input && document.activeElement !== input) {
        input.value = storedPriceOf(row, condition);
      }

      var scope = row.querySelector('[data-role="price-condition"]');
      if (scope) {
        scope.textContent = condition;
      }

      row.classList.toggle(
        "needs-price",
        quantity > 0 && storedPriceOf(row, condition) === ""
      );
    }
  }

  function renderAllRows() {
    var rows = list.querySelectorAll(".item-row");
    for (var i = 0; i < rows.length; i++) {
      renderRow(rows[i]);
    }
  }

  function nameOf(row) {
    var el = row.querySelector(".item-name");
    return el ? el.textContent.replace(/\s+/g, " ").trim() : "";
  }

  function categoryOf(row) {
    return row.closest("details.category");
  }

  // --- Category badges ------------------------------------------------------

  function updateCategoryBadge(category) {
    if (!category) {
      return;
    }
    var counted = 0;
    var rows = category.querySelectorAll(".item-row");
    for (var i = 0; i < rows.length; i++) {
      // Both conditions count towards the badge.
      for (var c = 0; c < CONDITIONS.length; c++) {
        counted += quantityOf(rows[i], CONDITIONS[c]);
      }
      // So does anything recorded at a second price.
      var groups = groupsFor(rows[i]);
      for (var g = 0; g < groups.length; g++) {
        counted += groupQuantity(groups[g]);
      }
    }

    var badge = category.querySelector('[data-role="category-count"]');
    if (badge) {
      badge.textContent = counted;
      badge.hidden = counted === 0;
    }

    // A section holding counted items stays open. Work in progress is never
    // hidden behind a closed accordion.
    if (counted > 0) {
      category.open = true;
    }
  }

  function updateAllBadges() {
    var categories = list.querySelectorAll("details.category");
    for (var i = 0; i < categories.length; i++) {
      updateCategoryBadge(categories[i]);
    }
  }

  // --- Remembering which sections are open ----------------------------------

  function saveOpenCategories() {
    if (searchInput && searchInput.value.trim()) {
      return; // searching temporarily opens things; do not save that
    }
    var open = [];
    var categories = list.querySelectorAll("details.category");
    for (var i = 0; i < categories.length; i++) {
      if (categories[i].open) {
        open.push(categories[i].getAttribute("data-category"));
      }
    }
    try {
      window.localStorage.setItem(OPEN_CATEGORIES_KEY, JSON.stringify(open));
    } catch (error) {
      /* Private browsing, or storage full. Not worth interrupting her for. */
    }
  }

  function restoreOpenCategories() {
    var saved = [];
    try {
      saved = JSON.parse(window.localStorage.getItem(OPEN_CATEGORIES_KEY) || "[]");
    } catch (error) {
      saved = [];
    }

    var categories = list.querySelectorAll("details.category");
    for (var i = 0; i < categories.length; i++) {
      var slug = categories[i].getAttribute("data-category");
      categories[i].open = saved.indexOf(slug) !== -1;
    }
  }

  // --- Search ---------------------------------------------------------------

  function runSearch() {
    var query = searchInput.value.trim().toLowerCase();
    searchClear.hidden = query === "";

    var categories = list.querySelectorAll("details.category");
    var anyVisible = false;

    for (var i = 0; i < categories.length; i++) {
      var category = categories[i];
      var rows = category.querySelectorAll(".item-row");
      var matchesHere = 0;

      for (var j = 0; j < rows.length; j++) {
        var haystack = rows[j].getAttribute("data-search") || "";
        var matches = query === "" || haystack.indexOf(query) !== -1;
        rows[j].hidden = !matches;
        if (matches) {
          matchesHere++;
        }
      }

      category.hidden = query !== "" && matchesHere === 0;
      if (matchesHere > 0) {
        anyVisible = true;
      }

      // Searching opens whatever it finds, so results are never hidden behind
      // a closed section. Clearing the search puts things back as they were.
      if (query !== "") {
        category.open = matchesHere > 0;
      }
    }

    if (query === "") {
      restoreOpenCategories();
      updateAllBadges();
    }

    noResults.hidden = anyVisible || query === "";
  }

  // --- Wiring ---------------------------------------------------------------

  list.addEventListener("click", function (event) {
    var row = event.target.closest(".item-row");
    if (!row) {
      return;
    }

    // A tap inside an extra price group belongs to that group's own line, not
    // to the row's main one.
    var group = event.target.closest('[data-role="price-group"]');

    if (event.target.closest(".step-up")) {
      if (group) {
        sendGroupUpdate(row, group, {
          quantity: groupQuantity(group) + 1,
          unit_price: groupPriceOf(group)
        });
      } else {
        sendUpdate(row, {
          quantity: quantityOf(row) + 1,
          condition: conditionOf(row),
          unit_price: priceOf(row)
        });
      }
      return;
    }

    if (event.target.closest(".step-down")) {
      // Never below zero. The server clamps too, this just avoids a pointless
      // round trip.
      if (group) {
        sendGroupUpdate(row, group, {
          quantity: Math.max(0, groupQuantity(group) - 1),
          unit_price: groupPriceOf(group)
        });
      } else {
        sendUpdate(row, {
          quantity: Math.max(0, quantityOf(row) - 1),
          condition: conditionOf(row),
          unit_price: priceOf(row)
        });
      }
      return;
    }

    var conditionButton = event.target.closest(".condition-toggle button");
    if (conditionButton) {
      // Switching sides only changes what the row is showing. Nothing is sent:
      // the new ones already counted stay exactly as they are, and the used
      // ones are their own line with their own quantity and price.
      row.setAttribute(
        "data-condition",
        conditionButton.getAttribute("data-condition")
      );
      renderRow(row);
      return;
    }

    // Tapping "also 2 used" flips to that side.
    if (event.target.closest('[data-role="other-condition"]')) {
      row.setAttribute("data-condition", otherConditionOf(row));
      renderRow(row);
      return;
    }

    if (event.target.closest('[data-role="quantity"]')) {
      if (group) {
        window.Keypad.open({
          title: nameOf(row) + " · at this price",
          value: groupQuantity(group),
          onOk: function (value) {
            sendGroupUpdate(row, group, {
              quantity: value,
              unit_price: groupPriceOf(group)
            });
          }
        });
        return;
      }

      window.Keypad.open({
        title: nameOf(row) + " · " + conditionOf(row),
        value: quantityOf(row),
        onOk: function (value) {
          sendUpdate(row, {
            quantity: value,
            condition: conditionOf(row),
            unit_price: priceOf(row)
          });
        }
      });
    }
  });

  /* Typed prices. Waiting a moment after the last keystroke means we save one
     price instead of one per digit. */
  var priceTimers = new window.WeakMap();

  list.addEventListener("input", function (event) {
    var input = event.target.closest('[data-role="price-input"]');
    if (!input) {
      return;
    }
    var row = input.closest(".item-row");
    var group = input.closest('[data-role="price-group"]');

    window.clearTimeout(priceTimers.get(input));
    priceTimers.set(
      input,
      window.setTimeout(function () {
        if (group) {
          sendGroupUpdate(row, group, {
            quantity: groupQuantity(group),
            unit_price: input.value
          });
        } else {
          sendUpdate(row, {
            quantity: quantityOf(row),
            condition: conditionOf(row),
            unit_price: input.value
          });
        }
      }, 400)
    );
  });

  list.addEventListener("toggle", function (event) {
    if (event.target.matches("details.category")) {
      saveOpenCategories();
    }
  }, true);

  if (searchInput) {
    searchInput.addEventListener("input", runSearch);
  }
  if (searchClear) {
    searchClear.addEventListener("click", function () {
      searchInput.value = "";
      runSearch();
      searchInput.focus();
    });
  }

  // --- The custom item form -------------------------------------------------

  var customModal = document.getElementById("custom-modal");
  var openCustom = document.getElementById("open-custom");
  var cancelCustom = document.getElementById("custom-cancel");

  if (openCustom && customModal) {
    openCustom.addEventListener("click", function () {
      customModal.hidden = false;
      document.body.classList.add("modal-open");
      var first = customModal.querySelector('input[name="custom_name"]');
      if (first) {
        first.focus();
      }
    });

    cancelCustom.addEventListener("click", function () {
      customModal.hidden = true;
      document.body.classList.remove("modal-open");
    });

    customModal.addEventListener("click", function (event) {
      if (event.target === customModal) {
        customModal.hidden = true;
        document.body.classList.remove("modal-open");
      }
    });
  }

  // --- Start ----------------------------------------------------------------

  restoreOpenCategories();
  renderAllRows();
  updateAllBadges();
})(window, document);
