-- =============================================================================
-- Migration: 004_add_attendance_pause.sql
-- Description: Add manual "Attendance Pause" support to members. This is a
-- SEPARATE feature from `members.status` (active/expired/paused) — that
-- column and its meaning are completely untouched by this migration.
-- Safe to run on existing databases — uses IF NOT EXISTS / guards, so it is
-- idempotent and can be re-run without side effects.
-- Run this BEFORE deploying the new backend code (same rule as 001/002/003).
--
-- NOTE: consistent with 002/003 — this project has no Alembic env/versions
-- directory and does not depend on `alembic` (see requirements.txt).
-- `Base.metadata.create_all()` in main.py only creates missing TABLES, not
-- missing COLUMNS on existing tables, so this raw-SQL script is the actual
-- migration mechanism for existing databases.
--
-- IMPORTANT — no existing columns are touched: this migration only ADDS
-- three new, additive, nullable-or-defaulted columns to `members`.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Add `attendance_paused` column (idempotent). DEFAULT FALSE backfills
--    every existing row automatically — nobody's attendance is paused by
--    running this migration.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'members' AND column_name = 'attendance_paused'
    ) THEN
        ALTER TABLE members
            ADD COLUMN attendance_paused BOOLEAN NOT NULL DEFAULT FALSE;
        RAISE NOTICE 'Added attendance_paused column to members (default: FALSE).';
    ELSE
        RAISE NOTICE 'attendance_paused column already exists on members — skipping.';
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------
-- 2. Add `attendance_pause_reason` column (idempotent, nullable).
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'members' AND column_name = 'attendance_pause_reason'
    ) THEN
        ALTER TABLE members
            ADD COLUMN attendance_pause_reason TEXT NULL;
        RAISE NOTICE 'Added attendance_pause_reason column to members.';
    ELSE
        RAISE NOTICE 'attendance_pause_reason column already exists on members — skipping.';
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------
-- 3. Add `attendance_paused_at` column (idempotent, nullable).
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'members' AND column_name = 'attendance_paused_at'
    ) THEN
        ALTER TABLE members
            ADD COLUMN attendance_paused_at TIMESTAMP NULL;
        RAISE NOTICE 'Added attendance_paused_at column to members.';
    ELSE
        RAISE NOTICE 'attendance_paused_at column already exists on members — skipping.';
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------
-- 4. Defensive backfill — in case a prior partial migration left NULLs on
--    the boolean column (should not happen given DEFAULT FALSE above, but
--    mirrors the defensive style of 002_add_shift_to_members.sql).
-- ---------------------------------------------------------------------------
UPDATE members SET attendance_paused = FALSE WHERE attendance_paused IS NULL;

-- ---------------------------------------------------------------------------
-- 5. Index — pause/resume lookups and the attendance check-in guard filter
--    on this column.
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_members_attendance_paused ON members (attendance_paused);

-- ---------------------------------------------------------------------------
-- 6. Verify
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    paused_count INT;
    active_count INT;
    null_count   INT;
BEGIN
    SELECT COUNT(*) INTO paused_count FROM members WHERE attendance_paused = TRUE;
    SELECT COUNT(*) INTO active_count FROM members WHERE attendance_paused = FALSE;
    SELECT COUNT(*) INTO null_count   FROM members WHERE attendance_paused IS NULL;

    RAISE NOTICE 'members.attendance_paused → paused: %, active: %, NULL: % (should be 0)',
        paused_count, active_count, null_count;
END;
$$;

COMMIT;

-- =============================================================================
-- Rollback script (run only if you need to revert):
-- =============================================================================
-- BEGIN;
-- DROP INDEX IF EXISTS ix_members_attendance_paused;
-- ALTER TABLE members DROP COLUMN IF EXISTS attendance_paused;
-- ALTER TABLE members DROP COLUMN IF EXISTS attendance_pause_reason;
-- ALTER TABLE members DROP COLUMN IF EXISTS attendance_paused_at;
-- COMMIT;
