from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, func
from database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200))
    message = Column(Text)
    type = Column(String(30))  # renewal|payment|info
    member_id = Column(Integer, ForeignKey("members.id"))
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
