"""
routers/media.py
----------------
Handles:
  POST   /api/members/{member_id}/photo
  POST   /api/members/{member_id}/documents
  GET    /api/members/{member_id}/documents
  DELETE /api/documents/{document_id}

Storage backend: Backblaze B2 (private bucket, S3-compatible API) for BOTH
member profile photos and member documents. Cloudinary has been fully
removed from this file and from the project's dependencies.

Route paths and response field names (photo_url, download_url, file_url,
document_name, document_type, ...) are UNCHANGED from before this
migration — the frontend needs no changes.

Legacy compatibility: rows created before this migration may still have
`photo_url` / `file_url` / `drive_file_id` pointing at Cloudinary and no
`photo_storage_key` / `storage_key`. Those values are returned as-is,
unmodified, until scripts/migrate_cloudinary_to_b2.py migrates them. This
file never calls the Cloudinary API (the SDK is gone) — legacy values are
just plain strings we pass through.
"""

from __future__ import annotations

import logging

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
from services.b2_storage import (
    ALLOWED_DOCUMENT_MIMES,
    ALLOWED_IMAGE_MIMES,
    MAX_FILE_SIZE_BYTES,
    build_member_document_key,
    build_member_photo_key,
    get_b2_storage_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["media"])

VALID_DOCUMENT_TYPES = {"aadhaar", "pan", "agreement", "medical", "other"}


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
    contents = upload.file.read()
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds the {max_bytes // 1_048_576} MB limit.",
        )
    return contents


def _resolve_document_urls(doc: MemberDocument, storage):
    """
    Return (file_url, download_url) for a document response.

    - storage_key set  -> fresh B2 presigned URLs, generated dynamically,
                           never persisted.
    - storage_key NULL -> legacy Cloudinary values, returned exactly as
                           stored (plain strings — no API call needed).
    """
    if doc.storage_key:
        try:
            view_url = storage.generate_presigned_url(doc.storage_key, mime_type=doc.mime_type)
            download_url = storage.generate_presigned_url(
                doc.storage_key, mime_type=doc.mime_type, download=True
            )
            return view_url, download_url
        except Exception as exc:
            logger.warning(
                "Could not generate B2 presigned URL for document %s (key=%s): %s",
                doc.id, doc.storage_key, exc,
            )
            return None, None
    return doc.file_url, doc.download_url


# ---------------------------------------------------------------------------
# FEATURE 1 — Member photo upload (Backblaze B2)
# ---------------------------------------------------------------------------


