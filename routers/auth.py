from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import User
from schemas import UserCreate, UserLogin, Token, UserOut, ForgotPasswordRequest
from core.security import hash_password, verify_password, create_access_token
from core.deps import get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=Token)
def register(data: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        name=data.name,
        email=data.email,
        phone=data.phone,
        password_hash=hash_password(data.password),
        role=data.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token({"sub": str(user.id)})
    return Token(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=Token)
def login(data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account deactivated")
    token = create_access_token({"sub": str(user.id)})
    return Token(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/forgot-password")
def forgot_password(data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    # In production: send reset email. For MVP, just confirm user exists.
    db.query(User).filter(User.email == data.email).first()
    return {"message": "If this email exists, a reset link will be sent."}
