from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func
from typing import Optional, List
from datetime import date, datetime
from zoneinfo import ZoneInfo
from database import get_db
from models import Member, User
from schemas import (
    MemberCreate, MemberUpdate, MemberOut, MemberListOut, DueMemberOut,
    PauseAttendanceRequest,
)
from core.deps import get_current_user, owner_or_admin

router = APIRouter(prefix="/api/members", tags=["members"])

# Attendance Pause timestamps are recorded in India Standard Time, same
# convention as services/attendance_service.py, so "Paused At" reads
# consistently with check-in/check-out times shown elsewhere in the app.
IST = ZoneInfo("Asia/Kolkata")


@router.get("/due-members", response_model=List[DueMemberOut])
def due_members(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Return members whose plan has expired:
    - status == 'expired', OR
    - status == 'active' but plan_end_date is in the past.
    Ordered by plan_end_date ascending (longest overdue first).
    """
    today = date.today()
    members = (
        db.query(Member)
        .options(joinedload(Member.plan))
        .filter(
            or_(
                Member.status == "expired",
                (Member.status == "active") & (Member.plan_end_date < today),
            )
        )
        .order_by(Member.plan_end_date.asc())
        .all()
    )

    result = []
    for m in members:
        days_overdue = (today - m.plan_end_date).days if m.plan_end_date else None
        result.append(
            DueMemberOut(
                member_id=m.id,
                name=m.name,
                phone=m.phone,
                email=m.email,
                plan_name=m.plan.name if m.plan else None,
                plan_end_date=m.plan_end_date,
                days_overdue=days_overdue,
            )
        )
    return result


@router.get("", response_model=MemberListOut)
def list_members(
    search: Optional[str] = None,
    status: Optional[str] = None,
    shift: Optional[str] = Query(None, description="Filter by shift: Day or Night"),
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Member).options(joinedload(Member.plan))
    if search:
        q = q.filter(or_(
            Member.name.ilike(f"%{search}%"),
            Member.phone.ilike(f"%{search}%"),
            Member.email.ilike(f"%{search}%"),
        ))
    if status:
        q = q.filter(Member.status == status)
    # NEW: optional shift filter (case-insensitive) — used by the Dashboard's
    # shift tabs (GET /api/members?shift=Day|Night). Omitted = all members,
    # preserving prior behavior exactly.
    if shift:
        q = q.filter(func.lower(Member.shift) == shift.lower())
    total = q.count()
    items = q.order_by(Member.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
    return MemberListOut(items=items, total=total, page=page, limit=limit)


@router.post("", response_model=MemberOut)
def create_member(
    data: MemberCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    member = Member(**data.model_dump(), created_by=current_user.id)
    db.add(member)
    db.commit()
    db.refresh(member)
    return db.query(Member).options(joinedload(Member.plan)).filter(Member.id == member.id).first()


@router.get("/{member_id}", response_model=MemberOut)
def get_member(
    member_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    member = db.query(Member).options(joinedload(Member.plan)).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return member


@router.patch("/{member_id}/pause-attendance", response_model=MemberOut)
def pause_attendance(
    member_id: int,
    data: PauseAttendanceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Manually pause a member's ability to check in for attendance.

    This is NOT member.status. It never touches status, payments, renewal,
    or attendance history/calculations — it only sets the three new
    attendance_paused* columns. Only ever triggered by an explicit owner
    action here; nothing in the codebase sets this automatically.
    """
    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    member.attendance_paused = True
    member.attendance_pause_reason = data.reason
    member.attendance_paused_at = datetime.now(IST).replace(tzinfo=None)

    db.commit()
    db.refresh(member)
    return db.query(Member).options(joinedload(Member.plan)).filter(Member.id == member_id).first()


@router.patch("/{member_id}/resume-attendance", response_model=MemberOut)
def resume_attendance(
    member_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually resume a member's ability to check in for attendance."""
    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    member.attendance_paused = False
    member.attendance_pause_reason = None
    member.attendance_paused_at = None

    db.commit()
    db.refresh(member)
    return db.query(Member).options(joinedload(Member.plan)).filter(Member.id == member_id).first()


@router.put("/{member_id}", response_model=MemberOut)
def update_member(
    member_id: int,
    data: MemberUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(member, field, value)
    db.commit()
    db.refresh(member)
    return db.query(Member).options(joinedload(Member.plan)).filter(Member.id == member_id).first()


@router.delete("/{member_id}")
def delete_member(
    member_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(owner_or_admin),
):
    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    db.delete(member)
    db.commit()
    return {"message": "Deleted"}
