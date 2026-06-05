from sqlalchemy import Column, Integer, String, Boolean, Numeric, DateTime, Text, func
from sqlalchemy.orm import relationship
from database import Base


class Plan(Base):
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    duration_months = Column(Integer, nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

    members = relationship("Member", back_populates="plan")
