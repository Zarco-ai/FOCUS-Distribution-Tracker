"""A record of every change made after the fact.

A committed batch can still be corrected -- The Center Director will miscount, and
pretending otherwise just means she edits the spreadsheet instead. But every
correction to committed data, and every change to the catalog, writes a row
here: what table, what record, what field, from what, to what, when.
"""

import datetime

from app.extensions import db


class AuditLog(db.Model):
    __tablename__ = "audit_log"

    id = db.Column(db.Integer, primary_key=True)
    table_name = db.Column(db.String(50), nullable=False, index=True)
    record_id = db.Column(db.Integer, nullable=False, index=True)
    field = db.Column(db.String(50), nullable=False)
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    changed_at = db.Column(
        db.DateTime, nullable=False, default=datetime.datetime.now, index=True
    )

    # Plain English description of what was being changed, so the log is
    # readable without cross-referencing ids by hand.
    description = db.Column(db.String(300), nullable=True)

    def __repr__(self):
        return (
            f"<AuditLog {self.table_name}#{self.record_id} {self.field}: "
            f"{self.old_value} -> {self.new_value}>"
        )
