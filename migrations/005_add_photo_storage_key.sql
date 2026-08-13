-- =============================================================================
-- Migration: 005_add_photo_storage_key.sql
-- Description: Add `photo_storage_key` to members, for the Cloudinary -> B2
-- member PROFILE PHOTO migration. This is purely additive: it does NOT
-- touch, rename, or backfill the existing `photo_url` column, and it does
-- NOT migrate any existing Cloudinary photos.
--
-- Safe to run on existing databases — uses IF NOT EXISTS / guards, so it is
-- idempotent and can be re-run without side effects (same style as
-- 001/002/003/004_*.sql). Run this BEFORE deploying the new backend code.
--
-- NOTE: consistent with 002/003/004 — this project has no Alembic
-- env/versions directory and does not depend on `alembic` (see
-- requirements.txt). `Base.metadata.create_all()` in main.py only creates
-- missing TABLES, not missing COLUMNS on existing tables, so this raw-SQL
-- script is the actual migration mechanism for existing databases.
--
-- BACKWARD COMPATIBILITY:
--   photo_storage_key IS NULL  -> member's photo is still on Cloudinary;
--                                  the existing `photo_url` value keeps
--                                  being returned untouched.
--   photo_storage_key IS NOT NULL -> member has a NEW B2 photo; the app
--                                  layer generates a fresh presigned URL
--                                  from this key on every read and never
--                                  stores that presigned URL in Postgres.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Add `photo_storage_key` column (idempotent, nullable — every existing
--    row gets NULL, meaning "still on Cloudinary", with zero migration of
--    existing data required).
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'members'
          AND column_name = 'photo_storage_key'
    ) THEN
        ALTER TABLE members ADD COLUMN photo_storage_key TEXT NULL;
        RAISE NOTICE 'Added photo_storage_key column to members (default: NULL).';
    ELSE
        RAISE NOTICE 'photo_storage_key column already exists on members — skipping.';
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------
-- 2. Index — supports the (uncommon but real) lookup of a member by their
--    B2 object key, and keeps the column consistent with the indexing
--    style already used elsewhere in this project (ix_members_shift,
--    ix_members_attendance_paused).
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_members_photo_storage_key
    ON members (photo_storage_key)
    WHERE photo_storage_key IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 3. Verify — confirm existing photo_url data is completely untouched, and
--    report how many members are already on the new B2 path (should be 0
--    right after this migration runs, since no upload has happened yet).
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    total_members     INT;
    b2_members        INT;
    cloudinary_members INT;
BEGIN
    SELECT COUNT(*) INTO total_members FROM members;
    SELECT COUNT(*) INTO b2_members FROM members WHERE photo_storage_key IS NOT NULL;
    SELECT COUNT(*) INTO cloudinary_members FROM members WHERE photo_storage_key IS NULL;

    RAISE NOTICE 'members.photo_storage_key -> total: %, on B2: %, still on Cloudinary/none: % (photo_url untouched)',
        total_members, b2_members, cloudinary_members;
END;
$$;

COMMIT;

-- =============================================================================
-- Rollback script (run only if you need to revert):
-- =============================================================================
-- BEGIN;
-- DROP INDEX IF EXISTS ix_members_photo_storage_key;
-- ALTER TABLE members DROP COLUMN IF EXISTS photo_storage_key;
-- -- DO NOT drop photo_url — it is the original Cloudinary column and must
-- -- remain intact regardless of whether this migration is rolled back.
-- COMMIT;
