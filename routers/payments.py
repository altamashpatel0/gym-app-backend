from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import cast, Date
from typing import List, Optional
from datetime import date, timedelta
from decimal import Decimal
from math import floor
from database import get_db
from models import Payment, Member, User, Plan
from schemas import PaymentCreate, PaymentUpdate, PaymentOut, PendingDue
from core.deps import get_current_user

router = APIRouter(prefix="/api/payments", tags=["payments"])


def _calculate_valid_dates(
    member: Member,
    plan: Optional[Plan],
    amount: Decimal,
    valid_from: Optional[date],
    valid_to: Optional[date],
) -> tuple[Optional[date], Optional[date]]:
    """
    Compute plan_start_date / plan_end_date.

    Rules:
    - If caller supplies valid_from + valid_to → use them as-is.
    - Else if plan is known → derive duration from amount/price ratio
      (multi-month support: paying 2x the plan price = 2x duration).
    - Start date defaults to today (or member's existing plan_end_date
      if still in the future — i.e. extension of active plan).
    """
    if valid_from and valid_to:
        return valid_from, valid_to

    today = date.today()

    if plan is None:
        return valid_from, valid_to  # Can't calculate without plan

    plan_price = Decimal(str(plan.price))
    if plan_price <= 0:
        return valid_from, valid_to

    # How many months does this payment cover?
    months_paid = floor(float(amount) / float(plan_price)) * plan.duration_months
    if months_paid <= 0:
        months_paid = plan.duration_months  # Default to 1 cycle if underpaid/exact

    # Start from today, or extend from existing end date if still active
    if valid_from:
        start = valid_from
    elif member.plan_end_date and member.plan_end_date >= today:
        start = member.plan_end_date + timedelta(days=1)
    else:
        start = today

    # Calculate end date: months_paid months after start
    # Safely handle month addition (including month-end edge cases)
    from calendar import monthrange
    year, month = start.year, start.month
    for _ in range(months_paid):
        month += 1
        if month > 12:
            month = 1
            year += 1
    day = min(start.day, monthrange(year, month)[1])
    end = date(year, month, day) - timedelta(days=1)

    return start, end


@router.get("/pending-dues", response_model=List[PendingDue])
def pending_dues(db: Session = Depends(get_db), _=Depends(get_current_user)):
    today = date.today()
    members = db.query(Member).options(joinedload(Member.plan)).filter(
        Member.status == "active",
        Member.renewal_date <= today,
    ).all()
    result = []
    for m in members:
        days = (today - m.renewal_date).days if m.renewal_date else None
        result.append(PendingDue(
            member_id=m.id,
            name=m.name,
            phone=m.phone,
            renewal_date=m.renewal_date,
            plan_name=m.plan.name if m.plan else None,
            days_overdue=days,
        ))
    return result


@router.get("", response_model=List[PaymentOut])
def list_payments(
    member_id: Optional[int] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = db.query(Payment).options(joinedload(Payment.member))
    if member_id:
        q = q.filter(Payment.member_id == member_id)
    if from_date:
        q = q.filter(cast(Payment.paid_at, Date) >= from_date)
    if to_date:
        q = q.filter(cast(Payment.paid_at, Date) <= to_date)
    q = q.order_by(Payment.paid_at.desc())
    return q.offset((page - 1) * limit).limit(limit).all()


@router.post("", response_model=PaymentOut)
def collect_payment(
    data: PaymentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    member = db.query(Member).options(joinedload(Member.plan)).filter(
        Member.id == data.member_id
    ).first()
    if not member:
        raise HTTPException(404, "Member not found")

    plan: Optional[Plan] = None
    plan_id = data.plan_id or member.plan_id
    if plan_id:
        plan = db.query(Plan).filter(Plan.id == plan_id).first()

    # Calculate valid_from / valid_to with multi-month logic
    valid_from, valid_to = _calculate_valid_dates(
        member=member,
        plan=plan,
        amount=data.amount,
        valid_from=data.valid_from,
        valid_to=data.valid_to,
    )

    payment = Payment(
        member_id=data.member_id,
        plan_id=plan_id,
        amount=data.amount,
        payment_mode=data.payment_mode,
        note=data.note,
        valid_from=valid_from,
        valid_to=valid_to,
        collected_by=current_user.id,
    )
    db.add(payment)

    # Update member plan dates + renewal_date + status
    if valid_from:
        member.plan_start_date = valid_from
    if valid_to:
        member.plan_end_date = valid_to
        member.renewal_date = valid_to
    if plan_id:
        member.plan_id = plan_id
    member.status = "active"

    db.commit()
    db.refresh(payment)
    return db.query(Payment).options(joinedload(Payment.member)).filter(
        Payment.id == payment.id
    ).first()


@router.get("/{payment_id}", response_model=PaymentOut)
def get_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    payment = db.query(Payment).options(joinedload(Payment.member)).filter(
        Payment.id == payment_id
    ).first()
    if not payment:
        raise HTTPException(404, "Payment not found")
    return payment


@router.put("/{payment_id}", response_model=PaymentOut)
def update_payment(
    payment_id: int,
    data: PaymentUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Edit an existing payment record."""
    payment = db.query(Payment).options(joinedload(Payment.member)).filter(
        Payment.id == payment_id
    ).first()
    if not payment:
        raise HTTPException(404, "Payment not found")

    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(payment, field, value)

    # If valid_to changed, keep member's renewal_date / plan_end_date in sync
    # only when this is the member's most recent payment
    if "valid_to" in updates and updates["valid_to"] is not None:
        member = payment.member
        latest_payment = (
            db.query(Payment)
            .filter(Payment.member_id == member.id)
            .order_by(Payment.paid_at.desc())
            .first()
        )
        if latest_payment and latest_payment.id == payment_id:
            member.plan_end_date = updates["valid_to"]
            member.renewal_date = updates["valid_to"]

    if "valid_from" in updates and updates["valid_from"] is not None:
        member = payment.member
        latest_payment = (
            db.query(Payment)
            .filter(Payment.member_id == member.id)
            .order_by(Payment.paid_at.desc())
            .first()
        )
        if latest_payment and latest_payment.id == payment_id:
            member.plan_start_date = updates["valid_from"]

    db.commit()
    db.refresh(payment)
    return db.query(Payment).options(joinedload(Payment.member)).filter(
        Payment.id == payment_id
    ).first()


@router.delete("/{payment_id}")
def delete_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Delete a payment record."""
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(404, "Payment not found")

    member_id = payment.member_id
    db.delete(payment)
    db.flush()  # reflect deletion before recalculating

    # Recalculate member plan dates from remaining payments
    latest = (
        db.query(Payment)
        .filter(Payment.member_id == member_id)
        .order_by(Payment.paid_at.desc())
        .first()
    )
    member = db.query(Member).filter(Member.id == member_id).first()
    if member:
        if latest:
            member.plan_start_date = latest.valid_from
            member.plan_end_date = latest.valid_to
            member.renewal_date = latest.valid_to
        else:
            # No payments left — clear dates
            member.plan_start_date = None
            member.plan_end_date = None

    db.commit()
    return {"message": "Payment deleted"}
