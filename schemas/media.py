"""
schemas/media.py
----------------
Pydantic v2 schemas for photo-upload and document endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Photo upload
# ---------------------------------------------------------------------------

class PhotoUploadResponse(BaseModel):
    """Returned after a successful photo upload."""

    model_config = ConfigDict(from_attributes=True)

    member_id: int
    photo_url: str        # view URL — renders directly in browser
    download_url: str
    message: str = "Photo uploaded successfully."


# ---------------------------------------------------------------------------
# Document CRUD
# ---------------------------------------------------------------------------

DocumentType = Literal["aadhaar", "pan", "agreement", "medical", "other"]


class MemberDocumentOut(BaseModel):
    """Full document record returned to the client."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    member_id: int
    document_name: str
    document_type: str
    file_url: Optional[str]          # view URL (renderable in browser for images)
    download_url: Optional[str]      # force-download URL
    mime_type: Optional[str]
    uploaded_at: datetime


class MemberDocumentListOut(BaseModel):
    """Paginated list of documents for a member."""

    items: list[MemberDocumentOut]
    total: int


class DocumentDeleteResponse(BaseModel):
    message: str
    document_id: int
