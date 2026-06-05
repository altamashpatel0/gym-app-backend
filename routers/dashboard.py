from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, cast, Date
from datetime import date, timedelta
from decimal import Decimal
from typing import List
from database import get_db
from models import Member, Payment, Attendance
from schemas import DashboardStats, ExpiringMemberOut
from core.deps import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
def dashboard_stats(db: Session = Depends(get_db), _=Depends(get_current_user)):
    today = date.today()
    soon = today + timedelta(days=7)

    total = db.query(func.count(Member.id)).scalar() or 0

    active = db.query(func.count(Member.id)).filter(
        Member.status == "active"
    ).scalar() or 0

    # Expiring soon: active members whose plan_end_date falls in next 7 days
    expiring = db.query(func.count(Member.id)).filter(
        Member.plan_end_date.between(today, soon),
        Member.status == "active",
    ).scalar() or 0

    # Expired: members with plan_end_date in the past (or status == expired)
    expired = db.query(func.count(Member.id)).filter(
        Member.status == "expired",
    ).scalar() or 0

    # Also count active members whose plan_end_date has passed (not yet marked expired)
    overdue_active = db.query(func.count(Member.id)).filter(
        Member.status == "active",
        Member.plan_end_date < today,
    ).scalar() or 0
    expired = expired + overdue_active

    today_col = db.query(
        func.coalesce(func.sum(Payment.amount), 0)
    ).filter(
        cast(Payment.paid_at, Date) == today
    ).scalar()

    total_revenue = db.query(
        func.coalesce(func.sum(Payment.amount), 0)
    ).scalar()

    today_att = db.query(
        func.count(Attendance.id)
    ).filter(Attendance.date == today).scalar() or 0

    return DashboardStats(
        total_members=total,
        active_members=active,
        expiring_soon=expiring,
        expired_members=expired,
        today_collection=Decimal(str(today_col or 0)),
        total_revenue=Decimal(str(total_revenue or 0)),
        today_attendance=today_att,
    )


@router.get("/expiring-members", response_model=List[ExpiringMemberOut])
def expiring_members(
    days: int = 7,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Return active members whose plan expires within the next `days` days (default 7).
    Ordered by plan_end_date ascending (soonest first).
    """
    today = date.today()
    cutoff = today + timedelta(days=days)

    members = (
        db.query(Member)
        .options(joinedload(Member.plan))
        .filter(
            Member.status == "active",
            Member.plan_end_date.isnot(None),
            Member.plan_end_date.between(today, cutoff),
        )
        .order_by(Member.plan_end_date.asc())
        .all()
    )

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
