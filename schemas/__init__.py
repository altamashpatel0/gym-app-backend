from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional, List
from datetime import date, datetime
from decimal import Decimal

# Allowed values for Member.shift. Kept as a simple tuple (not a DB enum)
# to match this codebase's existing convention for status/gender/payment_mode.
ALLOWED_SHIFTS = ("Day", "Night")


def _validate_shift(v):
    """Normalize + validate a shift value against ALLOWED_SHIFTS.
    Accepts case-insensitive input ('day', 'NIGHT', ...) and returns the
    canonical 'Day'/'Night' form so downstream comparisons stay simple.
    """
    if v is None:
        return v
    v = str(v).strip()
    for allowed in ALLOWED_SHIFTS:
        if v.lower() == allowed.lower():
            return allowed
    raise ValueError(f"Invalid shift '{v}'. Allowed values: {', '.join(ALLOWED_SHIFTS)}")


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
    age: Optional[int] = Field(None, ge=1, le=120)
    gender: Optional[str] = None
    plan_id: Optional[int] = None
    join_date: Optional[date] = None
    renewal_date: Optional[date] = None
    assigned_trainer_id: Optional[int] = None
    shift: str = "Day"  # NEW: every member must have a shift; defaults to Day

    @field_validator("shift", mode="before")
    @classmethod
    def _check_shift_create(cls, v):
        return _validate_shift(v) if v is not None else "Day"

class MemberUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    age: Optional[int] = Field(None, ge=1, le=120)
    gender: Optional[str] = None
    plan_id: Optional[int] = None
    join_date: Optional[date] = None
    renewal_date: Optional[date] = None
    status: Optional[str] = None
    assigned_trainer_id: Optional[int] = None
    shift: Optional[str] = None  # NEW: optional so partial updates don't force it

    @field_validator("shift", mode="before")
    @classmethod
    def _check_shift_update(cls, v):
        return _validate_shift(v)

class MemberOut(BaseModel):
    id: int
    name: str
    phone: str
    email: Optional[str]
    address: Optional[str]
    age: Optional[int]
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
    shift: str = "Day"  # NEW: always returned so the frontend can badge/filter on it

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

# due members (expired plan)
class DueMemberOut(BaseModel):
    member_id: int
    name: str
    phone: str
    email: Optional[str]
    plan_name: Optional[str]
    plan_end_date: Optional[date]
    days_overdue: Optional[int]

# expiring members
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
    # NEW (additive, optional): surfaced so existing GET /api/attendance/today
    # and /api/attendance list endpoints also expose the manual attendance
    # system's status/duration without changing any existing field names or
    # shapes. Old clients that ignore unknown fields are unaffected.
    status: Optional[str] = None
    duration_minutes: Optional[int] = None

    class Config:
        from_attributes = True


# ── Manual Attendance (check-in / check-out) ─────────────────────────────────
# New, additive schemas for the manual attendance system. These do not
# replace AttendanceCreate/AttendanceOut above (which stay untouched for the
# pre-existing endpoints) — they back the new /api/attendance/check-in,
# /check-out, /today, /member/{id}, /history/{id} and /dashboard-summary
# endpoints only.

ATTENDANCE_STATUS_IN = "IN"
ATTENDANCE_STATUS_OUT = "OUT"


class CheckInRequest(BaseModel):
    member_id: int


class CheckOutRequest(BaseModel):
    member_id: int


class AttendanceRecordOut(BaseModel):
    id: int
    member_id: int
    member_name: Optional[str] = None
    attendance_date: date
    check_in: Optional[datetime] = None
    check_out: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AttendanceDashboardSummary(BaseModel):
    today_checkins: int
    today_checkouts: int
    members_currently_inside: int
    average_workout_minutes: float


# ── Dashboard ─────────────────────────────────────────────────────────────────

class DashboardStats(BaseModel):
    total_members: int
    active_members: int
    expiring_soon: int
    expired_members: int          # NEW: due/expired count
    today_collection: Decimal
    total_revenue: Decimal        # NEW: all-time revenue
    today_attendance: int
    # NEW: Day/Night member counts. Always computed across ALL members,
    # independent of any `shift` filter applied to the other fields above,
    # so these two numbers stay meaningful no matter which dashboard tab
    # ("All" / "Day" / "Night") is currently selected on the frontend.
    day_members: int = 0
    night_members: int = 0


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
