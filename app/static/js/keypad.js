/* The numeric keypad.
 *
 * A mother might receive 120 diapers. Tapping + 120 times is not acceptable,
 * so tapping the quantity itself opens this instead.
 *
 * It is built by hand rather than using the device keyboard so that it looks
 * and behaves exactly the same on The Center Director's phone and on a laptop.
 *
 * Usage:
 *   Keypad.open({ title: "Coat . Adult", value: 12, onOk: function (n) { ... } });
 */
(function (window, document) {
  "use strict";

  var modal = document.getElementById("keypad-modal");
  if (!modal) {
    return; // not on the entry screen
  }

  var titleEl = document.getElementById("keypad-item");
  var displayEl = document.getElementById("keypad-display");
  var okButton = document.getElementById("keypad-ok");
  var cancelButton = document.getElementById("keypad-cancel");

  var typed = "";
  var startingValue = 0;
  var onOk = null;

  function render() {
    displayEl.textContent = typed === "" ? String(startingValue) : typed;
  }

  function open(options) {
    titleEl.textContent = options.title || "";
    startingValue = options.value || 0;
    onOk = options.onOk || null;
    // Start empty: the first key she presses replaces the number rather than
    // appending to it, which is what you want when correcting a mistake.
    typed = "";
    render();

    modal.hidden = false;
    document.body.classList.add("modal-open");
  }

  function close() {
    modal.hidden = true;
    document.body.classList.remove("modal-open");
    onOk = null;
  }

  function press(key) {
    if (key === "clear") {
      typed = "0";
    } else if (key === "back") {
      typed = (typed === "" ? String(startingValue) : typed).slice(0, -1);
    } else {
      // Six digits is far more than any real quantity and stops the display
      // from overflowing.
      if (typed.length < 6) {
        typed = (typed === "0" ? "" : typed) + key;
      }
    }
    render();
  }

  function confirm() {
    var value = typed === "" ? startingValue : parseInt(typed, 10);
    if (isNaN(value) || value < 0) {
      value = 0;
    }
    var callback = onOk;
    close();
    if (callback) {
      callback(value);
    }
  }

  modal.addEventListener("click", function (event) {
    var key = event.target.closest("[data-key]");
    if (key) {
      press(key.getAttribute("data-key"));
      return;
    }
    // Tapping the dark area outside the card cancels, same as Cancel.
    if (event.target === modal) {
      close();
    }
  });

  okButton.addEventListener("click", confirm);
  cancelButton.addEventListener("click", close);

  // On a laptop the physical number keys should work too.
  document.addEventListener("keydown", function (event) {
    if (modal.hidden) {
      return;
    }
    if (event.key >= "0" && event.key <= "9") {
      press(event.key);
    } else if (event.key === "Backspace") {
      press("back");
      event.preventDefault();
    } else if (event.key === "Enter") {
      confirm();
    } else if (event.key === "Escape") {
      close();
    }
  });

  window.Keypad = { open: open, close: close };
})(window, document);
