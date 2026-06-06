"""
services/google_drive.py
------------------------
Google Drive storage backend for GymOps.

Reads credentials from the GOOGLE_DRIVE_CREDENTIALS_JSON environment variable
(a JSON string containing a service-account key).  No hardcoded paths.

Folder layout on Drive (rooted at the shared folder in GOOGLE_DRIVE_ROOT_FOLDER_ID):
    <shared-root>/
        Members/
            Photos/
            Documents/

ROOT CAUSE FIX (storageQuotaExceeded / 403)
--------------------------------------------
The Google Drive v3 API distinguishes between two storage contexts:

  1. My Drive  — belongs to a regular Google account; has quota.
  2. Shared Drive (a.k.a. Team Drive) — quota lives on the *domain/org*,
     not on any individual user or service account.

When a service account calls files().create() WITHOUT the
``supportsAllDrives=True`` parameter, the Drive API silently treats the
request as targeting *My Drive* — the service-account's own storage space.
Service accounts have **zero** quota on My Drive, so every write immediately
raises:

    HttpError 403: Service Accounts do not have storage quota
                   (storageQuotaExceeded)

This happens even when ``parents`` correctly points at a folder inside a
Shared Drive, because the API ignores that parent and writes to the
service-account root first, then tries (and fails) to count quota.

The fix is to add ``supportsAllDrives=True`` to EVERY Drive API call that
reads or writes file/folder resources:

  • files().list()
  • files().create()
  • files().delete()
  • permissions().create()

Additionally, files().list() needs ``includeItemsFromAllDrives=True`` so that
folder-existence queries actually see items inside a Shared Drive; without it
the query always returns an empty list, causing the code to re-create the
same folder on every cold start (each new folder lands in the wrong place and
eventually triggers the quota error on its first upload).
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import unicodedata
from typing import Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCOPES = ["https://www.googleapis.com/auth/drive"]

ROOT_FOLDER_NAME = "GymManagementTool"   # kept for reference only
MEMBERS_FOLDER_NAME = "Members"
PHOTOS_FOLDER_NAME = "Photos"
DOCUMENTS_FOLDER_NAME = "Documents"

# ---------------------------------------------------------------------------
# Security: allowed MIME types
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


# ---------------------------------------------------------------------------
# Filename sanitisation
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
    ext = ext[:10]
    filename = f"{name}.{ext}" if ext else name[:100]
    return filename or "unnamed"


# ---------------------------------------------------------------------------
# GoogleDriveService
# ---------------------------------------------------------------------------

class GoogleDriveService:
    """Thin wrapper around the Google Drive v3 API."""

    def __init__(self) -> None:
        self._service = None
        self._folder_cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _get_service(self):
        if self._service is not None:
            return self._service

        creds_json = os.environ.get("GOOGLE_DRIVE_CREDENTIALS_JSON")
        if not creds_json:
            raise RuntimeError(
                "GOOGLE_DRIVE_CREDENTIALS_JSON environment variable is not set."
            )

        try:
            creds_info = json.loads(creds_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "GOOGLE_DRIVE_CREDENTIALS_JSON is not valid JSON."
            ) from exc

        credentials = service_account.Credentials.from_service_account_info(
            creds_info, scopes=SCOPES
        )
        self._service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        return self._service

    # ------------------------------------------------------------------
    # Root folder
    # ------------------------------------------------------------------

    @staticmethod
    def _get_root_folder_id() -> str:
        """
        Return the shared Drive folder ID from the environment.

        This folder must already exist and have been shared with the service
        account.  We never create a folder at the service-account root level
        because service accounts have no storage quota of their own.
        """
        folder_id = os.environ.get("GOOGLE_DRIVE_ROOT_FOLDER_ID", "").strip()
        if not folder_id:
            raise RuntimeError(
                "GOOGLE_DRIVE_ROOT_FOLDER_ID environment variable is not set."
            )
        return folder_id

    # ------------------------------------------------------------------
    # Folder helpers
    # ------------------------------------------------------------------

    def _get_or_create_folder(self, name: str, parent_id: Optional[str] = None) -> str:
        """Return the Drive folder ID for *name*, creating it if absent.

        *parent_id* is required — passing None would create a folder in the
        service account's root drive, which has no storage quota.

        FIX: Every files().list() and files().create() call now carries:
          • supportsAllDrives=True        — allows write access to Shared Drives
          • includeItemsFromAllDrives=True — allows the list query to see items
                                            that live inside a Shared Drive
        Without these flags the Drive API treats every request as targeting
        My Drive (the service account's own quota-less storage).
        """
        if parent_id is None:
            raise ValueError(
                "_get_or_create_folder() requires a parent_id. "
                "Use _get_root_folder_id() to obtain the shared root."
            )

        cache_key = f"{parent_id}:{name}"
        if cache_key in self._folder_cache:
            return self._folder_cache[cache_key]

        service = self._get_service()

        query_parts = [
            f"name = '{name}'",
            "mimeType = 'application/vnd.google-apps.folder'",
            "trashed = false",
            f"'{parent_id}' in parents",
        ]

        # FIX 1: added supportsAllDrives + includeItemsFromAllDrives so the
        # query actually searches inside the Shared Drive.
        results = (
            service.files()
            .list(
                q=" and ".join(query_parts),
                fields="files(id, name)",
                pageSize=1,
                supportsAllDrives=True,           # FIX 1a
                includeItemsFromAllDrives=True,   # FIX 1b
            )
            .execute()
        )
        files = results.get("files", [])

        if files:
            folder_id = files[0]["id"]
        else:
            metadata: dict = {
                "name": name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id],
            }
            # FIX 2: added supportsAllDrives so the folder is created inside
            # the Shared Drive rather than the service account's My Drive.
            folder = (
                service.files()
                .create(body=metadata, fields="id", supportsAllDrives=True)  # FIX 2
                .execute()
            )
            folder_id = folder["id"]

        self._folder_cache[cache_key] = folder_id
        return folder_id

    def _get_photos_folder_id(self) -> str:
        root_id = self._get_root_folder_id()
        members_id = self._get_or_create_folder(MEMBERS_FOLDER_NAME, root_id)
        return self._get_or_create_folder(PHOTOS_FOLDER_NAME, members_id)

    def _get_documents_folder_id(self) -> str:
        root_id = self._get_root_folder_id()
        members_id = self._get_or_create_folder(MEMBERS_FOLDER_NAME, root_id)
        return self._get_or_create_folder(DOCUMENTS_FOLDER_NAME, members_id)

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
        Upload *file_bytes* to Google Drive.

        Parameters
        ----------
        file_bytes : raw bytes of the file
        filename   : original filename (will be sanitised)
        mime_type  : detected MIME type of the file
        folder     : ``"photos"`` or ``"documents"``

        Returns
        -------
        dict with keys: file_id, view_url, download_url, filename
        """
        self._validate_file(file_bytes, mime_type, folder)

        safe_name = sanitize_filename(filename)
        folder_id = (
            self._get_photos_folder_id()
            if folder == "photos"
            else self._get_documents_folder_id()
        )

        service = self._get_service()

        file_metadata = {"name": safe_name, "parents": [folder_id]}
        media = MediaIoBaseUpload(
            io.BytesIO(file_bytes), mimetype=mime_type, resumable=False
        )

        # FIX 3: added supportsAllDrives so the file upload targets the Shared
        # Drive rather than the service account's quota-less My Drive.
        uploaded = (
            service.files()
            .create(
                body=file_metadata,
                media_body=media,
                fields="id, name",
                supportsAllDrives=True,   # FIX 3
            )
            .execute()
        )
        file_id = uploaded["id"]

        self._make_public(file_id)

        view_url, download_url = self._build_urls(file_id, mime_type)

        return {
            "file_id": file_id,
            "filename": safe_name,
            "view_url": view_url,
            "download_url": download_url,
        }

    def delete_file(self, file_id: str) -> bool:
        """
        Permanently delete a file from Google Drive.

        Returns True on success, False if not found.
        """
        try:
            # FIX 4: added supportsAllDrives so deletion works on Shared Drive
            # files (without it the call raises 404 even for existing files).
            self._get_service().files().delete(
                fileId=file_id,
                supportsAllDrives=True,   # FIX 4
            ).execute()
            return True
        except HttpError as exc:
            if exc.resp.status == 404:
                logger.warning("Drive file %s not found for deletion.", file_id)
                return False
            raise

    def get_public_url(self, file_id: str) -> str:
        """Return the browser-renderable URL for an existing Drive file."""
        return f"https://drive.google.com/uc?export=view&id={file_id}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_public(self, file_id: str) -> None:
        """Grant 'anyone with the link can view' permission."""
        # FIX 5: added supportsAllDrives so the permissions call succeeds for
        # files that live inside a Shared Drive.
        self._get_service().permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
            supportsAllDrives=True,   # FIX 5
        ).execute()

    @staticmethod
    def _build_urls(file_id: str, mime_type: str) -> tuple[str, str]:
        """
        Return (view_url, download_url).

        Images use ``export=view`` so they render directly in the browser.
        Documents use ``export=download``.
        """
        base = f"https://drive.google.com/uc?id={file_id}"
        view_url = f"{base}&export=view"
        download_url = f"{base}&export=download"
        return view_url, download_url

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

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
                f"Accepted: jpg, jpeg, png, webp."
            )
        if folder == "documents" and mime_type not in ALLOWED_DOCUMENT_MIMES:
            raise ValueError(
                f"'{mime_type}' is not an allowed document type."
            )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_drive_service: Optional[GoogleDriveService] = None


def get_drive_service() -> GoogleDriveService:
    """Return the module-level GoogleDriveService singleton."""
    global _drive_service
    if _drive_service is None:
        _drive_service = GoogleDriveService()
    return _drive_service
