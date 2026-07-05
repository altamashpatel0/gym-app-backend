from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, cast, Date
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional
from database import get_db
from models import Member, Payment, Attendance
from models.member import ShiftEnum
from schemas import DashboardStats, ExpiringMemberOut
from core.deps import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
def dashboard_stats(
    # ── NEW: optional shift filter — when provided, every total below is
    # scoped to that shift. When omitted, totals cover all members (unchanged
    # behavior). ──────────────────────────────────────────────────────────────
    shift: Optional[ShiftEnum] = Query(None, description="Filter all stats by shift: Day or Night"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    today = date.today()
    soon = today + timedelta(days=7)

    # Base member query, scoped by shift when a filter is active.
    member_q = db.query(Member)
    if shift:
        member_q = member_q.filter(Member.shift == shift.value)

    total = member_q.with_entities(func.count(Member.id)).scalar() or 0

    active = member_q.filter(
        Member.status == "active"
    ).with_entities(func.count(Member.id)).scalar() or 0

    # Expiring soon: active members whose plan_end_date falls in next 7 days
    expiring = db.query(func.count(Member.id)).filter(
        Member.plan_end_date.between(today, soon),
        Member.status == "active",
        *([Member.shift == shift.value] if shift else []),
    ).scalar() or 0

    # Expired: members with plan_end_date in the past (or status == expired)
    expired = db.query(func.count(Member.id)).filter(
        Member.status == "expired",
        *([Member.shift == shift.value] if shift else []),
    ).scalar() or 0

    # Also count active members whose plan_end_date has passed (not yet marked expired)
    overdue_active = db.query(func.count(Member.id)).filter(
        Member.status == "active",
        Member.plan_end_date < today,
        *([Member.shift == shift.value] if shift else []),
    ).scalar() or 0
    expired = expired + overdue_active

    # ── Revenue / attendance — join through Member so shift filtering applies.
    today_collection_q = db.query(
        func.coalesce(func.sum(Payment.amount), 0)
    ).filter(cast(Payment.paid_at, Date) == today)

    total_revenue_q = db.query(func.coalesce(func.sum(Payment.amount), 0))

    today_att_q = db.query(func.count(Attendance.id)).filter(Attendance.date == today)

    if shift:
        # Adjust `Payment.member_id` / `Attendance.member_id` below if your
        # models use a different FK column name.
        today_collection_q = today_collection_q.join(
            Member, Member.id == Payment.member_id
        ).filter(Member.shift == shift.value)
        total_revenue_q = total_revenue_q.join(
            Member, Member.id == Payment.member_id
        ).filter(Member.shift == shift.value)
        today_att_q = today_att_q.join(
            Member, Member.id == Attendance.member_id
        ).filter(Member.shift == shift.value)

    today_col = today_collection_q.scalar()
    total_revenue = total_revenue_q.scalar()
    today_att = today_att_q.scalar() or 0

    # ── NEW: Day / Night member counts. These are always computed across ALL
    # members regardless of the `shift` filter above, so the two cards on the
    # dashboard stay meaningful even while a shift filter is active elsewhere.
    day_members = db.query(func.count(Member.id)).filter(
        Member.shift == ShiftEnum.DAY.value
    ).scalar() or 0
    night_members = db.query(func.count(Member.id)).filter(
        Member.shift == ShiftEnum.NIGHT.value
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
    # ── NEW: optional shift filter, same semantics as /stats ────────────────
    shift: Optional[ShiftEnum] = Query(None, description="Filter by shift: Day or Night"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Return active members whose plan expires within the next `days` days (default 7).
    Ordered by plan_end_date ascending (soonest first).
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

    # ── NEW: scope by shift when provided ────────────────────────────────────
    if shift:
        q = q.filter(Member.shift == shift.value)

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
