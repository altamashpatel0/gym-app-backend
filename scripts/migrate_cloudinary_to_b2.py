"""
scripts/migrate_cloudinary_to_b2.py
------------------------------------
One-time (but safely re-runnable) data migration: copies every existing
member PHOTO and DOCUMENT file that is still on Cloudinary over to
Backblaze B2, and populates `photo_storage_key` / `storage_key`.

Run standalone — NOT wired up as an HTTP endpoint, so it's never reachable
from the frontend or exposed to unauthenticated callers:

    python -m scripts.migrate_cloudinary_to_b2 --dry-run
    python -m scripts.migrate_cloudinary_to_b2

WHAT THIS DOES NOT DO:
  - It never deletes anything from Cloudinary. Old Cloudinary files are
    left completely untouched — this script only reads them (over plain
    HTTPS) and writes new copies to B2.
  - It never uses the Cloudinary SDK/credentials. Cloudinary's default
    delivery is a public HTTPS URL (`secure_url`), so migrating existing
    assets only requires fetching that URL — the same way a browser would.
    If your Cloudinary account has restricted/private delivery, this
    script cannot fetch those files and those rows will show up as
    "failed" in the report; you'd need to temporarily reintroduce
    Cloudinary API credentials to pull those specific assets.

RESUMABILITY / IDEMPOTENCY:
  Every query below filters on `photo_storage_key IS NULL` /
  `storage_key IS NULL`. Once a record is successfully migrated, it's
  never touched again on subsequent runs — so stopping this script at
  member 80 and re-running it is always safe: already-migrated rows are
  skipped, and only the remaining/failed ones are retried. No separate
  tracking table is needed.

VERIFICATION BEFORE DB WRITE:
  Each file is uploaded to B2, then verified with a HEAD request
  (`B2StorageService.verify_object_exists`) BEFORE the Postgres row is
  updated. If verification fails, the DB is left untouched and the
  record will be retried on the next run.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

import magic

from database import SessionLocal
from models import Member, MemberDocument
from services.b2_storage import (
    ALLOWED_DOCUMENT_MIMES,
    ALLOWED_IMAGE_MIMES,
    MAX_FILE_SIZE_BYTES,
    build_member_document_key,
    build_member_photo_key,
    get_b2_storage_service,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("migrate_cloudinary_to_b2")

DOWNLOAD_TIMEOUT_SECONDS = 30


@dataclass
class MigrationReport:
    total: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    failed_ids: list = field(default_factory=list)

    def summary(self, label: str) -> str:
        return (
            f"\n=== {label} migration report ===\n"
            f"  total examined : {self.total}\n"
            f"  successful     : {self.successful}\n"
            f"  failed         : {self.failed}\n"
            f"  skipped        : {self.skipped}\n"
            f"  failed ids     : {self.failed_ids}\n"
        )


def _download(url: str, max_bytes: int = MAX_FILE_SIZE_BYTES) -> bytes:
    """
    Fetch an existing Cloudinary asset over plain HTTPS (no SDK, no
    credentials — this relies on Cloudinary's default public delivery).
    Raises on any failure or if the file exceeds the size cap.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "gymops-migration/1.0"})
    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_SECONDS) as resp:
        data = resp.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError(f"File at {url} exceeds {max_bytes // 1_048_576} MB limit.")
        return data


def migrate_photos(dry_run: bool) -> MigrationReport:
    report = MigrationReport()
    db = SessionLocal()
    storage = get_b2_storage_service()

    try:
        members = (
            db.query(Member)
            .filter(Member.photo_storage_key.is_(None))
            .filter(Member.photo_url.isnot(None))
            .all()
        )
        report.total = len(members)
        logger.info("Photos: %d member(s) still on Cloudinary.", report.total)

        for member in members:
            try:
                file_bytes = _download(member.photo_url)
                mime_type = magic.from_buffer(file_bytes, mime=True)

                if mime_type not in ALLOWED_IMAGE_MIMES:
                    logger.warning(
                        "Member %s: downloaded photo has unsupported MIME '%s' — skipping.",
                        member.id, mime_type,
                    )
                    report.skipped += 1
                    continue

                key = build_member_photo_key(member_id=member.id, mime_type=mime_type)

                if dry_run:
                    logger.info("[DRY RUN] Would migrate member %s photo -> %s", member.id, key)
                    report.successful += 1
                    continue

                storage.upload_file(
                    file_bytes=file_bytes,
                    filename=f"member_{member.id}_photo",
                    mime_type=mime_type,
                    folder="photos",
                    object_key=key,
                )

                if not storage.verify_object_exists(key):
                    raise RuntimeError("B2 verification failed after upload.")

                member.photo_storage_key = key
                # Original Cloudinary photo_url is intentionally LEFT AS-IS
                # (not cleared, not deleted) until you've verified the
                # migration end-to-end and are ready to clean up Cloudinary
                # separately. The API layer already prefers
                # photo_storage_key over photo_url once it's set.
                db.commit()

                logger.info("Member %s: migrated photo -> %s", member.id, key)
                report.successful += 1

            except Exception as exc:
                db.rollback()
                logger.error("Member %s: photo migration FAILED: %s", member.id, exc)
                report.failed += 1
                report.failed_ids.append(member.id)

    finally:
        db.close()

    return report


