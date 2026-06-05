"""
main.py  (updated — added media router registration only)
----------------------------------------------------------
All existing routers are preserved exactly as before.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import Base, engine
from routers.auth import router as auth_router
from routers.members import router as members_router
from routers.plans import router as plans_router
from routers.payments import router as payments_router
from routers.attendance import router as attendance_router
from routers.staff import router as staff_router
from routers.dashboard import router as dashboard_router
from routers.reports import router as reports_router
from routers.notifications import router as notifications_router
# ← NEW
from routers.media import router as media_router

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="GymOps API",
    version="1.1.0",
    description=(
        "Gym Management System API — includes member management, "
        "payments, attendance, reports, notifications, and media storage."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Existing routers (unchanged)
app.include_router(auth_router)
app.include_router(members_router)
app.include_router(plans_router)
app.include_router(payments_router)
app.include_router(attendance_router)
app.include_router(staff_router)
app.include_router(dashboard_router)
app.include_router(reports_router)
app.include_router(notifications_router)

# NEW: media / storage router
app.include_router(media_router)


@app.get("/")
def root():
    return {"status": "GymOps API running"}
