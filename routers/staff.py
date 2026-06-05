from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from models import User
from schemas import UserCreate, UserOut
from core.deps import owner_or_admin
from core.security import hash_password

router = APIRouter(prefix="/api/staff", tags=["staff"])


@router.get("", response_model=List[UserOut])
def list_staff(db: Session = Depends(get_db), _=Depends(owner_or_admin)):
    return db.query(User).filter(User.role != "owner").order_by(User.created_at.desc()).all()


@router.post("", response_model=UserOut)
def create_staff(data: UserCreate, db: Session = Depends(get_db), _=Depends(owner_or_admin)):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(400, "Email already exists")
    user = User(
        name=data.name,
        email=data.email,
        phone=data.phone,
        password_hash=hash_password(data.password),
        role=data.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.put("/{user_id}", response_model=UserOut)
def update_staff(user_id: int, data: UserCreate, db: Session = Depends(get_db), _=Depends(owner_or_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Not found")
    user.name = data.name
    user.phone = data.phone
    user.role = data.role
    if data.password:
        user.password_hash = hash_password(data.password)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}")
def delete_staff(user_id: int, db: Session = Depends(get_db), _=Depends(owner_or_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Not found")
    user.is_active = False
    db.commit()
    return {"message": "Deactivated"}
