"""
routers/media.py
----------------
Handles:
  POST   /api/members/{member_id}/photo
  POST   /api/members/{member_id}/documents
  GET    /api/members/{member_id}/documents
  DELETE /api/documents/{document_id}

All existing routes are untouched.  This router adds only new paths.
"""

from __future__ import annotations

import logging
from typing import Literal

import magic  # python-magic: MIME detection from file bytes (not filename)
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from core.deps import get_current_user, owner_or_admin
from database import get_db
from models import Member, MemberDocument
from schemas.media import (
    DocumentDeleteResponse,
    MemberDocumentListOut,
    MemberDocumentOut,
    PhotoUploadResponse,
)
from services.google_drive import (
    ALLOWED_DOCUMENT_MIMES,
    ALLOWED_IMAGE_MIMES,
    MAX_FILE_SIZE_BYTES,
    get_drive_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["media"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_DOCUMENT_TYPES = {"aadhaar", "pan", "agreement", "medical", "other"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_member_or_404(member_id: int, db: Session) -> Member:
    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found.")
    return member


def _detect_mime(file_bytes: bytes) -> str:
    """Use libmagic to detect MIME type from file content (not extension)."""
    return magic.from_buffer(file_bytes, mime=True)


def _read_upload(upload: UploadFile, max_bytes: int = MAX_FILE_SIZE_BYTES) -> bytes:
    """Read UploadFile into bytes, enforcing size limit."""
    # Read in one shot; for large files Starlette streams, but 10 MB is small
    contents = upload.file.read()
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds the {max_bytes // 1_048_576} MB limit.",
        )
    return contents


# ---------------------------------------------------------------------------
# FEATURE 1 — Member photo upload
# ---------------------------------------------------------------------------


@router.post(
    "/api/members/{member_id}/photo",
    response_model=PhotoUploadResponse,
    summary="Upload or replace a member's profile photo",
    description=(
        "Accepts jpg / jpeg / png / webp, max 10 MB. "
        "Stores the image in Google Drive (GymManagementTool/Members/Photos/) "
        "and saves the public URL in the member record."
    ),
    status_code=status.HTTP_200_OK,
)
async def upload_member_photo(
    member_id: int,
    photo: UploadFile = File(..., description="Profile photo (jpg/jpeg/png/webp, max 10 MB)"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    member = _get_member_or_404(member_id, db)

    # Read bytes
    file_bytes = _read_upload(photo)
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # Detect MIME from content (not filename)
    mime_type = _detect_mime(file_bytes)

    if mime_type not in ALLOWED_IMAGE_MIMES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"'{mime_type}' is not an accepted image type. "
                "Accepted formats: jpg, jpeg, png, webp."
            ),
        )

    drive = get_drive_service()

    # Delete old photo from Drive if it exists
    if member.photo_url and "id=" in member.photo_url:
        try:
            old_file_id = member.photo_url.split("id=")[1].split("&")[0]
            drive.delete_file(old_file_id)
        except Exception as exc:
            logger.warning("Could not delete old photo from Drive: %s", exc)

    # Upload new photo
    try:
        result = drive.upload_file(
            file_bytes=file_bytes,
            filename=photo.filename or f"member_{member_id}_photo",
            mime_type=mime_type,
            folder="photos",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Drive upload failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to upload photo to storage.")

    # Persist view URL
    member.photo_url = result["view_url"]
    db.commit()
    db.refresh(member)

    return PhotoUploadResponse(
        member_id=member_id,
        photo_url=result["view_url"],
        download_url=result["download_url"],
        message="Photo uploaded successfully.",
    )


# ---------------------------------------------------------------------------
# FEATURE 2 — Member document upload
# ---------------------------------------------------------------------------


@router.post(
    "/api/members/{member_id}/documents",
    response_model=MemberDocumentOut,
    summary="Upload a document for a member",
    description=(
        "Supported document_type values: aadhaar | pan | agreement | medical | other. "
        "Accepted file types: pdf, jpg, jpeg, png, webp, doc, docx. Max 10 MB."
    ),
    status_code=status.HTTP_201_CREATED,
)
async def upload_member_document(
    member_id: int,
    document: UploadFile = File(..., description="Document file (pdf/image/docx, max 10 MB)"),
    document_name: str = Form(..., description="Human-readable label, e.g. 'Aadhaar Card Front'"),
    document_type: str = Form(
        ...,
        description="One of: aadhaar | pan | agreement | medical | other",
    ),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # Validate document_type
    if document_type.lower() not in VALID_DOCUMENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid document_type. Must be one of: {', '.join(sorted(VALID_DOCUMENT_TYPES))}",
        )

    member = _get_member_or_404(member_id, db)

    file_bytes = _read_upload(document)
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    mime_type = _detect_mime(file_bytes)

    if mime_type not in ALLOWED_DOCUMENT_MIMES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"'{mime_type}' is not an accepted document type. "
                "Accepted: pdf, jpg, jpeg, png, webp, doc, docx."
            ),
        )

    drive = get_drive_service()

    try:
        result = drive.upload_file(
            file_bytes=file_bytes,
            filename=document.filename or f"member_{member_id}_doc",
            mime_type=mime_type,
            folder="documents",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Drive upload failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to upload document to storage.")

    doc = MemberDocument(
        member_id=member_id,
        document_name=document_name.strip(),
        document_type=document_type.lower(),
        file_url=result["view_url"],
        download_url=result["download_url"],
        drive_file_id=result["file_id"],
        mime_type=mime_type,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.get(
    "/api/members/{member_id}/documents",
    response_model=MemberDocumentListOut,
    summary="List all documents for a member",
)
def list_member_documents(
    member_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _get_member_or_404(member_id, db)

    docs = (
        db.query(MemberDocument)
        .filter(MemberDocument.member_id == member_id)
        .order_by(MemberDocument.uploaded_at.desc())
        .all()
    )
    return MemberDocumentListOut(items=docs, total=len(docs))


@router.delete(
    "/api/documents/{document_id}",
    response_model=DocumentDeleteResponse,
    summary="Delete a member document",
    description="Deletes the document record and removes the file from Google Drive.",
)
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(owner_or_admin),
):
    doc = db.query(MemberDocument).filter(MemberDocument.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Remove from Drive
    if doc.drive_file_id:
        try:
            get_drive_service().delete_file(doc.drive_file_id)
        except Exception as exc:
            logger.warning("Could not delete Drive file %s: %s", doc.drive_file_id, exc)

    db.delete(doc)
    db.commit()

    return DocumentDeleteResponse(
        message="Document deleted successfully.",
        document_id=document_id,
    )
