from sqlalchemy import Column, Integer, String, Numeric, Date, DateTime, Text, ForeignKey, func
from sqlalchemy.orm import relationship
from database import Base


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id"))
    amount = Column(Numeric(10, 2), nullable=False)
    paid_at = Column(DateTime, server_default=func.now())
    payment_mode = Column(String(20), default="cash")  # cash|upi|card|bank
    note = Column(Text)
    collected_by = Column(Integer, ForeignKey("users.id"))
    valid_from = Column(Date)
    valid_to = Column(Date)

    member = relationship("Member", back_populates="payments")
    plan = relationship("Plan")
    collector = relationship("User")
