from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, func
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(150), unique=True, nullable=False, index=True)
    phone = Column(String(20))
    password_hash = Column(Text, nullable=False)
    role = Column(String(20), default="staff")  # owner|admin|staff|trainer
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
