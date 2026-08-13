from __future__ import annotations

import logging
import os
import re
import unicodedata
from typing import Optional
from config import settings
import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)


# ============================================================
# Constants
# ============================================================

PHOTOS_FOLDER = "members/photos"
DOCUMENTS_FOLDER = "members/documents"

ALLOWED_IMAGE_MIMES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
}

ALLOWED_DOCUMENT_MIMES = {
    "application/pdf",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

BLOCKED_MIMES = {
    "application/zip",
    "application/x-zip-compressed",
    "application/x-rar-compressed",
    "application/x-tar",
    "application/x-sh",
    "application/x-executable",
    "application/x-msdownload",
    "text/x-python",
    "text/x-shellscript",
    "application/x-httpd-php",
    "application/javascript",
}

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

PRESIGNED_URL_EXPIRY = 3600  # 1 hour

# Extension used when building deterministic photo keys, keyed by detected
# MIME type (not by the client-supplied filename, which can't be trusted).
_MIME_TO_EXTENSION = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


# ============================================================
# Deterministic member-photo key builder
# ============================================================

def build_member_photo_key(member_id: int, mime_type: str, version: Optional[int] = None) -> str:
    """
    Build a collision-free, member-specific object key for a profile photo:

        members/photos/{member_id}/profile-v{version}.{ext}

    `version` defaults to a millisecond timestamp, which is monotonically
    increasing and unique per upload — this avoids needing an extra DB
    column just to track a version counter, while still giving each
    member's photos their own namespace so two members uploading
    "photo.jpg" at the same time can never collide.
    """
    import time

    ext = _MIME_TO_EXTENSION.get(mime_type, "jpg")
    v = version if version is not None else int(time.time() * 1000)
    return f"{PHOTOS_FOLDER}/{member_id}/profile-v{v}.{ext}"


# ============================================================
# Deterministic member-document key builder
# ============================================================

def build_member_document_key(member_id: int, filename: str, unique_id: Optional[str] = None) -> str:
    """
    Build a collision-free, member-specific object key for a document:

        members/documents/{member_id}/{unique_id}-{safe_filename}

    `unique_id` defaults to a short uuid4 hex, guaranteeing uniqueness even
    when the same member uploads two files with the identical original
    filename (e.g. re-uploading "aadhaar.pdf" after a correction).
    """
    import uuid

    uid = unique_id or uuid.uuid4().hex[:12]
    safe_name = sanitize_filename(filename)
    return f"{DOCUMENTS_FOLDER}/{member_id}/{uid}-{safe_name}"


# ============================================================
# Filename sanitization
# ============================================================

def sanitize_filename(filename: str) -> str:
    filename = os.path.basename(filename.strip())

    filename = unicodedata.normalize("NFKD", filename)
    filename = filename.encode("ascii", "ignore").decode("ascii")

    filename = re.sub(r"[^\w.\-]", "_", filename)
    filename = re.sub(r"\.{2,}", ".", filename)

    name, _, ext = filename.rpartition(".")

    name = name[:100]
    ext = ext[:10]

    filename = f"{name}.{ext}" if ext else name[:100]

    return filename or "unnamed"


# ============================================================
# B2 Storage Service
# ============================================================

class B2StorageService:

    def __init__(self) -> None:
        self._client = None
        self._configured = False

    # --------------------------------------------------------
    # Configuration
    # --------------------------------------------------------

    def _ensure_configured(self) -> None:
        if self._configured:
            return

        endpoint = settings.B2_ENDPOINT.strip()
        bucket_name = settings.B2_BUCKET_NAME.strip()
        key_id = settings.B2_KEY_ID.strip()
        application_key = settings.B2_APPLICATION_KEY.strip()

        missing = [
            name
            for name, value in [
                ("B2_ENDPOINT", endpoint),
                ("B2_BUCKET_NAME", bucket_name),
                ("B2_KEY_ID", key_id),
                ("B2_APPLICATION_KEY", application_key),
            ]
            if not value
        ]

        if missing:
            raise RuntimeError(
                f"Missing B2 configuration: {', '.join(missing)}"
            )

        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=key_id,
            aws_secret_access_key=application_key,
            region_name="us-east-005",
        )

        self._bucket_name = bucket_name
        self._configured = True

    # --------------------------------------------------------
    # Upload
    # --------------------------------------------------------

    def upload_file(
        self,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
        folder: str = "documents",
        object_key: Optional[str] = None,
    ) -> dict:
        """
        Upload *file_bytes* to B2.

        If `object_key` is provided, it is used verbatim (this is how
        member-photo uploads get their deterministic, collision-free key —
        see `build_member_photo_key`). Otherwise the key is derived from the
        sanitized filename, exactly as before.
        """

        self._ensure_configured()

        self._validate_file(
            file_bytes=file_bytes,
            mime_type=mime_type,
            folder=folder,
        )

        safe_name = sanitize_filename(filename)

        if object_key:
            file_key = object_key
        else:
            b2_folder = PHOTOS_FOLDER if folder == "photos" else DOCUMENTS_FOLDER
            file_key = f"{b2_folder}/{safe_name}"

        try:
            self._client.put_object(
                Bucket=self._bucket_name,
                Key=file_key,
                Body=file_bytes,
                ContentType=mime_type,
            )

            logger.info(
                "B2 upload successful: bucket=%s key=%s",
                self._bucket_name,
                file_key,
            )

        except (BotoCoreError, ClientError) as exc:
            logger.exception("B2 upload failed: %s", exc)
            raise RuntimeError(f"B2 upload failed: {exc}") from exc

        view_url = self._generate_presigned_url(
            file_key=file_key,
            mime_type=mime_type,
            download=False,
        )

        download_url = self._generate_presigned_url(
            file_key=file_key,
            mime_type=mime_type,
            download=True,
        )

        return {
            "file_id": file_key,
            "filename": safe_name,
            "view_url": view_url,
            "download_url": download_url,
        }

    # --------------------------------------------------------
    # Verify
    # --------------------------------------------------------

    def verify_object_exists(self, file_key: str) -> bool:
        """
        Confirm an object was actually written to B2 (HEAD request — no
        body transfer). Used right after upload, before the DB is updated,
        and by the Cloudinary->B2 data-migration script before it marks a
        record as migrated.
        """
        self._ensure_configured()

        if not file_key:
            return False

        try:
            self._client.head_object(Bucket=self._bucket_name, Key=file_key)
            return True
        except (BotoCoreError, ClientError) as exc:
            logger.warning("B2 object verification failed for %s: %s", file_key, exc)
            return False

    # --------------------------------------------------------
    # Delete
    # --------------------------------------------------------

    def delete_file(self, file_id: str) -> bool:

        self._ensure_configured()

        if not file_id:
            return False

        try:
            self._client.delete_object(
                Bucket=self._bucket_name,
                Key=file_id,
            )

            logger.info(
                "B2 delete successful: bucket=%s key=%s",
                self._bucket_name,
                file_id,
            )

            return True

        except (BotoCoreError, ClientError) as exc:
            logger.warning(
                "B2 delete failed for %s: %s",
                file_id,
                exc,
            )
            return False

    # --------------------------------------------------------
    # Presigned URL
    # --------------------------------------------------------

    def generate_presigned_url(
        self,
        file_key: str,
        mime_type: Optional[str] = None,
        download: bool = False,
    ) -> str:
        """
        Generate a fresh, time-limited (1 hour) presigned GET URL for an
        existing B2 object. Public method — this is what
        routers/members.py calls on every member read to turn a stored
        `photo_storage_key` into a usable `photo_url`, since the bucket is
        private and presigned URLs are never persisted to Postgres.
        """

        self._ensure_configured()

        params = {
            "Bucket": self._bucket_name,
            "Key": file_key,
        }

        if mime_type:
            params["ResponseContentType"] = mime_type

        if download:
            filename = os.path.basename(file_key)

            params["ResponseContentDisposition"] = (
                f'attachment; filename="{filename}"'
            )

        try:
            return self._client.generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=PRESIGNED_URL_EXPIRY,
            )

        except (BotoCoreError, ClientError) as exc:
            logger.exception(
                "Failed generating B2 presigned URL: %s",
                exc,
            )
            raise RuntimeError(
                f"Failed generating B2 URL: {exc}"
            ) from exc

    # Backward-compatible alias for the old private name used elsewhere in
    # this file (upload_file).
    _generate_presigned_url = generate_presigned_url

    # --------------------------------------------------------
    # Validation
    # --------------------------------------------------------

    @staticmethod
    def _validate_file(
        file_bytes: bytes,
        mime_type: str,
        folder: str,
    ) -> None:

        if len(file_bytes) > MAX_FILE_SIZE_BYTES:
            raise ValueError(
                f"File size {len(file_bytes) / 1_048_576:.1f} MB "
                f"exceeds the 10 MB limit."
            )

        if mime_type in BLOCKED_MIMES:
            raise ValueError(
                f"File type '{mime_type}' is not allowed."
            )

        if folder == "photos":

            if mime_type not in ALLOWED_IMAGE_MIMES:
                raise ValueError(
                    f"'{mime_type}' is not an allowed image type. "
                    "Accepted: jpg, jpeg, png, webp."
                )

        elif folder == "documents":

            if mime_type not in ALLOWED_DOCUMENT_MIMES:
                raise ValueError(
                    f"'{mime_type}' is not an allowed document type."
                )


# ============================================================
# Singleton
# ============================================================

_b2_storage_service: Optional[B2StorageService] = None


def get_b2_storage_service() -> B2StorageService:

    global _b2_storage_service

    if _b2_storage_service is None:
        _b2_storage_service = B2StorageService()

    return _b2_storage_service