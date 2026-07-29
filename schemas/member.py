"""
schemas/member.py
────────────────────────────────────────────────────────────────────────────────
NOTE (fix): previously imported `ShiftEnum` from `models.member`, but that
enum is not actually defined there — models/member.py stores `shift` as a
plain validated string (see migrations/002_add_shift_to_members.sql, which
uses a VARCHAR + CHECK constraint, not a DB enum). Restored to the original,
working string-based validation below instead of inventing an enum. This
does not change the Shift feature's behavior at all — "Day" and "Night" are
still the only accepted values, just validated as strings.
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations
from datetime import date, datetime
from typing   import Optional
from pydantic import BaseModel, field_validator


# Allowed shift values — mirrors the CHECK constraint in
# migrations/002_add_shift_to_members.sql (chk_members_shift_valid).
ALLOWED_SHIFTS = ("Day", "Night")

# ── Attendance Pause reasons (frontend dropdown mirrors this list) ───────────
# Kept as a plain string on the wire (not a DB/model enum) since the reason is
# just a free-form note the owner picks — matches the "Other" option in the
# UI dropdown, which needs to accept arbitrary text.
ATTENDANCE_PAUSE_REASONS = ["Payment Due", "Medical Leave", "Membership Hold", "Other"]


def _validate_shift(v):
    if v is None:
        return v
    if v not in ALLOWED_SHIFTS:
        raise ValueError(f"Invalid shift '{v}'. Allowed values: {', '.join(ALLOWED_SHIFTS)}")
    return v


# ── Create ────────────────────────────────────────────────────────────────────
class MemberCreate(BaseModel):
    name:                str
    phone:               str
    email:               Optional[str]    = None
    address:             Optional[str]    = None
    dob:                 Optional[date]   = None
    age:                 Optional[int]    = None
    gender:              Optional[str]    = None
    plan_id:             Optional[int]    = None
    join_date:           Optional[date]   = None
    renewal_date:        Optional[date]   = None
    status:              str              = "active"
    assigned_trainer_id: Optional[int]   = None

    shift: str = "Day"

    @field_validator("shift")
    @classmethod
    def validate_shift(cls, v):
        return _validate_shift(v)


# ── Update ────────────────────────────────────────────────────────────────────
class MemberUpdate(BaseModel):
    name:                Optional[str]    = None
    phone:               Optional[str]    = None
    email:               Optional[str]    = None
    address:             Optional[str]    = None
    dob:                 Optional[date]   = None
    age:                 Optional[int]    = None
    gender:              Optional[str]    = None
    plan_id:             Optional[int]    = None
    join_date:           Optional[date]   = None
    renewal_date:        Optional[date]   = None
    status:              Optional[str]    = None
    assigned_trainer_id: Optional[int]   = None

    shift: Optional[str] = None

    @field_validator("shift")
    @classmethod
    def validate_shift(cls, v):
        return _validate_shift(v)


# ── Response ──────────────────────────────────────────────────────────────────
class PlanBasic(BaseModel):
    id:   int
    name: str
    model_config = {"from_attributes": True}


class MemberResponse(BaseModel):
    id:                  int
    name:                str
    phone:               str
    email:               Optional[str]
    address:             Optional[str]
    dob:                 Optional[date]
    age:                 Optional[int]
    gender:              Optional[str]
    plan_id:             Optional[int]
    plan:                Optional[PlanBasic]
    join_date:           Optional[date]
    renewal_date:        Optional[date]
    status:              str
    assigned_trainer_id: Optional[int]
    photo_url:           Optional[str]

    shift: str = "Day"

    # ── Attendance Pause (separate from `status`) ─────────────────────────────
    # Read-only here — these are only ever changed via the dedicated
    # /pause-attendance and /resume-attendance endpoints, never through
    # MemberCreate/MemberUpdate.
    attendance_paused: bool = False
    attendance_pause_reason: Optional[str] = None
    attendance_paused_at: Optional[datetime] = None
    # ─────────────────────────────────────────────────────────────────────────

    model_config = {"from_attributes": True}


# ── Attendance Pause request ─────────────────────────────────────────────────
class PauseAttendanceRequest(BaseModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v):
        if not v or not v.strip():
            raise ValueError("A reason is required to pause attendance.")
        return v.strip()
