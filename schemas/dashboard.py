from __future__ import annotations
from datetime import date
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel


class DashboardStats(BaseModel):
    total_members:    int
    active_members:   int
    expiring_soon:    int
    expired_members:  int
    today_collection: Decimal
    total_revenue:    Decimal
    today_attendance: int

    # Day/Night member counts — always computed across all members,
    # independent of any shift filter applied to the other fields above.
    day_members:   int = 0
    night_members: int = 0

    model_config = {"from_attributes": True}


class ExpiringMemberOut(BaseModel):
    member_id:      int
    name:           str
    phone:          str
    email:          Optional[str] = None
    plan_name:      Optional[str] = None
    plan_end_date:  Optional[date] = None
    days_remaining: Optional[int] = None

    model_config = {"from_attributes": True}
