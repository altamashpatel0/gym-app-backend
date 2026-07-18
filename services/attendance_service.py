"""
services/attendance_service.py
-------------------------------
Business logic for the manual attendance system (check-in / check-out).

Kept as a service layer (mirrors services/cloudinary_storage.py) so the
router stays thin and the rules below are unit-testable / reusable by a
future biometric-device integration without touching the DB schema:

  - Member cannot check in twice on the same day.
  - Member must be checked in ("IN") before they can check out.
  - duration_minutes is computed once, at checkout time.
  - Exactly one attendance row per member per day (enforced here at the
    application layer; see migrations note for the optional DB-level
    unique index).

Nothing here modifies the existing `Attendance` columns (id, member_id,
check_in, check_out, marked_by, date) — it only reads/writes the new
additive columns (status, duration_minutes, created_at, updated_at).
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from models import Attendance, Member
from schemas import ATTENDANCE_STATUS_IN, ATTENDANCE_STATUS_OUT

# All check-in/check-out timestamps are recorded timezone-aware in India
# Standard Time, rather than naive UTC, so stored times are unambiguous.
IST = ZoneInfo("Asia/Kolkata")


def _get_member_or_404(db: Session, member_id: int) -> Member:
    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    return member


def _today_record(db: Session, member_id: int, for_update: bool = False) -> Optional[Attendance]:
    q = db.query(Attendance).filter(
        Attendance.member_id == member_id,
        Attendance.date == date.today(),
    )
    if for_update:
        q = q.with_for_update()
    return q.first()


def _to_record_out(record: Attendance) -> dict:
    """Map an Attendance ORM row -> the manual-attendance API shape.

    Note the `date` DB column is surfaced to clients as `attendance_date`
    (schema-level rename only — the DB column itself is untouched).
    """
    return {
        "id": record.id,
        "member_id": record.member_id,
        "member_name": record.member.name if record.member else None,
        "attendance_date": record.date,
        "check_in": record.check_in,
        "check_out": record.check_out,
        "duration_minutes": record.duration_minutes,
        "status": record.status,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def check_in(db: Session, member_id: int) -> dict:
    _get_member_or_404(db, member_id)

    existing = _today_record(db, member_id)
    if existing and existing.status == ATTENDANCE_STATUS_IN:
        raise HTTPException(status_code=400, detail="Member is already checked in today")
    if existing and existing.status == ATTENDANCE_STATUS_OUT:
        # Already completed a full in/out cycle today — one record per
        # member per day, so a second check-in isn't allowed either.
        raise HTTPException(status_code=400, detail="Member has already checked in today")

    now = datetime.now(IST)
    record = Attendance(
        member_id=member_id,
        check_in=now,
        date=date.today(),
        status=ATTENDANCE_STATUS_IN,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    record = (
        db.query(Attendance)
        .options(joinedload(Attendance.member))
        .filter(Attendance.id == record.id)
        .first()
    )
    return _to_record_out(record)


def check_out(db: Session, member_id: int) -> dict:
    _get_member_or_404(db, member_id)

    record = _today_record(db, member_id)
    if not record or record.status != ATTENDANCE_STATUS_IN:
        raise HTTPException(status_code=400, detail="Member has not checked in today")

    now = datetime.now(IST)
    record.check_out = now
    record.status = ATTENDANCE_STATUS_OUT
    if record.check_in:
        # The DB column is a plain DateTime (no timezone type), so a
        # value written as IST-aware can come back from the DB as naive
        # on some drivers. Since every write in this service uses IST,
        # a naive value here is always IST wall-clock time already —
        # reattaching IST simply makes the subtraction below well-defined
        # without changing the resulting duration.
        check_in_dt = record.check_in
        if check_in_dt.tzinfo is None:
            check_in_dt = check_in_dt.replace(tzinfo=IST)
        delta = now - check_in_dt
        record.duration_minutes = max(0, round(delta.total_seconds() / 60))
    db.commit()
    db.refresh(record)
    record = (
        db.query(Attendance)
        .options(joinedload(Attendance.member))
        .filter(Attendance.id == record.id)
        .first()
    )
    return _to_record_out(record)


def get_today(db: Session) -> List[dict]:
    records = (
        db.query(Attendance)
        .options(joinedload(Attendance.member))
        .filter(Attendance.date == date.today())
        .order_by(Attendance.check_in.desc())
        .all()
    )
    return [_to_record_out(r) for r in records]


def get_member_today(db: Session, member_id: int) -> Optional[dict]:
    _get_member_or_404(db, member_id)
    record = (
        db.query(Attendance)
        .options(joinedload(Attendance.member))
        .filter(Attendance.member_id == member_id, Attendance.date == date.today())
        .first()
    )
    return _to_record_out(record) if record else None


def get_history(db: Session, member_id: int) -> List[dict]:
    _get_member_or_404(db, member_id)
    records = (
        db.query(Attendance)
        .options(joinedload(Attendance.member))
        .filter(Attendance.member_id == member_id)
        .order_by(Attendance.date.desc(), Attendance.check_in.desc())
        .all()
    )
    return [_to_record_out(r) for r in records]


def get_dashboard_summary(db: Session) -> dict:
    today = date.today()
    base_q = db.query(Attendance).filter(Attendance.date == today)

    today_checkins = base_q.with_entities(func.count(Attendance.id)).scalar() or 0

    today_checkouts = (
        base_q.filter(Attendance.status == ATTENDANCE_STATUS_OUT)
        .with_entities(func.count(Attendance.id))
        .scalar()
        or 0
    )

    members_currently_inside = (
        db.query(Attendance)
        .filter(Attendance.date == today, Attendance.status == ATTENDANCE_STATUS_IN)
        .with_entities(func.count(Attendance.id))
        .scalar()
        or 0
    )

    avg_minutes = (
        db.query(func.avg(Attendance.duration_minutes))
        .filter(Attendance.date == today, Attendance.duration_minutes.isnot(None))
        .scalar()
    )

    return {
        "today_checkins": today_checkins,
        "today_checkouts": today_checkouts,
        "members_currently_inside": members_currently_inside,
        "average_workout_minutes": round(float(avg_minutes), 1) if avg_minutes is not None else 0.0,
    }
