from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from database import get_db
from models import User
from core.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = db.query(User).filter(User.id == int(payload.get("sub"))).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_roles(*roles):
    def checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user
    return checker


def owner_or_admin(user: User = Depends(get_current_user)) -> User:
    if user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
