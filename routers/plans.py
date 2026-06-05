from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from models import Plan
from schemas import PlanCreate, PlanUpdate, PlanOut
from core.deps import get_current_user, owner_or_admin

router = APIRouter(prefix="/api/plans", tags=["plans"])


@router.get("", response_model=List[PlanOut])
def list_plans(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(Plan).filter(Plan.is_active == True).all()


@router.post("", response_model=PlanOut)
def create_plan(data: PlanCreate, db: Session = Depends(get_db), _=Depends(owner_or_admin)):
    plan = Plan(**data.model_dump())
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


@router.put("/{plan_id}", response_model=PlanOut)
def update_plan(plan_id: int, data: PlanUpdate, db: Session = Depends(get_db), _=Depends(owner_or_admin)):
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "Plan not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(plan, field, value)
    db.commit()
    db.refresh(plan)
    return plan


@router.delete("/{plan_id}")
def delete_plan(plan_id: int, db: Session = Depends(get_db), _=Depends(owner_or_admin)):
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "Plan not found")
    plan.is_active = False
    db.commit()
    return {"message": "Deactivated"}
