-- =============================================================================
-- Migration: 006_remove_cloudinary_document_storage.sql
-- Description: Part of the full Cloudinary -> Backblaze B2 removal.
--
--   1. Add `member_documents.storage_key` (B2 object key for NEW documents).
--   2. Relax `member_documents.file_url` from NOT NULL to nullable, since
--      new B2-backed rows no longer store a URL at all — the API layer
--      generates a fresh presigned URL from `storage_key` on every read.
--      Existing rows keep their current `file_url` value untouched; this
--      only changes what's ALLOWED going forward.
--
-- Photo storage (`members.photo_storage_key`) was already added by
-- migrations/005_add_photo_storage_key.sql — nothing further needed there.
--
-- Safe to run on existing databases — uses IF NOT EXISTS / guards, so it is
-- idempotent and can be re-run without side effects (same style as
-- 001-005_*.sql). Run this BEFORE deploying the new backend code.
--
-- IMPORTANT: this migration does NOT touch, migrate, or delete any existing
-- Cloudinary data. Existing `file_url` / `download_url` / `drive_file_id`
-- values are left exactly as they are. Use
-- scripts/migrate_cloudinary_to_b2.py (run separately, offline, with
-- --dry-run first) to actually move file bytes from Cloudinary to B2 and
-- populate `storage_key` / `photo_storage_key` for existing records.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Add `storage_key` column (idempotent, nullable).
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'member_documents'
          AND column_name = 'storage_key'
    ) THEN
        ALTER TABLE member_documents ADD COLUMN storage_key TEXT NULL;
        RAISE NOTICE 'Added storage_key column to member_documents (default: NULL).';
    ELSE
        RAISE NOTICE 'storage_key column already exists on member_documents — skipping.';
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------
-- 2. Relax file_url NOT NULL -> nullable. Only alters the constraint; does
--    NOT touch any existing row's value. Guarded so it's safe to re-run.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'member_documents'
          AND column_name = 'file_url'
          AND is_nullable = 'NO'
    ) THEN
        ALTER TABLE member_documents ALTER COLUMN file_url DROP NOT NULL;
        RAISE NOTICE 'Relaxed member_documents.file_url to nullable.';
    ELSE
        RAISE NOTICE 'member_documents.file_url is already nullable — skipping.';
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------
-- 3. Index — supports the (uncommon but real) lookup of a document by its
--    B2 object key, and the data-migration script's "WHERE storage_key IS
--    NULL" resumability query.
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_member_documents_storage_key
    ON member_documents (storage_key)
    WHERE storage_key IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 4. Verify
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    total_docs      INT;
    b2_docs         INT;
    cloudinary_docs INT;
BEGIN
    SELECT COUNT(*) INTO total_docs FROM member_documents;
    SELECT COUNT(*) INTO b2_docs FROM member_documents WHERE storage_key IS NOT NULL;
    SELECT COUNT(*) INTO cloudinary_docs FROM member_documents WHERE storage_key IS NULL;

    RAISE NOTICE 'member_documents.storage_key -> total: %, on B2: %, still legacy/unmigrated: %',
        total_docs, b2_docs, cloudinary_docs;
END;
$$;

COMMIT;

-- =============================================================================
-- Rollback script (run only if you need to revert):
-- =============================================================================
-- BEGIN;
-- DROP INDEX IF EXISTS ix_member_documents_storage_key;
-- ALTER TABLE member_documents DROP COLUMN IF EXISTS storage_key;
-- -- NOTE: re-adding NOT NULL to file_url is NOT safely reversible here if
-- -- any row's file_url is now NULL (i.e. any document was uploaded via B2
-- -- after this migration ran). Backfill or handle those rows first if you
-- -- need to roll back the nullable change.
-- COMMIT;
