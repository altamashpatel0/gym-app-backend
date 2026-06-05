from sqlalchemy import Column, Integer, Date, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from database import Base


class Attendance(Base):
    __tablename__ = "attendance"

    id = Column(Integer, primary_key=True, index=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    check_in = Column(DateTime, server_default=func.now())
    check_out = Column(DateTime)
    marked_by = Column(Integer, ForeignKey("users.id"))
    date = Column(Date, server_default=func.current_date())

    member = relationship("Member", back_populates="attendance")
    marker = relationship("User")