def migrate_documents(dry_run: bool) -> MigrationReport:
    report = MigrationReport()
    db = SessionLocal()
    storage = get_b2_storage_service()

    try:
        docs = (
            db.query(MemberDocument)
            .filter(MemberDocument.storage_key.is_(None))
            .filter(MemberDocument.file_url.isnot(None))
            .all()
        )
        report.total = len(docs)
        logger.info("Documents: %d document(s) still on Cloudinary.", report.total)

        for doc in docs:
            try:
                file_bytes = _download(doc.file_url)
                mime_type = doc.mime_type or magic.from_buffer(file_bytes, mime=True)

                if mime_type not in ALLOWED_DOCUMENT_MIMES:
                    logger.warning(
                        "Document %s: unsupported MIME '%s' — skipping.", doc.id, mime_type
                    )
                    report.skipped += 1
                    continue

                key = build_member_document_key(
                    member_id=doc.member_id,
                    filename=doc.document_name or f"document_{doc.id}",
                )

                if dry_run:
                    logger.info("[DRY RUN] Would migrate document %s -> %s", doc.id, key)
                    report.successful += 1
                    continue

                storage.upload_file(
                    file_bytes=file_bytes,
                    filename=doc.document_name or f"document_{doc.id}",
                    mime_type=mime_type,
                    folder="documents",
                    object_key=key,
                )

                if not storage.verify_object_exists(key):
                    raise RuntimeError("B2 verification failed after upload.")

                doc.storage_key = key
                # Legacy file_url / download_url / drive_file_id are
                # intentionally left untouched — same rationale as photos.
                db.commit()

                logger.info("Document %s: migrated -> %s", doc.id, key)
                report.successful += 1

            except Exception as exc:
                db.rollback()
                logger.error("Document %s: migration FAILED: %s", doc.id, exc)
                report.failed += 1
                report.failed_ids.append(doc.id)

    finally:
        db.close()

    return report


def _remaining_cloudinary_counts() -> tuple[int, int]:
    db = SessionLocal()
    try:
        remaining_photos = (
            db.query(Member)
            .filter(Member.photo_storage_key.is_(None))
            .filter(Member.photo_url.isnot(None))
            .count()
        )
        remaining_docs = (
            db.query(MemberDocument)
            .filter(MemberDocument.storage_key.is_(None))
            .filter(MemberDocument.file_url.isnot(None))
            .count()
        )
        return remaining_photos, remaining_docs
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Migrate existing Cloudinary photos/documents to Backblaze B2.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would happen without uploading or writing to the DB.")
    parser.add_argument("--photos-only", action="store_true", help="Only migrate member photos.")
    parser.add_argument("--documents-only", action="store_true", help="Only migrate member documents.")
    args = parser.parse_args()

    start = time.time()
    logger.info("Starting Cloudinary -> B2 migration (dry_run=%s)", args.dry_run)

    photo_report = None
    doc_report = None

    if not args.documents_only:
        photo_report = migrate_photos(dry_run=args.dry_run)
        print(photo_report.summary("Photo"))

    if not args.photos_only:
        doc_report = migrate_documents(dry_run=args.dry_run)
        print(doc_report.summary("Document"))

    if not args.dry_run:
        remaining_photos, remaining_docs = _remaining_cloudinary_counts()
        print(
            f"\n=== Remaining Cloudinary records after this run ===\n"
            f"  photos still on Cloudinary    : {remaining_photos}\n"
            f"  documents still on Cloudinary : {remaining_docs}\n"
            f"  (these are safe to retry — just run this script again)\n"
        )

    elapsed = time.time() - start
    logger.info("Migration run finished in %.1fs", elapsed)

    any_failures = (photo_report and photo_report.failed) or (doc_report and doc_report.failed)
    sys.exit(1 if any_failures else 0)


if __name__ == "__main__":
    main()
