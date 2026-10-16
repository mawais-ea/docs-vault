from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import create_token, current_user, hash_password, new_api_key, verify_password
from ..config import get_settings
from ..db import get_db
from ..models import User
from ..schemas import LoginIn, MeOut, RegisterIn, TokenOut
from ..services.pipeline import seed_default_categories

router = APIRouter(tags=["account"])


@router.post("/auth/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if not get_settings().allow_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is closed")
    email = body.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(email=email, password_hash=hash_password(body.password), api_key=new_api_key())
    db.add(user)
    db.flush()
    seed_default_categories(db, user)
    db.commit()
    return TokenOut(access_token=create_token(user.id), api_key=user.api_key)


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")
    return TokenOut(access_token=create_token(user.id), api_key=user.api_key)


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user)):
    return MeOut(id=user.id, email=user.email, api_key=user.api_key)


@router.post("/me/rotate-key", response_model=MeOut)
def rotate_key(user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.api_key = new_api_key()
    db.commit()
    return MeOut(id=user.id, email=user.email, api_key=user.api_key)
