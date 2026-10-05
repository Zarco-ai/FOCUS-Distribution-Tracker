"""The screens themselves: every page loads, and every form validates its
input.

These are deliberately shallow. They prove the pages render and that bad input
gets a readable message instead of a stack trace -- the two things most likely
to embarrass Christopher during the demo.
"""

import datetime
from decimal import Decimal

from app.extensions import db
from app.models import Batch, ServiceType, set_commit_mode
from app.services import batches, catalog


def start_batch(client):
    response = client.post("/batch/resume")
    return int(response.headers["Location"].rstrip("/").split("/")[-1])


def item_id(name, category):
    return catalog.find_item(name, category).id


# --- Every page loads -------------------------------------------------------


def test_every_page_loads(client, seeded_app):
    batch_id = start_batch(client)
    coat = item_id("Coat", "clothing_adult")

    for url in [
        "/",
        f"/batch/{batch_id}",
        f"/batch/{batch_id}/review",
        "/batches",
        "/totals",
        "/totals/export.csv",
        "/review-queue",
        "/admin/items",
        "/admin/items/new",
        f"/admin/items/{coat}",
        "/admin/needs-price",
        "/admin/settings",
        "/admin/audit",
    ]:
        assert client.get(url).status_code == 200, url


def test_the_entry_screen_shows_every_active_item(client, seeded_app):
    batch_id = start_batch(client)
    page = client.get(f"/batch/{batch_id}").get_data(as_text=True)

    assert "Individual Pack of Wipes" in page
    assert "Blood Pressure Monitor" in page
    assert page.count('class="item-row') == len(catalog.active_items())


def test_repeated_names_are_shown_with_their_category(client, seeded_app):
    """The Center Director must be able to tell a $60 adult coat from a $15 infant one."""
    batch_id = start_batch(client)
    page = client.get(f"/batch/{batch_id}").get_data(as_text=True)

    assert "· Adult" in page
    assert "· Children" in page
    assert "· Infant" in page


def test_manual_items_show_their_note_as_help_text(client, seeded_app):
    batch_id = start_batch(client)
    page = client.get(f"/batch/{batch_id}").get_data(as_text=True)

    assert "price required" in page
    assert "confirm price" in page
    assert "too many stroller types" in page  # the Stroller note


# --- The counting API -------------------------------------------------------


def test_the_plus_button_saves_and_returns_the_new_value(client, seeded_app):
    batch_id = start_batch(client)

    response = client.post(
        f"/api/batch/{batch_id}/line",
        json={"item_id": item_id("Coat", "clothing_adult"), "quantity": 1,
              "condition": "used"},
    )
    body = response.get_json()

    assert body["ok"] is True
    assert body["line"]["value"] == "45.00"
    assert body["batch"]["total_value"] == "45.00"
    assert body["batch"]["item_count"] == 1


def test_the_api_refuses_an_unknown_item(client, seeded_app):
    batch_id = start_batch(client)
    response = client.post(
        f"/api/batch/{batch_id}/line", json={"item_id": 99999, "quantity": 1}
    )
    assert response.status_code == 404
    assert response.get_json()["ok"] is False


def test_the_api_refuses_an_unknown_condition(client, seeded_app):
    batch_id = start_batch(client)
    response = client.post(
        f"/api/batch/{batch_id}/line",
        json={"item_id": item_id("Coat", "clothing_adult"), "condition": "broken"},
    )
    assert response.status_code == 400


def test_the_api_clamps_a_negative_quantity(client, seeded_app):
    batch_id = start_batch(client)
    response = client.post(
        f"/api/batch/{batch_id}/line",
        json={"item_id": item_id("Coat", "clothing_adult"), "quantity": -5},
    )
    assert response.get_json()["line"]["quantity"] == 0


def test_the_api_survives_a_junk_quantity(client, seeded_app):
    batch_id = start_batch(client)
    response = client.post(
        f"/api/batch/{batch_id}/line",
        json={"item_id": item_id("Coat", "clothing_adult"), "quantity": "banana"},
    )
    assert response.status_code == 200
    assert response.get_json()["line"]["quantity"] == 0


