from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from config import settings

engine = create_engine(settings.DATABASE_URL)


# ── ROOT-CAUSE FIX: force every DB connection's session timezone to IST ──────
# psycopg2 always adapts a tz-aware Python datetime (e.g. our
# `datetime.now(IST)` values) by casting it to `::timestamptz` in the SQL it
# sends. PostgreSQL then normalizes that value using the *session* TimeZone
# setting before storing/returning it - regardless of whether the target
# column is TIMESTAMP or TIMESTAMPTZ. Postgres' default session timezone is
# UTC (confirmed via `SHOW timezone;` -> "Etc/UTC"), so a value written as
# 4:00 PM IST was silently normalized to ~10:30 AM before being stored/read
# back - exactly the ~5h30m gap observed in production (4:00 PM -> 10:34 AM).
#
# Setting the session timezone to Asia/Kolkata on every new connection makes
# Postgres interpret/display all timestamps in IST wall-clock time, matching
# what attendance_service.py and routers/attendance.py already compute with
# `datetime.now(IST)`. This requires NO schema/column changes - it only
# affects how the existing columns are read/written per connection.
@event.listens_for(engine, "connect")
def _set_session_timezone(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("SET TIME ZONE 'Asia/Kolkata';")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
