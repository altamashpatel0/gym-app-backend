from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from datetime import date, timedelta
from database import get_db
from models import Member, Payment, Notification
from schemas import NotificationOut
from core.deps import get_current_user

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=List[NotificationOut])
def get_notifications(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Auto-generate notifications from DB state."""
    today = date.today()
    soon = today + timedelta(days=7)
    notifications = []

    # Pull stored notifications
    stored = db.query(Notification).order_by(Notification.created_at.desc()).limit(50).all()
    return stored


@router.post("/{notification_id}/read")
def mark_read(notification_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    n = db.query(Notification).filter(Notification.id == notification_id).first()
    if not n:
        raise HTTPException(404, "Not found")
    n.is_read = True
    db.commit()
    return {"message": "Marked read"}


@router.post("/read-all")
def mark_all_read(db: Session = Depends(get_db), _=Depends(get_current_user)):
    db.query(Notification).filter(Notification.is_read == False).update({"is_read": True})
    db.commit()
    return {"message": "All marked read"}
