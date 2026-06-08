from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from datetime import date, datetime
from database import get_db
from models import Attendance, User
from schemas import AttendanceCreate, AttendanceOut
from core.deps import get_current_user

router = APIRouter(prefix="/api/attendance", tags=["attendance"])


@router.get("/today", response_model=List[AttendanceOut])
def today_attendance(db: Session = Depends(get_db), _=Depends(get_current_user)):
    today = date.today()
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
    # Prevent duplicate same-day check-in
    existing = db.query(Attendance).filter(
        Attendance.member_id == data.member_id,
        Attendance.date == date.today()
    ).first()
    if existing:
        raise HTTPException(400, "Already checked in today")
    record = Attendance(member_id=data.member_id, marked_by=current_user.id)
    db.add(record)
    db.commit()
    db.refresh(record)
    return db.query(Attendance).options(joinedload(Attendance.member)).filter(Attendance.id == record.id).first()


@router.put("/{attendance_id}/checkout")
def checkout(attendance_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    record = db.query(Attendance).filter(Attendance.id == attendance_id).first()
    if not record:
        raise HTTPException(404, "Not found")
    record.check_out = datetime.utcnow()
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
