"""Writing to the audit log.

Call record_change() whenever something that has already been committed gets
edited, and whenever the catalog changes. Draft batches are not audited --
they are still being written, and logging every tap of the + button would bury
the changes that matter.
"""

from app.extensions import db
from app.models import AuditLog


def _as_text(value):
    """Everything in the log is stored as readable text."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def record_change(table_name, record_id, field, old_value, new_value,
                  description=None):
    """Log one field changing on one record. Returns None if nothing moved."""
    old_text = _as_text(old_value)
    new_text = _as_text(new_value)

    if old_text == new_text:
        return None

    entry = AuditLog(
        table_name=table_name,
        record_id=record_id,
        field=field,
        old_value=old_text,
        new_value=new_text,
        description=description,
    )
    db.session.add(entry)
    return entry


def apply_change(record, field, new_value, table_name, description=None):
    """Set a field on a record and log the change in one step.

    Returns True if the value actually changed.
    """
    old_value = getattr(record, field)
    entry = record_change(
        table_name=table_name,
        record_id=record.id,
        field=field,
        old_value=old_value,
        new_value=new_value,
        description=description,
    )
    if entry is None:
        return False
    setattr(record, field, new_value)
    return True


def history_for(table_name, record_id):
    """Every logged change to one record, newest first."""
    return (
        AuditLog.query.filter_by(table_name=table_name, record_id=record_id)
        .order_by(AuditLog.changed_at.desc())
        .all()
    )


def recent_changes(limit=100):
    return AuditLog.query.order_by(AuditLog.changed_at.desc()).limit(limit).all()