def test_counting_the_same_item_new_then_used_keeps_both(client, seeded_app):
    """Christopher's bug: clicking + on a new Bottles, then adding a used one,
    used to overwrite the first."""
    batch_id = start_batch(client)
    bottles = item_id("Bottles", "baby_essentials")

    client.post(
        f"/api/batch/{batch_id}/line",
        json={"item_id": bottles, "quantity": 1, "condition": "new"},
    )
    response = client.post(
        f"/api/batch/{batch_id}/line",
        json={"item_id": bottles, "quantity": 1, "condition": "used"},
    )
    body = response.get_json()

    assert body["line"]["condition"] == "used"
    assert body["line"]["value"] == "3.50"  # $7.00 x 0.50
    assert body["batch"]["item_count"] == 2
    assert body["batch"]["total_value"] == "10.50"  # 7.00 + 3.50

    batch = db.session.get(Batch, batch_id)
    assert len(batch.active_lines) == 2


def test_the_entry_screen_remembers_both_conditions(client, seeded_app):
    batch_id = start_batch(client)
    bottles = item_id("Bottles", "baby_essentials")

    for condition, quantity in [("new", 3), ("used", 2)]:
        client.post(
            f"/api/batch/{batch_id}/line",
            json={"item_id": bottles, "quantity": quantity, "condition": condition},
        )

    page = client.get(f"/batch/{batch_id}").get_data(as_text=True)

    assert 'data-quantity-new="3"' in page
    assert 'data-quantity-used="2"' in page


def test_a_manual_item_keeps_a_separate_price_per_condition(client, seeded_app):
    batch_id = start_batch(client)
    stroller = item_id("Stroller", "baby_mom_items")

    client.post(
        f"/api/batch/{batch_id}/line",
        json={"item_id": stroller, "quantity": 1, "condition": "new",
              "unit_price": "300"},
    )
    response = client.post(
        f"/api/batch/{batch_id}/line",
        json={"item_id": stroller, "quantity": 1, "condition": "used",
              "unit_price": "40"},
    )

    assert response.get_json()["line"]["value"] == "20.00"  # 40 x 0.50
    assert response.get_json()["batch"]["total_value"] == "320.00"


def test_two_of_the_same_item_at_two_prices_through_the_screen(client, seeded_app):
    """Christopher's second bug: a $40 stroller and a $300 stroller in one
    batch."""
    batch_id = start_batch(client)
    stroller = item_id("Stroller", "baby_mom_items")

    client.post(
        f"/api/batch/{batch_id}/line",
        json={"item_id": stroller, "quantity": 1, "unit_price": "300"},
    )
    client.post(
        f"/batch/{batch_id}/price-group",
        data={"item_id": stroller, "condition": "new"},
    )

    batch = db.session.get(Batch, batch_id)
    extra = [line for line in batch.lines if line.unit_price_at_time is None][0]

    response = client.post(
        f"/api/batch/{batch_id}/line/{extra.id}",
        json={"quantity": 1, "unit_price": "40"},
    )
    body = response.get_json()

    assert body["line"]["value"] == "40.00"
    assert body["batch"]["item_count"] == 2
    assert body["batch"]["total_value"] == "340.00"


def test_the_add_another_price_button_only_shows_on_manual_items(
    client, seeded_app
):
    batch_id = start_batch(client)
    page = client.get(f"/batch/{batch_id}").get_data(as_text=True)

    # One button per manual-price item, and none for the fixed-price ones.
    manual_count = len(catalog.items_needing_a_price())
    assert page.count("Add another at a different price") == manual_count


def test_removing_an_extra_price_leaves_the_first_alone(client, seeded_app):
    batch_id = start_batch(client)
    stroller = item_id("Stroller", "baby_mom_items")

    client.post(
        f"/api/batch/{batch_id}/line",
        json={"item_id": stroller, "quantity": 1, "unit_price": "300"},
    )
    client.post(
        f"/batch/{batch_id}/price-group",
        data={"item_id": stroller, "condition": "new"},
    )

    batch = db.session.get(Batch, batch_id)
    extra = [line for line in batch.lines if line.unit_price_at_time is None][0]

    client.post(f"/batch/{batch_id}/price-group/{extra.id}/remove")

    batch = db.session.get(Batch, batch_id)
    assert len(batch.active_lines) == 1
    assert batch.active_lines[0].unit_price_at_time == Decimal("300.00")