@router.post(
    "/api/members/{member_id}/photo",
    response_model=PhotoUploadResponse,
    summary="Upload or replace a member's profile photo",
    description=(
        "Accepts jpg / jpeg / png / webp, max 10 MB. "
        "Stores the image in a private Backblaze B2 bucket "
        "(members/photos/{member_id}/) and saves only the object key in "
        "the member record. `photo_url` in the response is a freshly "
        "generated, time-limited presigned URL."
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

    file_bytes = _read_upload(photo)
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    mime_type = _detect_mime(file_bytes)

    if mime_type not in ALLOWED_IMAGE_MIMES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"'{mime_type}' is not an accepted image type. "
                "Accepted formats: jpg, jpeg, png, webp."
            ),
        )

    storage = get_b2_storage_service()

    # Previous B2 key only (NOT any legacy Cloudinary URL — that's a
    # separate, untouched migration path). None if this member has never
    # had a B2 photo before (either brand new, or still on Cloudinary).
    previous_b2_key = member.photo_storage_key

    new_key = build_member_photo_key(member_id=member_id, mime_type=mime_type)

    # 1) Upload NEW photo first. Any failure here -> DB untouched, old
    #    photo (Cloudinary or B2) untouched.
    try:
        result = storage.upload_file(
            file_bytes=file_bytes,
            filename=photo.filename or f"member_{member_id}_photo",
            mime_type=mime_type,
            folder="photos",
            object_key=new_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("B2 photo upload failed for member %s: %s", member_id, exc)
        raise HTTPException(
            status_code=502,
            detail="Failed to upload photo to storage. Please try again.",
        )

    uploaded_key = result["file_id"]

    # 2) Verify the object actually landed before touching the DB.
    if not storage.verify_object_exists(uploaded_key):
        logger.error(
            "B2 upload for member %s reported success but object not found: %s",
            member_id, uploaded_key,
        )
        try:
            storage.delete_file(uploaded_key)
        except Exception:
            pass
        raise HTTPException(status_code=502, detail="Photo upload could not be verified. Please try again.")

    # 3) Update DB and commit. Old photo untouched until this succeeds.
    try:
        member.photo_storage_key = uploaded_key
        # Clear the legacy Cloudinary URL column now that this member has a
        # live B2 photo. Only this member's row is touched — never anyone
        # else's Cloudinary data.
        member.photo_url = None
        db.commit()
        db.refresh(member)
    except Exception as exc:
        db.rollback()
        logger.exception("DB commit failed after B2 upload for member %s: %s", member_id, exc)
        try:
            storage.delete_file(uploaded_key)
        except Exception as cleanup_exc:
            logger.warning("Cleanup of orphaned B2 object %s failed: %s", uploaded_key, cleanup_exc)
        raise HTTPException(status_code=500, detail="Failed to save the new photo. Please try again.")

    # 4) Only now clean up the PREVIOUS B2 photo (best-effort; never fails
    #    the request). Legacy Cloudinary assets are never touched here.
    if previous_b2_key and previous_b2_key != uploaded_key:
        try:
            storage.delete_file(previous_b2_key)
        except Exception as exc:
            logger.warning(
                "Could not delete previous B2 photo %s for member %s: %s",
                previous_b2_key, member_id, exc,
            )

    return PhotoUploadResponse(
        member_id=member_id,
        photo_url=result["view_url"],
        download_url=result["download_url"],
        message="Photo uploaded successfully.",
    )


# ---------------------------------------------------------------------------
# FEATURE 2 — Member document upload (Backblaze B2)
# ---------------------------------------------------------------------------


@router.post(
    "/api/members/{member_id}/documents",
    response_model=MemberDocumentOut,
    summary="Upload a document for a member",
    description=(
        "Supported document_type values: aadhaar | pan | agreement | medical | other. "
        "Accepted file types: pdf, jpg, jpeg, png, webp, doc, docx. Max 10 MB. "
        "Stored in a private Backblaze B2 bucket (members/documents/{member_id}/)."
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

    storage = get_b2_storage_service()

    new_key = build_member_document_key(member_id=member_id, filename=document.filename or "document")

    # 1) Upload first.
    try:
        result = storage.upload_file(
            file_bytes=file_bytes,
            filename=document.filename or f"member_{member_id}_doc",
            mime_type=mime_type,
            folder="documents",
            object_key=new_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("B2 document upload failed for member %s: %s", member_id, exc)
        raise HTTPException(status_code=502, detail="Failed to upload document to storage.")

    uploaded_key = result["file_id"]

    # 2) Verify before touching the DB.
    if not storage.verify_object_exists(uploaded_key):
        logger.error(
            "B2 document upload for member %s reported success but object not found: %s",
            member_id, uploaded_key,
        )
        try:
            storage.delete_file(uploaded_key)
        except Exception:
            pass
        raise HTTPException(status_code=502, detail="Document upload could not be verified. Please try again.")

    # 3) Create the DB row and commit. `file_url`/`download_url` stay NULL —
    #    they're generated dynamically from `storage_key` on every read
    #    (see _resolve_document_urls / list_member_documents below).
    try:
        doc = MemberDocument(
            member_id=member_id,
            document_name=document_name.strip(),
            document_type=document_type.lower(),
            storage_key=uploaded_key,
            file_url=None,
            download_url=None,
            drive_file_id=None,
            mime_type=mime_type,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
    except Exception as exc:
        db.rollback()
        logger.exception("DB commit failed after B2 document upload for member %s: %s", member_id, exc)
        try:
            storage.delete_file(uploaded_key)
        except Exception as cleanup_exc:
            logger.warning("Cleanup of orphaned B2 object %s failed: %s", uploaded_key, cleanup_exc)
        raise HTTPException(status_code=500, detail="Failed to save the document. Please try again.")

    view_url, download_url = _resolve_document_urls(doc, storage)

    return MemberDocumentOut(
        id=doc.id,
        member_id=doc.member_id,
        document_name=doc.document_name,
        document_type=doc.document_type,
        file_url=view_url,
        download_url=download_url,
        mime_type=doc.mime_type,
        uploaded_at=doc.uploaded_at,
    )


# ---------------------------------------------------------------------------
# FEATURE 3 — List member documents
# ---------------------------------------------------------------------------


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

    storage = get_b2_storage_service()
    items = []
    for doc in docs:
        view_url, download_url = _resolve_document_urls(doc, storage)
        items.append(
            MemberDocumentOut(
                id=doc.id,
                member_id=doc.member_id,
                document_name=doc.document_name,
                document_type=doc.document_type,
                file_url=view_url,
                download_url=download_url,
                mime_type=doc.mime_type,
                uploaded_at=doc.uploaded_at,
            )
        )

    return MemberDocumentListOut(items=items, total=len(items))


# ---------------------------------------------------------------------------
# FEATURE 4 — Delete a document
# ---------------------------------------------------------------------------


@router.delete(
    "/api/documents/{document_id}",
    response_model=DocumentDeleteResponse,
    summary="Delete a member document",
    description="Deletes the document record and removes the file from Backblaze B2.",
)
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(owner_or_admin),
):
    doc = db.query(MemberDocument).filter(MemberDocument.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    if doc.storage_key:
        try:
            get_b2_storage_service().delete_file(doc.storage_key)
        except Exception as exc:
            logger.warning(
                "Could not delete B2 object %s for document %s: %s",
                doc.storage_key, document_id, exc,
            )
    elif doc.drive_file_id:
        # Legacy Cloudinary-backed document that hasn't been migrated yet.
        # The Cloudinary SDK has been removed from this project, so we can
        # no longer call its delete API. Per the migration requirements we
        # must not touch Cloudinary data anyway at this stage — the DB
        # record is removed, but the Cloudinary asset is intentionally
        # left in place (orphaned) until it's either migrated or manually
        # cleaned up in the Cloudinary dashboard.
        logger.warning(
            "Document %s was still on Cloudinary (public_id=%s) and has not been "
            "migrated to B2 — its Cloudinary asset was NOT deleted (SDK removed). "
            "Run scripts/migrate_cloudinary_to_b2.py before bulk-deleting legacy documents.",
            document_id, doc.drive_file_id,
        )

    db.delete(doc)
    db.commit()

    return DocumentDeleteResponse(
        message="Document deleted successfully.",
        document_id=document_id,
    )
