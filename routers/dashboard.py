from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, cast, Date
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal

# Timezone-aware India Standard Time, used specifically for the attendance
# figure below so it reflects the IST calendar day (attendance data is
# recorded in IST — see models/attendance.py / services/attendance_service.py).
IST = ZoneInfo("Asia/Kolkata")
from typing import List, Optional
from database import get_db
from models import Member, Payment, Attendance
from schemas import DashboardStats, ExpiringMemberOut
from core.deps import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
def dashboard_stats(
    shift: Optional[str] = Query(None, description="Optional shift filter: Day or Night"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    today = date.today()
    soon = today + timedelta(days=7)
    shift_norm = shift.lower() if shift else None

    # Base member query, optionally scoped to a shift. Every member-derived
    # count below (total/active/expiring/expired) is built off this same
    # base, so a shift filter consistently narrows all of them together.
    member_q = db.query(Member)
    if shift_norm:
        member_q = member_q.filter(func.lower(Member.shift) == shift_norm)

    total = member_q.with_entities(func.count(Member.id)).scalar() or 0

    active = member_q.filter(Member.status == "active") \
        .with_entities(func.count(Member.id)).scalar() or 0

    # Expiring soon: active members whose plan_end_date falls in next 7 days
    expiring = member_q.filter(
        Member.plan_end_date.between(today, soon),
        Member.status == "active",
    ).with_entities(func.count(Member.id)).scalar() or 0

    # Expired: members with plan_end_date in the past (or status == expired)
    expired = member_q.filter(
        Member.status == "expired",
    ).with_entities(func.count(Member.id)).scalar() or 0

    # Also count active members whose plan_end_date has passed (not yet marked expired)
    overdue_active = member_q.filter(
        Member.status == "active",
        Member.plan_end_date < today,
    ).with_entities(func.count(Member.id)).scalar() or 0
    expired = expired + overdue_active

    # Revenue/collection — join to Member so the optional shift filter
    # applies here too (a "Day" tab shows Day members' collections only).
    payment_q = db.query(Payment).join(Member, Payment.member_id == Member.id)
    if shift_norm:
        payment_q = payment_q.filter(func.lower(Member.shift) == shift_norm)

    today_col = payment_q.filter(
        cast(Payment.paid_at, Date) == today
    ).with_entities(func.coalesce(func.sum(Payment.amount), 0)).scalar()

    total_revenue = payment_q.with_entities(
        func.coalesce(func.sum(Payment.amount), 0)
    ).scalar()

    # Attendance — same shift-join treatment.
    attendance_q = db.query(Attendance).join(Member, Attendance.member_id == Member.id)
    if shift_norm:
        attendance_q = attendance_q.filter(func.lower(Member.shift) == shift_norm)

    today_ist = datetime.now(IST).date()
    today_att = attendance_q.filter(
        Attendance.date == today_ist
    ).with_entities(func.count(Attendance.id)).scalar() or 0

    # Day/Night member counts — ALWAYS computed across ALL members,
    # independent of the `shift` query param above, so these two numbers
    # stay meaningful no matter which dashboard tab is currently selected.
    day_members = db.query(func.count(Member.id)).filter(
        func.lower(Member.shift) == "day"
    ).scalar() or 0

    night_members = db.query(func.count(Member.id)).filter(
        func.lower(Member.shift) == "night"
    ).scalar() or 0

    return DashboardStats(
        total_members=total,
        active_members=active,
        expiring_soon=expiring,
        expired_members=expired,
        today_collection=Decimal(str(today_col or 0)),
        total_revenue=Decimal(str(total_revenue or 0)),
        today_attendance=today_att,
        day_members=day_members,
        night_members=night_members,
    )


@router.get("/expiring-members", response_model=List[ExpiringMemberOut])
def expiring_members(
    days: int = 7,
    shift: Optional[str] = Query(None, description="Optional shift filter: Day or Night"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Return active members whose plan expires within the next `days` days (default 7).
    Ordered by plan_end_date ascending (soonest first). `shift` is optional and
    backward-compatible — omitting it preserves the exact prior behavior.
    """
    today = date.today()
    cutoff = today + timedelta(days=days)

    q = (
        db.query(Member)
        .options(joinedload(Member.plan))
        .filter(
            Member.status == "active",
            Member.plan_end_date.isnot(None),
            Member.plan_end_date.between(today, cutoff),
        )
    )
    if shift:
        q = q.filter(func.lower(Member.shift) == shift.lower())

    members = q.order_by(Member.plan_end_date.asc()).all()

    result = []
    for m in members:
        days_remaining = (m.plan_end_date - today).days if m.plan_end_date else None
        result.append(
            ExpiringMemberOut(
                member_id=m.id,
                name=m.name,
                phone=m.phone,
                email=m.email,
                plan_name=m.plan.name if m.plan else None,
                plan_end_date=m.plan_end_date,
                days_remaining=days_remaining,
            )
        )
    return result
