-- =============================================================================
-- Migration: 003_add_manual_attendance_fields.sql
-- Description: Add manual check-in/check-out support to the existing
-- `attendance` table: status, duration_minutes, created_at, updated_at.
-- Safe to run on existing databases — uses IF NOT EXISTS / guards, so it is
-- idempotent and can be re-run without side effects.
-- Run this BEFORE deploying the new backend code (same rule as 001/002_*.sql).
--
-- NOTE: consistent with 002_add_shift_to_members.sql — this project has no
-- Alembic env/versions directory and does not depend on `alembic` (see
-- requirements.txt). `Base.metadata.create_all()` in main.py only creates
-- missing TABLES, not missing COLUMNS on existing tables, so this raw-SQL
-- script is the actual migration mechanism for existing databases.
--
-- IMPORTANT — no existing columns are touched:
--   id, member_id, check_in, check_out, marked_by, date  → UNCHANGED.
-- Only new, additive columns are introduced below.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Add `status` column (idempotent). DEFAULT 'IN' backfills every existing
--    row automatically — no separate UPDATE needed for the default itself.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'attendance' AND column_name = 'status'
    ) THEN
        ALTER TABLE attendance
            ADD COLUMN status VARCHAR(10) NOT NULL DEFAULT 'IN';
        RAISE NOTICE 'Added status column to attendance (default: IN).';
    ELSE
        RAISE NOTICE 'status column already exists on attendance — skipping.';
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------
-- 2. Add `duration_minutes` column (idempotent, nullable).
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'attendance' AND column_name = 'duration_minutes'
    ) THEN
        ALTER TABLE attendance
            ADD COLUMN duration_minutes INTEGER NULL;
        RAISE NOTICE 'Added duration_minutes column to attendance.';
    ELSE
        RAISE NOTICE 'duration_minutes column already exists on attendance — skipping.';
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------
-- 3. Add `created_at` / `updated_at` bookkeeping columns (idempotent).
--    DEFAULT now() backfills existing rows with the migration run time,
--    since the true original creation time isn't otherwise recorded.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'attendance' AND column_name = 'created_at'
    ) THEN
        ALTER TABLE attendance
            ADD COLUMN created_at TIMESTAMP NOT NULL DEFAULT now();
        RAISE NOTICE 'Added created_at column to attendance.';
    ELSE
        RAISE NOTICE 'created_at column already exists on attendance — skipping.';
    END IF;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'attendance' AND column_name = 'updated_at'
    ) THEN
        ALTER TABLE attendance
            ADD COLUMN updated_at TIMESTAMP NOT NULL DEFAULT now();
        RAISE NOTICE 'Added updated_at column to attendance.';
    ELSE
        RAISE NOTICE 'updated_at column already exists on attendance — skipping.';
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------
-- 4. Backfill historical correctness: any pre-existing row that already has
--    a check_out timestamp represents a completed visit, so its status
--    should be 'OUT' (not the blanket 'IN' default from step 1), and its
--    duration_minutes should be computed from check_in/check_out so the new
--    dashboard-summary (average workout time) is meaningful for old data too.
--    Rows without a check_out remain 'IN' (still "open" for check-out).
-- ---------------------------------------------------------------------------
UPDATE attendance
SET status = 'OUT'
WHERE check_out IS NOT NULL
  AND status = 'IN';

UPDATE attendance
SET duration_minutes = GREATEST(0, ROUND(EXTRACT(EPOCH FROM (check_out - check_in)) / 60))
WHERE check_out IS NOT NULL
  AND check_in IS NOT NULL
  AND duration_minutes IS NULL;

-- ---------------------------------------------------------------------------
-- 5. Constrain `status` to known values, without touching any existing data.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_attendance_status_valid'
    ) THEN
        ALTER TABLE attendance
            ADD CONSTRAINT chk_attendance_status_valid CHECK (status IN ('IN', 'OUT'));
        RAISE NOTICE 'Added chk_attendance_status_valid CHECK constraint.';
    ELSE
        RAISE NOTICE 'chk_attendance_status_valid already exists — skipping.';
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------
-- 6. Indexes to support the new endpoints (today / member / history lookups).
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_attendance_member_date ON attendance (member_id, date);
CREATE INDEX IF NOT EXISTS ix_attendance_date_status ON attendance (date, status);

-- ---------------------------------------------------------------------------
-- 7. OPTIONAL — enforce "one attendance record per member per day" at the
--    database level. Left commented out by default: if any pre-existing
--    duplicate (member_id, date) rows already exist in production data,
--    this would fail. The app layer (services/attendance_service.py)
--    already enforces this rule for all new rows created through the new
--    check-in/check-out endpoints. Uncomment and run separately once you've
--    confirmed there are no duplicates:
--
-- DO $$
-- BEGIN
--     IF NOT EXISTS (
--         SELECT 1 FROM pg_constraint WHERE conname = 'uq_attendance_member_date'
--     ) THEN
--         ALTER TABLE attendance
--             ADD CONSTRAINT uq_attendance_member_date UNIQUE (member_id, date);
--     END IF;
-- END;
-- $$;

-- ---------------------------------------------------------------------------
-- 8. Verify
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    in_count    INT;
    out_count   INT;
    null_count  INT;
BEGIN
    SELECT COUNT(*) INTO in_count   FROM attendance WHERE status = 'IN';
    SELECT COUNT(*) INTO out_count  FROM attendance WHERE status = 'OUT';
    SELECT COUNT(*) INTO null_count FROM attendance WHERE status IS NULL;

    RAISE NOTICE 'attendance.status → IN: %, OUT: %, NULL: % (should be 0)',
        in_count, out_count, null_count;
END;
$$;

COMMIT;

-- =============================================================================
-- Rollback script (run only if you need to revert):
-- =============================================================================
-- BEGIN;
-- ALTER TABLE attendance DROP CONSTRAINT IF EXISTS chk_attendance_status_valid;
-- DROP INDEX IF EXISTS ix_attendance_member_date;
-- DROP INDEX IF EXISTS ix_attendance_date_status;
-- ALTER TABLE attendance DROP COLUMN IF EXISTS status;
-- ALTER TABLE attendance DROP COLUMN IF EXISTS duration_minutes;
-- ALTER TABLE attendance DROP COLUMN IF EXISTS created_at;
-- ALTER TABLE attendance DROP COLUMN IF EXISTS updated_at;
-- COMMIT;
