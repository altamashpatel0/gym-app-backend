from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Date
from typing import Optional
from datetime import date
from decimal import Decimal
from database import get_db
from models import Member, Payment
from schemas import RevenueReportOut, RevenueReport
from core.deps import owner_or_admin

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/revenue", response_model=RevenueReportOut)
def revenue_report(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: Session = Depends(get_db),
    _=Depends(owner_or_admin),
):
    q = db.query(
        cast(Payment.paid_at, Date).label("date"),
        func.sum(Payment.amount).label("total")
    )
    if from_date:
        q = q.filter(cast(Payment.paid_at, Date) >= from_date)
    if to_date:
        q = q.filter(cast(Payment.paid_at, Date) <= to_date)
    rows = q.group_by(cast(Payment.paid_at, Date)).order_by(cast(Payment.paid_at, Date)).all()
    data = [RevenueReport(date=str(r.date), total=Decimal(str(r.total))) for r in rows]
    total = sum(r.total for r in data) if data else Decimal("0")
    return RevenueReportOut(data=data, total=total)


@router.get("/active-members")
def active_members_report(db: Session = Depends(get_db), _=Depends(owner_or_admin)):
    members = db.query(Member).filter(Member.status == "active").all()
    return {
        "count": len(members),
        "members": [
            {"id": m.id, "name": m.name, "phone": m.phone, "renewal_date": str(m.renewal_date) if m.renewal_date else None}
            for m in members
        ]
    }


@router.get("/due-members")
def due_members_report(db: Session = Depends(get_db), _=Depends(owner_or_admin)):
    today = date.today()
    members = db.query(Member).filter(Member.renewal_date <= today, Member.status == "active").all()
    return {
        "count": len(members),
        "members": [
            {"id": m.id, "name": m.name, "phone": m.phone, "renewal_date": str(m.renewal_date) if m.renewal_date else None}
            for m in members
        ]
    }
