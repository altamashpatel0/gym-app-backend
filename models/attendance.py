from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime
from zoneinfo import ZoneInfo

# Timezone-aware India Standard Time. Used as the Python-side (client-side)
# default for every attendance timestamp column below. SQLAlchemy always
# computes a Python-side `default` and includes it directly in the INSERT
# statement, so these IST values take precedence over the DB-side
# `server_default` (which stays only as a harmless fallback for any
# non-ORM insert path — it is never actually reached by this app, so no
# UTC calculation from it ever ends up in attendance data). This does NOT
# alter the existing database schema/columns in any way.
IST = ZoneInfo("Asia/Kolkata")


def _ist_now() -> datetime:
    return datetime.now(IST)


def _ist_today():
    return datetime.now(IST).date()


class Attendance(Base):
    __tablename__ = "attendance"

    id = Column(Integer, primary_key=True, index=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    check_in = Column(DateTime, default=_ist_now, server_default=func.now())
    check_out = Column(DateTime)
    marked_by = Column(Integer, ForeignKey("users.id"))
    # NOTE: kept as `date` (not renamed to `attendance_date`) so existing
    # queries/routers (routers/attendance.py, routers/dashboard.py) that
    # filter on Attendance.date keep working unchanged. The manual
    # check-in/check-out API exposes this same column to clients under the
    # name "attendance_date" via the response schema — see schemas/__init__.py.
    date = Column(Date, default=_ist_today, server_default=func.current_date())

    # ── NEW (manual attendance system) ──────────────────────────────────────
    # Current state of this attendance record. "IN" once checked in, "OUT"
    # once checked out. Kept as a plain validated string (same convention as
    # Member.status/gender/shift elsewhere in this codebase) rather than a
    # native DB enum, so it's a simple additive ALTER TABLE on Postgres.
    # server_default="IN" backfills all pre-existing rows automatically;
    # the migration additionally sets historical rows with a check_out to
    # "OUT" (see migrations/002_add_manual_attendance_fields.sql).
    status = Column(String(10), nullable=False, server_default="IN")

    # Minutes between check_in and check_out, computed at checkout time.
    # Nullable because it's unknown/not-yet-applicable while a member is
    # still checked in (status == "IN").
    duration_minutes = Column(Integer, nullable=True)

    # Bookkeeping timestamps. Distinct from `check_in`, which is a business
    # field (when the member physically checked in) — `created_at` is purely
    # "when this row was written", which matters once biometric devices can
    # also write rows (e.g. backfilled/batched inserts).
    created_at = Column(DateTime, default=_ist_now, server_default=func.now())
    updated_at = Column(DateTime, default=_ist_now, onupdate=_ist_now, server_default=func.now())

    member = relationship("Member", back_populates="attendance")
    marker = relationship("User")
