-- =============================================================================
-- Migration: 002_add_shift_to_members.sql
-- Description: Add `shift` (Day/Night) column to members.
-- Safe to run on existing databases — uses IF NOT EXISTS / guards, so it is
-- idempotent and can be re-run without side effects.
-- Run this BEFORE deploying the new backend code (same rule as 001_*.sql).
--
-- NOTE: `migrations/add_shift_to_members.py` (Alembic-style) predates this
-- file and is NOT wired up — this project has no Alembic env/versions
-- directory and does not depend on `alembic` (see requirements.txt). Tables
-- are created via SQLAlchemy's `Base.metadata.create_all()` in main.py,
-- which only creates missing TABLES, not missing COLUMNS on existing
-- tables. This raw-SQL script is therefore the actual migration mechanism
-- for existing databases, consistent with 001_add_media_storage.sql above.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Add the `shift` column (idempotent). DEFAULT 'Day' backfills every
--    existing row automatically — no separate UPDATE statement needed.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'members'
          AND column_name = 'shift'
    ) THEN
        ALTER TABLE members
            ADD COLUMN shift VARCHAR(10) NOT NULL DEFAULT 'Day';
        RAISE NOTICE 'Added shift column to members (default: Day).';
    ELSE
        RAISE NOTICE 'shift column already exists on members — skipping.';
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------
-- 2. Defensive backfill — in case a prior partial migration left NULLs.
-- ---------------------------------------------------------------------------
UPDATE members SET shift = 'Day' WHERE shift IS NULL;

-- ---------------------------------------------------------------------------
-- 3. Constrain to known values, without touching any existing data (all
--    existing rows are already 'Day' from the DEFAULT above).
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_members_shift_valid'
    ) THEN
        ALTER TABLE members
            ADD CONSTRAINT chk_members_shift_valid CHECK (shift IN ('Day', 'Night'));
        RAISE NOTICE 'Added chk_members_shift_valid CHECK constraint.';
    ELSE
        RAISE NOTICE 'chk_members_shift_valid already exists — skipping.';
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------
-- 4. Index — dashboard/member-list shift filtering queries on this column.
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_members_shift ON members (shift);

-- ---------------------------------------------------------------------------
-- 5. Verify
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    day_count   INT;
    night_count INT;
    null_count  INT;
BEGIN
    SELECT COUNT(*) INTO day_count   FROM members WHERE shift = 'Day';
    SELECT COUNT(*) INTO night_count FROM members WHERE shift = 'Night';
    SELECT COUNT(*) INTO null_count  FROM members WHERE shift IS NULL;

    RAISE NOTICE 'members.shift → Day: %, Night: %, NULL: % (should be 0)',
        day_count, night_count, null_count;
END;
$$;

COMMIT;

-- =============================================================================
-- Rollback script (run only if you need to revert):
-- =============================================================================
-- BEGIN;
-- ALTER TABLE members DROP CONSTRAINT IF EXISTS chk_members_shift_valid;
-- DROP INDEX IF EXISTS ix_members_shift;
-- ALTER TABLE members DROP COLUMN IF EXISTS shift;
-- COMMIT;
