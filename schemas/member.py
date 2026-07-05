"""
schemas/member.py  — ADD SHIFT FIELD
────────────────────────────────────────────────────────────────────────────────
WHY CHANGED:
  1. Imported ShiftEnum from models.member (single source of truth).
  2. Added `shift` field to MemberCreate and MemberUpdate with:
       - type validation via ShiftEnum (Pydantic rejects any other value)
       - default of ShiftEnum.DAY so existing callers without `shift` still work
  3. Added `shift` field to MemberResponse so the API always returns it.
  4. MemberUpdate keeps shift Optional so partial PATCH-style PUT still works.
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations
from datetime import date
from typing   import Optional
from pydantic import BaseModel, field_validator

from models.member import ShiftEnum   # single source of truth


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

    # ── NEW ───────────────────────────────────────────────────────────────────
    shift: ShiftEnum = ShiftEnum.DAY
    # ─────────────────────────────────────────────────────────────────────────

    @field_validator("shift", mode="before")
    @classmethod
    def validate_shift(cls, v):
        """Accept both enum members and raw strings; reject anything else."""
        if isinstance(v, ShiftEnum):
            return v
        try:
            return ShiftEnum(v)
        except ValueError:
            raise ValueError(
                f"Invalid shift '{v}'. Allowed values: "
                + ", ".join(e.value for e in ShiftEnum)
            )


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

    # ── NEW ───────────────────────────────────────────────────────────────────
    shift: Optional[ShiftEnum] = None
    # ─────────────────────────────────────────────────────────────────────────

    @field_validator("shift", mode="before")
    @classmethod
    def validate_shift(cls, v):
        if v is None:
            return v
        if isinstance(v, ShiftEnum):
            return v
        try:
            return ShiftEnum(v)
        except ValueError:
            raise ValueError(
                f"Invalid shift '{v}'. Allowed values: "
                + ", ".join(e.value for e in ShiftEnum)
            )


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

    # ── NEW ───────────────────────────────────────────────────────────────────
    shift: ShiftEnum = ShiftEnum.DAY
    # ─────────────────────────────────────────────────────────────────────────

    model_config = {"from_attributes": True}
