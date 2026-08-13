"""
models/member_document.py
--------------------------
NOTE: this file was NOT among the files uploaded for this migration — only
referenced by name from routers/media.py. It has been reconstructed here
from the exact column list in migrations/001_add_media_storage.sql:

    id, member_id, document_name, document_type, file_url, download_url,
    drive_file_id, mime_type, uploaded_at

Please diff this against your actual models/member_document.py before
merging — if it has extra columns, indexes, or relationships beyond what's
in that migration, re-add them here.

CHANGE FOR THIS MIGRATION: adds `storage_key`, the B2 object key for
documents stored under members/documents/{member_id}/. `file_url` /
`download_url` / `drive_file_id` are kept for backward compatibility with
pre-migration Cloudinary-backed rows (see migrations/006_*.sql, which also
relaxes `file_url` from NOT NULL to nullable — new B2-backed rows no longer
need a value there since routers/media.py generates a fresh presigned URL
dynamically from `storage_key` on every read).
"""

from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship
from database import Base


class MemberDocument(Base):
    __tablename__ = "member_documents"

    id = Column(Integer, primary_key=True, index=True)
    member_id = Column(Integer, ForeignKey("members.id", ondelete="CASCADE"), nullable=False, index=True)
    document_name = Column(String(200), nullable=False)
    document_type = Column(String(50), nullable=False)  # aadhaar|pan|agreement|medical|other

    # Legacy Cloudinary fields — kept for backward compatibility with rows
    # created before this migration. NULL/unused for any document uploaded
    # after this migration (those use `storage_key` instead).
    file_url = Column(Text, nullable=True)       # legacy Cloudinary secure_url only
    download_url = Column(Text, nullable=True)    # legacy Cloudinary fl_attachment URL only
    drive_file_id = Column(String(200), nullable=True)  # legacy Cloudinary public_id only

    # ── B2 (NEW) ─────────────────────────────────────────────────────────────
    # The B2 object key, e.g. "members/documents/191/ab12cd34ef56-aadhaar.pdf".
    # This is the ONLY thing persisted for new uploads — file_url/download_url
    # are generated as fresh presigned URLs on every read, never stored.
    storage_key = Column(Text, nullable=True)
    # ─────────────────────────────────────────────────────────────────────────

    mime_type = Column(String(100), nullable=True)
    uploaded_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    member = relationship("Member", back_populates="documents")
