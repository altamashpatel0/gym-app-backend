# ─────────────────────────────────────────────────────────────────────────────
# APPLY THIS TO YOUR REAL models/member.py — DO NOT USE THIS AS A FULL FILE.
#
# Context: two different uploads were both named "member.py" in this chat
# (models/member.py and schemas/member.py), so one silently overwrote the
# other before I could read it. I only have schemas/member.py now. I do NOT
# have your real models/member.py — specifically not the ShiftEnum
# definition it must contain (schemas/member.py does `from models.member
# import ShiftEnum`, so your real model file defines it, even though the
# copy pasted earlier in this chat did not).
#
# The good news: these 3 new columns are fully independent of ShiftEnum,
# `status`, or anything else in the Member model. Just add the 3 lines
# below inside your existing `class Member(Base):` body — e.g. right after
# the `shift = Column(...)` line — and nothing else needs to change.
# ─────────────────────────────────────────────────────────────────────────────

    # ── Attendance Pause (NEW) ──────────────────────────────────────────────
    # Completely separate from `status` (active/expired/paused). This only
    # controls whether the member is allowed to check in for gym attendance.
    # Always owner-controlled — never set automatically anywhere in the app.
    attendance_paused = Column(Boolean, nullable=False, server_default="false", default=False)
    attendance_pause_reason = Column(Text, nullable=True)
    attendance_paused_at = Column(DateTime, nullable=True)
    # ─────────────────────────────────────────────────────────────────────────

# Requires these imports already present at the top of the file:
#   from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime, Text, ForeignKey, func
# (Boolean, Text, and DateTime are standard SQLAlchemy column types — if your
# real file already imports Boolean/Text/DateTime for other columns like
# `photo_url = Column(Text)`, no import changes are needed at all.)
