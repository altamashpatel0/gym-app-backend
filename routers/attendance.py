from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from datetime import date, datetime
from zoneinfo import ZoneInfo
from database import get_db
from models import Attendance, User
from schemas import (
    AttendanceCreate,
    AttendanceOut,
    CheckInRequest,
    CheckOutRequest,
    AttendanceRecordOut,
    AttendanceDashboardSummary,
)
from core.deps import get_current_user
from services import attendance_service

router = APIRouter(prefix="/api/attendance", tags=["attendance"])

# Timezone-aware India Standard Time, used instead of naive datetime.utcnow()
# so recorded timestamps are unambiguous.
IST = ZoneInfo("Asia/Kolkata")


# ── Manual attendance system (check-in / check-out) ──────────────────────────
# NEW endpoints. These live alongside the pre-existing endpoints below
# (which remain untouched for backward compatibility) and are the surface
# a future biometric integration would call into instead of/along with the
# manual buttons — no DB schema changes would be required for that, since
# it would just call attendance_service.check_in/check_out the same way.

@router.post("/check-in", response_model=AttendanceRecordOut)
def manual_check_in(
    data: CheckInRequest,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    return attendance_service.check_in(db, data.member_id)


@router.post("/check-out", response_model=AttendanceRecordOut)
def manual_check_out(
    data: CheckOutRequest,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    return attendance_service.check_out(db, data.member_id)


@router.get("/dashboard-summary", response_model=AttendanceDashboardSummary)
def attendance_dashboard_summary(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    return attendance_service.get_dashboard_summary(db)


@router.get("/member/{member_id}", response_model=Optional[AttendanceRecordOut])
def member_today_attendance(
    member_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    return attendance_service.get_member_today(db, member_id)


@router.get("/history/{member_id}", response_model=List[AttendanceRecordOut])
def member_attendance_history(
    member_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    return attendance_service.get_history(db, member_id)


@router.get("/today", response_model=List[AttendanceOut])
def today_attendance(db: Session = Depends(get_db), _=Depends(get_current_user)):
    today = datetime.now(IST).date()
    return (
        db.query(Attendance)
        .options(joinedload(Attendance.member))
        .filter(Attendance.date == today)
        .order_by(Attendance.check_in.desc())
        .all()
    )


@router.get("", response_model=List[AttendanceOut])
def list_attendance(
    date_str: Optional[str] = None,
    member_id: Optional[int] = None,
    page: int = 1,
    limit: int = 30,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = db.query(Attendance).options(joinedload(Attendance.member))
    if date_str:
        q = q.filter(Attendance.date == date_str)
    if member_id:
        q = q.filter(Attendance.member_id == member_id)
    return q.order_by(Attendance.check_in.desc()).offset((page - 1) * limit).limit(limit).all()


@router.post("", response_model=AttendanceOut)
def mark_attendance(
    data: AttendanceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.now(IST)
    today = now.date()
    # Prevent duplicate same-day check-in
    existing = db.query(Attendance).filter(
        Attendance.member_id == data.member_id,
        Attendance.date == today
    ).first()
    if existing:
        raise HTTPException(400, "Already checked in today")
    record = Attendance(
        member_id=data.member_id,
        marked_by=current_user.id,
        check_in=now,
        date=today,
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return db.query(Attendance).options(joinedload(Attendance.member)).filter(Attendance.id == record.id).first()


@router.put("/{attendance_id}/checkout")
def checkout(attendance_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    record = db.query(Attendance).filter(Attendance.id == attendance_id).first()
    if not record:
        raise HTTPException(404, "Not found")
    now = datetime.now(IST)
    record.check_out = now
    record.updated_at = now
    db.commit()
    return {"message": "Checked out"}


@router.delete("/{attendance_id}")
def delete_attendance(attendance_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    record = db.query(Attendance).filter(Attendance.id == attendance_id).first()
    if not record:
        raise HTTPException(404, "Not found")
    db.delete(record)
    db.commit()
    return {"message": "Attendance deleted"}
