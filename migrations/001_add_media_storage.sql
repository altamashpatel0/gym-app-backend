-- =============================================================================
-- Migration: 001_add_media_storage.sql
-- Description: Add member_documents table and ensure photo_url exists on members.
-- Safe to run on existing databases — uses IF NOT EXISTS / IF EXISTS guards.
-- Run this BEFORE deploying the new code.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Ensure photo_url column exists on members (it already does per the model,
--    but this guard makes the migration idempotent).
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'members'
          AND column_name = 'photo_url'
    ) THEN
        ALTER TABLE members ADD COLUMN photo_url TEXT;
        RAISE NOTICE 'Added photo_url column to members.';
    ELSE
        RAISE NOTICE 'photo_url already exists on members — skipping.';
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------
-- 2. Create member_documents table (idempotent).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS member_documents (
    id              SERIAL          PRIMARY KEY,
    member_id       INTEGER         NOT NULL
                                    REFERENCES members(id)
                                    ON DELETE CASCADE,
    document_name   VARCHAR(200)    NOT NULL,
    document_type   VARCHAR(50)     NOT NULL,   -- aadhaar|pan|agreement|medical|other
    file_url        TEXT            NOT NULL,   -- public view URL
    download_url    TEXT,                       -- force-download URL
    drive_file_id   VARCHAR(200),              -- Google Drive file ID (for deletion)
    mime_type       VARCHAR(100),
    uploaded_at     TIMESTAMP WITH TIME ZONE
                    NOT NULL
                    DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- 3. Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_member_documents_member_id
    ON member_documents (member_id);

CREATE INDEX IF NOT EXISTS ix_member_documents_id
    ON member_documents (id);

-- ---------------------------------------------------------------------------
-- 4. Verify
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    col_count INT;
BEGIN
    SELECT COUNT(*) INTO col_count
    FROM information_schema.columns
    WHERE table_name = 'member_documents';

    RAISE NOTICE 'member_documents table has % columns.', col_count;
END;
$$;

COMMIT;

-- =============================================================================
-- Rollback script (run only if you need to revert):
-- =============================================================================
-- BEGIN;
-- DROP TABLE IF EXISTS member_documents;
-- -- DO NOT drop photo_url from members — it was part of the original schema.
-- COMMIT;
