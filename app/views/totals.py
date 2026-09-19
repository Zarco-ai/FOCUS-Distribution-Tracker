"""Totals for a date range, and the CSV export.

This is the simple version. The real monthly report has to reproduce
The Center Director's exact table, and we do not have all her columns yet -- so this page
shows the report buckets and the combined goods column, and stays easy to
extend.
"""

import datetime

from flask import Blueprint, Response, render_template, request

from app.services import totals as totals_service

totals_bp = Blueprint("totals", __name__)


@totals_bp.route("/totals")
def index():
    start_date, end_date = _range_from_request()
    return render_template(
        "totals/totals.html",
        summary=totals_service.summary(start_date, end_date),
        start_date=start_date,
        end_date=end_date,
    )


@totals_bp.route("/totals/export.csv")
def export():
    start_date, end_date = _range_from_request()
    csv_text = totals_service.export_csv(start_date, end_date)

    filename = f"focus-gik-{start_date.isoformat()}-to-{end_date.isoformat()}.csv"
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _range_from_request():
    """Dates from the query string, defaulting to the current month."""
    today = datetime.date.today()
    default_start, default_end = totals_service.month_range(today.year, today.month)

    return (
        _parse_date(request.args.get("start"), default_start),
        _parse_date(request.args.get("end"), default_end),
    )


def _parse_date(raw, fallback):
    if not raw:
        return fallback
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError:
        return fallback
