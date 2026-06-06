from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import date, datetime
from decimal import Decimal


# ── Auth ──────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    password: str
    role: str = "staff"

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserOut(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str]
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


# ── Plans ─────────────────────────────────────────────────────────────────────

class PlanCreate(BaseModel):
    name: str
    duration_months: int
    price: Decimal
    description: Optional[str] = None

class PlanUpdate(BaseModel):
    name: Optional[str] = None
    duration_months: Optional[int] = None
    price: Optional[Decimal] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

class PlanOut(BaseModel):
    id: int
    name: str
    duration_months: int
    price: Decimal
    description: Optional[str]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ── Members ───────────────────────────────────────────────────────────────────

class MemberCreate(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None
    address: Optional[str] = None
    dob: Optional[date] = None
    gender: Optional[str] = None
    plan_id: Optional[int] = None
    join_date: Optional[date] = None
    renewal_date: Optional[date] = None
    assigned_trainer_id: Optional[int] = None

class MemberUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    dob: Optional[date] = None
    gender: Optional[str] = None
    plan_id: Optional[int] = None
    join_date: Optional[date] = None
    renewal_date: Optional[date] = None
    status: Optional[str] = None
    assigned_trainer_id: Optional[int] = None

class MemberOut(BaseModel):
    id: int
    name: str
    phone: str
    email: Optional[str]
    address: Optional[str]
    dob: Optional[date]
    gender: Optional[str]
    photo_url: Optional[str] = None
    plan_id: Optional[int]
    join_date: Optional[date]
    renewal_date: Optional[date]
    plan_start_date: Optional[date]   # NEW
    plan_end_date: Optional[date]     # NEW
    status: str
    assigned_trainer_id: Optional[int]
    plan: Optional[PlanOut]
    created_at: datetime

    class Config:
        from_attributes = True

class MemberListOut(BaseModel):
    items: List[MemberOut]
    total: int
    page: int
    limit: int


# ── Payments ──────────────────────────────────────────────────────────────────

class PaymentCreate(BaseModel):
    member_id: int
    plan_id: Optional[int] = None
    amount: Decimal
    payment_mode: str = "cash"
    note: Optional[str] = None
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None

class PaymentUpdate(BaseModel):
    """For PUT /api/payments/{payment_id} — all fields optional."""
    plan_id: Optional[int] = None
    amount: Optional[Decimal] = None
    payment_mode: Optional[str] = None
    note: Optional[str] = None
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None

class PaymentOut(BaseModel):
    id: int
    member_id: int
    plan_id: Optional[int]
    amount: Decimal
    paid_at: datetime
    payment_mode: str
    note: Optional[str]
    valid_from: Optional[date]
    valid_to: Optional[date]
    member: Optional[MemberOut]

    class Config:
        from_attributes = True

class PendingDue(BaseModel):
    member_id: int
    name: str
    phone: str
    renewal_date: Optional[date]
    plan_name: Optional[str]
    days_overdue: Optional[int]

# NEW: due members (expired plan)
class DueMemberOut(BaseModel):
    member_id: int
    name: str
    phone: str
    email: Optional[str]
    plan_name: Optional[str]
    plan_end_date: Optional[date]
    days_overdue: Optional[int]

# NEW: expiring members
class ExpiringMemberOut(BaseModel):
    member_id: int
    name: str
    phone: str
    email: Optional[str]
    plan_name: Optional[str]
    plan_end_date: Optional[date]
    days_remaining: Optional[int]


# ── Attendance ────────────────────────────────────────────────────────────────

class AttendanceCreate(BaseModel):
    member_id: int

class AttendanceOut(BaseModel):
    id: int
    member_id: int
    check_in: datetime
    check_out: Optional[datetime]
    date: date
    member: Optional[MemberOut]

    class Config:
        from_attributes = True


# ── Dashboard ─────────────────────────────────────────────────────────────────

class DashboardStats(BaseModel):
    total_members: int
    active_members: int
    expiring_soon: int
    expired_members: int          # NEW: due/expired count
    today_collection: Decimal
    total_revenue: Decimal        # NEW: all-time revenue
    today_attendance: int


# ── Reports ───────────────────────────────────────────────────────────────────

class RevenueReport(BaseModel):
    date: str
    total: Decimal

class RevenueReportOut(BaseModel):
    data: List[RevenueReport]
    total: Decimal


# ── Notifications ─────────────────────────────────────────────────────────────

class NotificationOut(BaseModel):
    id: int
    title: Optional[str]
    message: Optional[str]
    type: Optional[str]
    member_id: Optional[int]
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True