def test_an_unpriced_extra_is_reported_as_a_warning(client, seeded_app):
    batch_id = start_batch(client)
    stroller = item_id("Stroller", "baby_mom_items")

    client.post(
        f"/api/batch/{batch_id}/line",
        json={"item_id": stroller, "quantity": 1, "unit_price": "300"},
    )
    response = client.post(
        f"/batch/{batch_id}/price-group",
        data={"item_id": stroller, "condition": "new"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    batch = db.session.get(Batch, batch_id)
    assert batches.approval_warnings(batch)
    assert not any("price" in reason for reason in batches.blocking_reasons(batch))


def test_a_custom_item_added_with_no_price_can_still_be_approved(client, seeded_app):
    batch_id = start_batch(client)

    client.post(
        f"/batch/{batch_id}/custom-item",
        data={"custom_name": "Mystery box", "quantity": "2", "unit_price": "0.00"},
        follow_redirects=True,
    )
    client.post(
        f"/batch/{batch_id}/service-type",
        data={"service_type_id": ServiceType.query.first().id},
    )
    client.post(f"/batch/{batch_id}/approve", follow_redirects=True)

    batch = db.session.get(Batch, batch_id)
    assert batch.is_committed
    assert batch.total_value == Decimal("0.00")
    assert batch.flagged_lines


def test_the_custom_item_form_defaults_the_price_to_zero(client, seeded_app):
    batch_id = start_batch(client)
    page = client.get(f"/batch/{batch_id}").get_data(as_text=True)

    assert 'name="unit_price" inputmode="decimal" value="0.00"' in page
    assert "Price each (optional)" not in page


def test_a_manual_item_reports_that_it_needs_a_price(client, seeded_app):
    """The row says so, and the batch says so -- as a warning, not a blocker."""
    batch_id = start_batch(client)
    response = client.post(
        f"/api/batch/{batch_id}/line",
        json={"item_id": item_id("Stroller", "baby_mom_items"), "quantity": 1},
    )
    body = response.get_json()

    assert body["line"]["needs_price"] is True
    assert any("Stroller" in warning for warning in body["batch"]["warnings"])
    assert not any("price" in reason for reason in body["batch"]["reasons"])


def test_a_junk_price_is_ignored_rather_than_crashing(client, seeded_app):
    batch_id = start_batch(client)
    response = client.post(
        f"/api/batch/{batch_id}/line",
        json={"item_id": item_id("Stroller", "baby_mom_items"), "quantity": 1,
              "unit_price": "twenty dollars"},
    )
    assert response.status_code == 200
    assert response.get_json()["line"]["needs_price"] is True


# --- Approving through the web --------------------------------------------


def test_approving_without_a_service_type_is_refused_with_a_message(
    client, seeded_app
):
    batch_id = start_batch(client)
    client.post(
        f"/api/batch/{batch_id}/line",
        json={"item_id": item_id("Coat", "clothing_adult"), "quantity": 1},
    )

    page = client.post(f"/batch/{batch_id}/approve", follow_redirects=True)

    assert b"Pick a service type" in page.data
    assert db.session.get(Batch, batch_id).is_draft


def test_the_full_happy_path(client, seeded_app):
    batch_id = start_batch(client)

    client.post(
        f"/api/batch/{batch_id}/line",
        json={"item_id": item_id("Coat", "clothing_adult"), "quantity": 1,
              "condition": "used"},
    )
    client.post(
        f"/batch/{batch_id}/service-type",
        data={"service_type_id": ServiceType.query.first().id},
    )
    client.post(
        f"/batch/{batch_id}/attendance",
        data={"individuals_served": "3", "children_served": "4",
              "education_participants": "0"},
    )
    client.post(f"/batch/{batch_id}/approve", follow_redirects=True)

    batch = db.session.get(Batch, batch_id)
    assert batch.is_committed
    assert batch.attendance.individuals_served == 3

    totals_page = client.get("/totals").get_data(as_text=True)
    assert "$45.00" in totals_page


def test_a_batch_holding_an_unpriced_item_can_be_approved_and_priced_later(
    client, seeded_app
):
    """The whole reported flow, end to end: count something whose price is
    unknown, approve anyway, start the next batch, and put the value on the
    first one afterwards."""
    batch_id = start_batch(client)

    client.post(
        f"/api/batch/{batch_id}/line",
        json={"item_id": item_id("Stroller", "baby_mom_items"), "quantity": 1},
    )
    client.post(
        f"/batch/{batch_id}/service-type",
        data={"service_type_id": ServiceType.query.first().id},
    )

    # The review screen offers Approve rather than disabling it.
    review_page = client.get(f"/batch/{batch_id}/review").get_data(as_text=True)
    assert "You can approve this now" in review_page
    assert "btn-big\" disabled" not in review_page

    client.post(f"/batch/{batch_id}/approve", follow_redirects=True)

    batch = db.session.get(Batch, batch_id)
    assert batch.is_committed
    assert batch.item_count == 1
    assert batch.total_value == Decimal("0.00")
    flagged = batch.flagged_lines
    assert len(flagged) == 1

    # Counting again starts a fresh batch, not the one with the flagged line.
    next_id = start_batch(client)
    assert next_id != batch_id

    # And the price typed in the queue lands on the batch it was counted in.
    client.post(
        f"/review-queue/{flagged[0].id}/resolve",
        data={"unit_price": "450"},
        follow_redirects=True,
    )

    batch = db.session.get(Batch, batch_id)
    assert batch.total_value == Decimal("450.00")
    assert batch.flagged_lines == []
    assert "$450.00" in client.get("/totals").get_data(as_text=True)


def test_the_review_queue_asks_for_a_price_not_a_catalog_match(client, seeded_app):
    batch_id = start_batch(client)
    client.post(
        f"/api/batch/{batch_id}/line",
        json={"item_id": item_id("Stroller", "baby_mom_items"), "quantity": 1},
    )
    client.post(
        f"/batch/{batch_id}/service-type",
        data={"service_type_id": ServiceType.query.first().id},
    )
    client.post(f"/batch/{batch_id}/approve", follow_redirects=True)

    page = client.get("/review-queue").get_data(as_text=True)

    assert "Waiting for a price" in page
    # Its category is shown, because Stroller is not the only thing it could be.
    assert "Stroller" in page and "Baby &amp; Mom" in page
    # And the note explaining why it has no price on file.
    assert "too many stroller types" in page


def test_a_new_batch_can_be_started_while_another_is_unfinished(client, seeded_app):
    """An open batch -- including one holding an item that needs a price --
    must never capture the next session's counting."""
    open_id = start_batch(client)
    client.post(
        f"/api/batch/{open_id}/line",
        json={"item_id": item_id("Stroller", "baby_mom_items"), "quantity": 1},
    )

    # Resuming still picks the unfinished batch up, and the home screen says so.
    assert start_batch(client) == open_id
    home = client.get("/").get_data(as_text=True)
    assert "Keep counting" in home
    assert "Start a new batch instead" in home

    response = client.post("/batch/new")
    new_id = int(response.headers["Location"].rstrip("/").split("/")[-1])

    assert new_id != open_id
    assert db.session.get(Batch, open_id).is_draft
    assert db.session.get(Batch, new_id).item_count == 0


def test_per_mother_mode_opens_a_new_batch_after_approving(client, seeded_app):
    set_commit_mode("per_mother")
    db.session.commit()

    batch_id = start_batch(client)
    client.post(
        f"/api/batch/{batch_id}/line",
        json={"item_id": item_id("Coat", "clothing_adult"), "quantity": 1},
    )
    client.post(
        f"/batch/{batch_id}/service-type",
        data={"service_type_id": ServiceType.query.first().id},
    )

    response = client.post(f"/batch/{batch_id}/approve")
    next_url = response.headers["Location"]

    assert f"/batch/{batch_id}" != next_url
    assert "/batch/" in next_url
    assert client.get(next_url).status_code == 200


# --- Forms validate ---------------------------------------------------------


def test_a_custom_item_without_a_name_gets_a_message(client, seeded_app):
    batch_id = start_batch(client)
    page = client.post(
        f"/batch/{batch_id}/custom-item",
        data={"custom_name": "  ", "quantity": "1"},
        follow_redirects=True,
    )
    assert b"needs a name" in page.data


def test_a_new_item_with_a_bad_used_rate_gets_a_message(client, seeded_app):
    page = client.post(
        "/admin/items/new",
        data={
            "name": "Thing",
            "category": "home_goods",
            "report_bucket": "household",
            "used_multiplier": "banana",
            "price_entry": "fixed",
        },
    )
    assert b"used rate must be a number" in page.data


def test_a_duplicate_item_gets_a_message(client, seeded_app):
    page = client.post(
        "/admin/items/new",
        data={
            "name": "Coat",
            "category": "clothing_adult",
            "report_bucket": "clothing",
            "used_multiplier": "0.75",
            "price_entry": "fixed",
        },
    )
    assert b"already exists" in page.data


def test_the_center_director_can_add_a_diaper_through_the_ui(client, seeded_app):
    """If she has to call Christopher to add a diaper, the system has failed."""
    client.post(
        "/admin/items/new",
        data={
            "name": "Diapers Size 3",
            "category": "diapers",
            "report_bucket": "diapers",
            "used_multiplier": "0.5",
            "price_entry": "fixed",
            "unit_price_new": "0.25",
        },
        follow_redirects=True,
    )

    diaper = catalog.find_item("Diapers Size 3", "diapers")
    assert diaper is not None
    assert diaper.report_bucket == "diapers"

    batch_id = start_batch(client)
    page = client.get(f"/batch/{batch_id}").get_data(as_text=True)
    assert "Diapers Size 3" in page


def test_settings_reject_an_unknown_commit_mode(client, seeded_app):
    page = client.post(
        "/admin/settings", data={"commit_mode": "whenever"}, follow_redirects=True
    )
    assert b"Unknown mode" in page.data


def test_a_bad_date_range_falls_back_instead_of_crashing(client, seeded_app):
    assert client.get("/totals?start=not-a-date&end=also-not").status_code == 200


def test_a_missing_batch_gives_a_404_not_a_crash(client, seeded_app):
    assert client.get("/batch/99999").status_code == 404
    assert client.get("/batches/99999").status_code == 404


# --- The service type dropdown ----------------------------------------------
#
# The same endpoint serves the dropdown on the counting screen and the one on the
# review screen, and every option on both of them has to land her back on the
# page she was already looking at.


def service_type_id():
    return ServiceType.query.first().id


def test_setting_the_service_type_while_counting_stays_on_the_counting_page(
    client, seeded_app
):
    batch_id = start_batch(client)

    response = client.post(
        f"/batch/{batch_id}/service-type",
        data={"service_type_id": service_type_id(), "return_to": "entry"},
    )

    assert response.status_code == 302
    assert response.headers["Location"] == f"/batch/{batch_id}"


def test_setting_the_service_type_while_reviewing_stays_on_the_review_page(
    client, seeded_app
):
    """She got to the review screen, saw 'Pick a service type', and picked one.
    Throwing her back to the counting screen to start again is not the answer."""
    batch_id = start_batch(client)

    response = client.post(
        f"/batch/{batch_id}/service-type",
        data={"service_type_id": service_type_id(), "return_to": "review"},
    )

    assert response.status_code == 302
    assert response.headers["Location"] == f"/batch/{batch_id}/review"
    assert db.session.get(Batch, batch_id).service_type_id == service_type_id()


def test_the_review_page_dropdown_asks_to_come_back_to_the_review_page(
    client, seeded_app
):
    """The redirect above only happens because the form says so. If this input
    goes missing the dropdown silently starts navigating away again."""
    batch_id = start_batch(client)
    page = client.get(f"/batch/{batch_id}/review").get_data(as_text=True)

    assert 'name="return_to" value="review"' in page


def test_the_blank_service_type_option_on_the_counting_page_is_a_page(
    client, seeded_app
):
    """Picking 'Service type…' used to answer 415 Unsupported Media Type,
    because an empty form value sent the view looking for JSON that was never
    there."""
    batch_id = start_batch(client)
    client.post(
        f"/batch/{batch_id}/service-type",
        data={"service_type_id": service_type_id(), "return_to": "entry"},
    )

    response = client.post(
        f"/batch/{batch_id}/service-type",
        data={"service_type_id": "", "return_to": "entry"},
    )

    assert response.status_code == 302
    assert response.headers["Location"] == f"/batch/{batch_id}"
    assert db.session.get(Batch, batch_id).service_type_id is None
    assert client.get(f"/batch/{batch_id}").status_code == 200


def test_the_not_set_option_on_the_review_page_is_a_page(client, seeded_app):
    """Same bug, same endpoint, other screen: 'Not set' has to come back as the
    review page."""
    batch_id = start_batch(client)
    client.post(
        f"/batch/{batch_id}/service-type",
        data={"service_type_id": service_type_id(), "return_to": "review"},
    )

    response = client.post(
        f"/batch/{batch_id}/service-type",
        data={"service_type_id": "", "return_to": "review"},
    )

    assert response.status_code == 302
    assert response.headers["Location"] == f"/batch/{batch_id}/review"
    assert db.session.get(Batch, batch_id).service_type_id is None


def test_a_service_type_that_is_not_a_number_is_refused_with_a_message(
    client, seeded_app
):
    batch_id = start_batch(client)

    page = client.post(
        f"/batch/{batch_id}/service-type",
        data={"service_type_id": "diapers please"},
        follow_redirects=True,
    )

    assert page.status_code == 200
    assert b"not a service type" in page.data
    assert db.session.get(Batch, batch_id).service_type_id is None


def test_a_service_type_that_does_not_exist_is_refused_with_a_message(
    client, seeded_app
):
    batch_id = start_batch(client)

    page = client.post(
        f"/batch/{batch_id}/service-type",
        data={"service_type_id": "99999"},
        follow_redirects=True,
    )

    assert b"no longer exists" in page.data
    assert db.session.get(Batch, batch_id).service_type_id is None


def test_an_approved_batch_cannot_have_its_service_type_cleared(client, seeded_app):
    """A batch could never have been approved without one, and the monthly report
    reads this field, so 'Not set' is not an option once it is approved."""
    batch_id = start_batch(client)
    client.post(
        f"/api/batch/{batch_id}/line",
        json={"item_id": item_id("Coat", "clothing_adult"), "quantity": 1},
    )
    client.post(
        f"/batch/{batch_id}/service-type",
        data={"service_type_id": service_type_id()},
    )
    client.post(f"/batch/{batch_id}/approve", follow_redirects=True)

    page = client.post(
        f"/batch/{batch_id}/service-type",
        data={"service_type_id": "", "return_to": "review"},
        follow_redirects=True,
    )

    assert b"has to keep a service type" in page.data
    assert db.session.get(Batch, batch_id).service_type_id == service_type_id()

    # And the dropdown does not offer an option that is only going to be
    # refused.
    review_page = client.get(f"/batch/{batch_id}/review").get_data(as_text=True)
    assert ">Not set<" not in review_page


def test_changing_the_service_type_on_an_approved_batch_is_audited(client, seeded_app):
    from app.services import audit

    batch_id = start_batch(client)
    first, second = ServiceType.query.order_by(ServiceType.id).limit(2).all()
    client.post(
        f"/api/batch/{batch_id}/line",
        json={"item_id": item_id("Coat", "clothing_adult"), "quantity": 1},
    )
    client.post(
        f"/batch/{batch_id}/service-type", data={"service_type_id": first.id}
    )
    client.post(f"/batch/{batch_id}/approve", follow_redirects=True)

    client.post(
        f"/batch/{batch_id}/service-type",
        data={"service_type_id": second.id, "return_to": "review"},
    )

    history = audit.history_for("batch", batch_id)
    assert [entry.field for entry in history] == ["service_type_id"]
    # Names, not row ids -- nobody reading the log knows what a 3 is.
    assert history[0].old_value == first.name
    assert history[0].new_value == second.name


# --- A $0 line always ends up in the review queue ----------------------------


def approved_batch_with_an_unpriced_stroller(client):
    batch_id = start_batch(client)
    client.post(
        f"/api/batch/{batch_id}/line",
        json={"item_id": item_id("Stroller", "baby_mom_items"), "quantity": 1},
    )
    client.post(
        f"/batch/{batch_id}/service-type",
        data={"service_type_id": service_type_id()},
    )
    client.post(f"/batch/{batch_id}/approve", follow_redirects=True)
    return batch_id


def test_a_price_taken_back_to_zero_on_the_review_page_returns_to_the_queue(
    client, seeded_app
):
    """The reported bug, through the screens: price it in the queue, take it back
    to $0 on the review screen, and it has to be waiting in the queue again."""
    batch_id = approved_batch_with_an_unpriced_stroller(client)
    line_id = db.session.get(Batch, batch_id).flagged_lines[0].id

    client.post(
        f"/review-queue/{line_id}/resolve", data={"unit_price": "5"},
        follow_redirects=True,
    )
    assert "Waiting for a price" not in client.get("/review-queue").get_data(
        as_text=True
    )

    page = client.post(
        f"/batch/{batch_id}/review/lines",
        data={f"quantity-{line_id}": "1", f"condition-{line_id}": "new",
              f"unit_price-{line_id}": "0"},
        follow_redirects=True,
    )

    assert b"waiting in the review queue" in page.data
    assert db.session.get(Batch, batch_id).flagged_lines
    queue = client.get("/review-queue").get_data(as_text=True)
    assert "Waiting for a price" in queue
    assert "Stroller" in queue


def test_a_price_set_to_zero_in_the_queue_says_it_is_staying_there(
    client, seeded_app
):
    batch_id = approved_batch_with_an_unpriced_stroller(client)
    line_id = db.session.get(Batch, batch_id).flagged_lines[0].id

    page = client.post(
        f"/review-queue/{line_id}/resolve", data={"unit_price": "0"},
        follow_redirects=True,
    )

    assert b"stays in the review queue" in page.data
    assert "Stroller" in client.get("/review-queue").get_data(as_text=True)


def test_an_approved_batch_with_a_zero_value_item_is_flagged_on_the_home_screen(
    client, seeded_app
):
    approved_batch_with_an_unpriced_stroller(client)

    page = client.get("/").get_data(as_text=True)

    assert "Recently approved" in page
    assert "Needs Review" in page


def test_an_approved_batch_worth_what_it_says_is_not_flagged(client, seeded_app):
    """The flag is about a $0 value and nothing else. A batch where everything
    has a price does not get one."""
    batch_id = start_batch(client)
    client.post(
        f"/api/batch/{batch_id}/line",
        json={"item_id": item_id("Coat", "clothing_adult"), "quantity": 1},
    )
    client.post(
        f"/batch/{batch_id}/service-type",
        data={"service_type_id": service_type_id()},
    )
    client.post(f"/batch/{batch_id}/approve", follow_redirects=True)

    page = client.get("/").get_data(as_text=True)

    assert "Recently approved" in page
    assert "Needs Review" not in page


def test_the_home_flag_clears_once_the_value_is_typed(client, seeded_app):
    batch_id = approved_batch_with_an_unpriced_stroller(client)
    line_id = db.session.get(Batch, batch_id).flagged_lines[0].id

    client.post(
        f"/review-queue/{line_id}/resolve", data={"unit_price": "300"},
        follow_redirects=True,
    )

    assert "Needs Review" not in client.get("/").get_data(as_text=True)


def test_a_custom_line_with_a_real_price_does_not_flag_the_home_screen(
    client, seeded_app
):
    """It is in the review queue -- it needs a category -- but it is not worth
    $0, and the home screen flag is only ever about the money."""
    batch_id = start_batch(client)
    client.post(
        f"/batch/{batch_id}/custom-item",
        data={"custom_name": "Bike helmet", "quantity": "1", "unit_price": "25",
              "condition": "new"},
    )
    client.post(
        f"/batch/{batch_id}/service-type",
        data={"service_type_id": service_type_id()},
    )
    client.post(f"/batch/{batch_id}/approve", follow_redirects=True)

    page = client.get("/").get_data(as_text=True)

    assert db.session.get(Batch, batch_id).flagged_lines
    assert "Needs Review" not in page


# --- The privacy boundary ---------------------------------------------------


def test_no_screen_asks_for_a_name_of_a_person(client, seeded_app):
    """Attendance is counts only. This checks the forms do not drift."""
    batch_id = start_batch(client)

    review_page = client.get(f"/batch/{batch_id}/review").get_data(as_text=True)

    assert 'name="individuals_served"' in review_page
    assert 'name="children_served"' in review_page
    # No field that invites a person's name.
    for forbidden in ["client_name", "mother_name", "recipient", "patient"]:
        assert forbidden not in review_page


def test_the_attendance_table_has_no_name_column(seeded_app):
    from app.models import Attendance

    columns = {column.name for column in Attendance.__table__.columns}
    assert columns == {
        "id",
        "batch_id",
        "individuals_served",
        "children_served",
        "education_participants",
    }


def test_stale_drafts_are_flagged_on_the_home_screen(client, seeded_app):
    old = batches.open_batch(date=datetime.date.today() - datetime.timedelta(days=2))
    batches.set_line(old, catalog.find_item("Coat", "clothing_adult"), quantity=1)
    db.session.commit()

    page = client.get("/").get_data(as_text=True)
    assert "Unfinished" in page


def test_discarding_a_draft_requires_confirmation(client, seeded_app):
    old = batches.open_batch(date=datetime.date.today() - datetime.timedelta(days=2))
    db.session.commit()
    batch_id = old.id

    client.post(f"/batch/{batch_id}/discard", data={})
    assert db.session.get(Batch, batch_id) is not None

    client.post(f"/batch/{batch_id}/discard", data={"confirm": "yes"})
    assert db.session.get(Batch, batch_id) is None
