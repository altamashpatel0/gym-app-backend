"""
services/cloudinary_storage.py
-------------------------------
Cloudinary storage backend for GymOps.

Reads credentials from environment variables:
    CLOUDINARY_CLOUD_NAME
    CLOUDINARY_API_KEY
    CLOUDINARY_API_SECRET

Folder layout in Cloudinary:
    gym_management/members/photos/
    gym_management/members/documents/

Public API mirrors the old GoogleDriveService so call-sites in media.py
need no changes beyond the import.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from typing import Optional

import cloudinary
import cloudinary.uploader
import cloudinary.api

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PHOTOS_FOLDER    = "gym_management/members/photos"
DOCUMENTS_FOLDER = "gym_management/members/documents"

# ---------------------------------------------------------------------------
# Security: allowed MIME types
# (unchanged from the Google Drive version so media.py stays the same)
# ---------------------------------------------------------------------------

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
    "application/msword",                                                        # .doc
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
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

# Map MIME types to Cloudinary resource_type values.
# Cloudinary accepts "image", "video", or "raw" (everything else).
_MIME_TO_RESOURCE_TYPE: dict[str, str] = {
    "image/jpeg": "image",
    "image/jpg":  "image",
    "image/png":  "image",
    "image/webp": "image",
    "application/pdf": "image",   # Cloudinary handles PDFs under "image"
}


def _resource_type_for(mime_type: str) -> str:
    return _MIME_TO_RESOURCE_TYPE.get(mime_type, "raw")


# ---------------------------------------------------------------------------
# Filename sanitisation  (identical logic to the Drive version)
# ---------------------------------------------------------------------------

def sanitize_filename(filename: str) -> str:
    """
    Return a filesystem-safe filename:
    - Strip path components
    - Normalise unicode
    - Replace anything that is not alphanumeric / dot / dash / underscore
    - Collapse consecutive dots (prevent double-extension tricks)
    - Limit total length
    """
    filename = os.path.basename(filename.strip())
    filename = unicodedata.normalize("NFKD", filename)
    filename = filename.encode("ascii", "ignore").decode("ascii")
    filename = re.sub(r"[^\w.\-]", "_", filename)
    filename = re.sub(r"\.{2,}", ".", filename)
    name, _, ext = filename.rpartition(".")
    name = name[:100]
    ext  = ext[:10]
    filename = f"{name}.{ext}" if ext else name[:100]
    return filename or "unnamed"


# ---------------------------------------------------------------------------
# CloudinaryService
# ---------------------------------------------------------------------------

class CloudinaryService:
    """
    Thin wrapper around the Cloudinary Upload & Admin APIs.

    Provides the same public interface as the old GoogleDriveService:
        upload_file(file_bytes, filename, mime_type, folder) -> dict
        delete_file(public_id)                               -> bool

    The returned dict always contains:
        file_id      – Cloudinary public_id (used for deletion)
        filename     – sanitised filename
        view_url     – secure_url (HTTPS, browser-renderable)
        download_url – secure_url with fl_attachment flag for forced download
    """

    def __init__(self) -> None:
        self._configured = False

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def _ensure_configured(self) -> None:
        """Configure the Cloudinary SDK from environment variables (once)."""
        if self._configured:
            return

        cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME", "").strip()
        api_key    = os.environ.get("CLOUDINARY_API_KEY", "").strip()
        api_secret = os.environ.get("CLOUDINARY_API_SECRET", "").strip()

        missing = [
            name for name, val in [
                ("CLOUDINARY_CLOUD_NAME", cloud_name),
                ("CLOUDINARY_API_KEY",    api_key),
                ("CLOUDINARY_API_SECRET", api_secret),
            ] if not val
        ]
        if missing:
            raise RuntimeError(
                f"Missing Cloudinary environment variable(s): {', '.join(missing)}"
            )

        cloudinary.config(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
            secure=True,          # always use HTTPS URLs
        )
        self._configured = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def upload_file(
        self,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
        folder: str = "documents",
    ) -> dict:
        """
        Upload *file_bytes* to Cloudinary.

        Parameters
        ----------
        file_bytes : raw bytes of the file
        filename   : original filename (will be sanitised; used as public_id stem)
        mime_type  : detected MIME type of the file
        folder     : ``"photos"`` or ``"documents"``

        Returns
        -------
        dict with keys: file_id, view_url, download_url, filename

        Raises
        ------
        ValueError  – on security / validation failures
        Exception   – on Cloudinary API errors (let caller convert to HTTP 502)
        """
        self._ensure_configured()
        self._validate_file(file_bytes, mime_type, folder)

        safe_name     = sanitize_filename(filename)
        # Strip extension from public_id; Cloudinary manages extensions itself.
        public_id_stem = safe_name.rsplit(".", 1)[0] if "." in safe_name else safe_name
        cld_folder     = PHOTOS_FOLDER if folder == "photos" else DOCUMENTS_FOLDER
        public_id      = f"{cld_folder}/{public_id_stem}"
        resource_type  = _resource_type_for(mime_type)

        upload_result = cloudinary.uploader.upload(
            file_bytes,
            public_id=public_id,
            resource_type=resource_type,
            overwrite=True,               # replace if same public_id already exists
            invalidate=True,              # purge CDN cache on overwrite
            use_filename=False,           # we control the public_id ourselves
            unique_filename=False,
        )

        secure_url  = upload_result["secure_url"]
        stored_id   = upload_result["public_id"]  # may have Cloudinary suffix
        view_url    = secure_url
        # Force-download URL: insert fl_attachment transformation
        download_url = self._build_download_url(secure_url)

        return {
            "file_id":      stored_id,
            "filename":     safe_name,
            "view_url":     view_url,
            "download_url": download_url,
        }

    def delete_file(self, public_id: str) -> bool:
        """
        Permanently delete a file from Cloudinary by its public_id.

        Tries both resource types (image / raw) so callers don't need to track
        which type was used at upload time.

        Returns True on success, False if the asset was not found.
        """
        self._ensure_configured()

        for resource_type in ("image", "raw"):
            try:
                result = cloudinary.uploader.destroy(
                    public_id,
                    resource_type=resource_type,
                    invalidate=True,
                )
                if result.get("result") == "ok":
                    return True
                if result.get("result") == "not found":
                    continue   # try the other resource_type
            except cloudinary.exceptions.Error as exc:
                logger.warning(
                    "Cloudinary delete error for %s (resource_type=%s): %s",
                    public_id, resource_type, exc,
                )

        logger.warning("Cloudinary asset not found for deletion: %s", public_id)
        return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_download_url(secure_url: str) -> str:
        """
        Insert the ``fl_attachment`` transformation flag into a Cloudinary URL
        so the browser downloads the file instead of rendering it inline.

        Example
        -------
        Input : https://res.cloudinary.com/<cloud>/image/upload/v123/path/file.pdf
        Output: https://res.cloudinary.com/<cloud>/image/upload/fl_attachment/v123/path/file.pdf
        """
        return secure_url.replace("/upload/", "/upload/fl_attachment/", 1)

    @staticmethod
    def _validate_file(file_bytes: bytes, mime_type: str, folder: str) -> None:
        """Raise ValueError on any security violation."""
        if len(file_bytes) > MAX_FILE_SIZE_BYTES:
            raise ValueError(
                f"File size {len(file_bytes) / 1_048_576:.1f} MB exceeds the 10 MB limit."
            )

        if mime_type in BLOCKED_MIMES:
            raise ValueError(f"File type '{mime_type}' is not allowed.")

        if folder == "photos" and mime_type not in ALLOWED_IMAGE_MIMES:
            raise ValueError(
                f"'{mime_type}' is not an allowed image type. "
                "Accepted: jpg, jpeg, png, webp."
            )
        if folder == "documents" and mime_type not in ALLOWED_DOCUMENT_MIMES:
            raise ValueError(
                f"'{mime_type}' is not an allowed document type."
            )


# ---------------------------------------------------------------------------
# Module-level singleton  (mirrors get_drive_service())
# ---------------------------------------------------------------------------

_cloudinary_service: Optional[CloudinaryService] = None


def get_cloudinary_service() -> CloudinaryService:
    """Return the module-level CloudinaryService singleton."""
    global _cloudinary_service
    if _cloudinary_service is None:
        _cloudinary_service = CloudinaryService()
    return _cloudinary_service
