from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime, Text, ForeignKey, func
from sqlalchemy.orm import relationship
from database import Base


class Member(Base):
    __tablename__ = "members"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(150))
    phone = Column(String(20), nullable=False)
    address = Column(Text)
    age = Column(Integer, nullable=True)
    gender = Column(String(10))
    photo_url = Column(Text)
    plan_id = Column(Integer, ForeignKey("plans.id"))
    join_date = Column(Date, server_default=func.current_date())
    renewal_date = Column(Date)
    plan_start_date = Column(Date, nullable=True)   # when current plan started
    plan_end_date = Column(Date, nullable=True)     # when current plan expires
    status = Column(String(20), default="active")  # active|expired|paused
    # Day/Night shift the member is assigned to. Stored as a plain validated
    # string (same convention as `status`/`gender`/`payment_mode` elsewhere
    # in this codebase) rather than a native DB enum, so it can be added to
    # existing PostgreSQL databases with a simple, reversible ALTER TABLE
    # (see migrations/002_add_shift_to_members.sql). server_default="Day"
    # ensures every pre-existing row is backfilled automatically.
    shift = Column(String(10), nullable=False, server_default="Day", default="Day")
    assigned_trainer_id = Column(Integer, ForeignKey("users.id"))
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    plan = relationship("Plan", back_populates="members")
    trainer = relationship("User", foreign_keys=[assigned_trainer_id])
    payments = relationship("Payment", back_populates="member")
    attendance = relationship("Attendance", back_populates="member")

    # FIX: was defined outside the class body — SQLAlchemy never registered it
    documents = relationship(
        "MemberDocument",
        back_populates="member",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
