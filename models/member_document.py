"""
models/member_document.py
--------------------------
SQLAlchemy model for member documents (Aadhaar, PAN, Agreement, etc.).
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from database import Base


class MemberDocument(Base):
    __tablename__ = "member_documents"

    id = Column(Integer, primary_key=True, index=True)
    member_id = Column(Integer, ForeignKey("members.id", ondelete="CASCADE"), nullable=False, index=True)
    document_name = Column(String(200), nullable=False)          # human-readable label
    document_type = Column(String(50), nullable=False)           # aadhaar|pan|agreement|medical|other
    file_url = Column(Text, nullable=False)                      # public view URL
    download_url = Column(Text, nullable=True)                   # direct download URL
    drive_file_id = Column(String(200), nullable=True)           # Drive file ID for deletion
    mime_type = Column(String(100), nullable=True)               # stored MIME type
    uploaded_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationship back to Member (optional, read-only)
    member = relationship("Member", back_populates="documents")
