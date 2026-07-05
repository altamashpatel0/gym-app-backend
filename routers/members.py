"""
routers/members.py  — ADD SHIFT FIELD
────────────────────────────────────────────────────────────────────────────────
WHY CHANGED:
  1. GET /api/members  — added optional `shift` query param; filters DB results
     when provided, ignored when omitted (backwards compatible).
  2. POST /api/members — `shift` arrives in MemberCreate, stored directly.
  3. PUT  /api/members/{id} — `shift` in MemberUpdate applied when not None.
  The route signatures and response shapes are otherwise unchanged.
────────────────────────────────────────────────────────────────────────────────
"""

from typing     import Optional
from fastapi    import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from database        import get_db
from models.member   import Member, ShiftEnum
from schemas.member  import MemberCreate, MemberUpdate, MemberResponse
# from dependencies  import get_current_user   # ← keep your existing auth dep

router = APIRouter(prefix="/api/members", tags=["members"])


# ── List ──────────────────────────────────────────────────────────────────────
@router.get("", response_model=dict)
def list_members(
    search: Optional[str]      = Query(None),
    status: Optional[str]      = Query(None),
    # ── NEW ───────────────────────────────────────────────────────────────────
    shift:  Optional[ShiftEnum] = Query(None, description="Filter by shift: Day or Night"),
    # ─────────────────────────────────────────────────────────────────────────
    page:   int                = Query(1, ge=1),
    limit:  int                = Query(20, ge=1, le=200),
    db:     Session            = Depends(get_db),
    # current_user = Depends(get_current_user),
):
    q = db.query(Member).options(joinedload(Member.plan))

    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(Member.name.ilike(like), Member.phone.ilike(like), Member.email.ilike(like))
        )
    if status:
        q = q.filter(Member.status == status)

    # ── NEW: filter by shift when provided ────────────────────────────────────
    if shift:
        q = q.filter(Member.shift == shift.value)
    # ─────────────────────────────────────────────────────────────────────────

    total = q.count()
    items = q.order_by(Member.id.desc()).offset((page - 1) * limit).limit(limit).all()

    return {"items": items, "total": total, "page": page, "limit": limit}


# ── Create ────────────────────────────────────────────────────────────────────
@router.post("", response_model=MemberResponse, status_code=201)
def create_member(
    data: MemberCreate,
    db:   Session = Depends(get_db),
    # current_user = Depends(get_current_user),
):
    member = Member(**data.model_dump())
    # Pydantic returns ShiftEnum instance; SQLAlchemy stores its .value string
    member.shift = data.shift.value if isinstance(data.shift, ShiftEnum) else data.shift
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


# ── Read ──────────────────────────────────────────────────────────────────────
@router.get("/{member_id}", response_model=MemberResponse)
def get_member(member_id: int, db: Session = Depends(get_db)):
    member = db.query(Member).options(joinedload(Member.plan)).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return member


# ── Update ────────────────────────────────────────────────────────────────────
@router.put("/{member_id}", response_model=MemberResponse)
def update_member(
    member_id: int,
    data:      MemberUpdate,
    db:        Session = Depends(get_db),
    # current_user = Depends(get_current_user),
):
    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    update_data = data.model_dump(exclude_unset=True)

    # ── NEW: coerce ShiftEnum → string before ORM assignment ─────────────────
    if "shift" in update_data and isinstance(update_data["shift"], ShiftEnum):
        update_data["shift"] = update_data["shift"].value
    # ─────────────────────────────────────────────────────────────────────────

    for field, value in update_data.items():
        setattr(member, field, value)

    db.commit()
    db.refresh(member)
    return member


# ── Delete ────────────────────────────────────────────────────────────────────
@router.delete("/{member_id}", status_code=204)
def delete_member(member_id: int, db: Session = Depends(get_db)):
    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    db.delete(member)
    db.commit()
