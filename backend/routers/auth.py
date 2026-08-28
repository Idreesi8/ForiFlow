"""Login endpoint. Public: issues a JWT; does not require one."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from config import JWT_EXPIRE_HOURS
from models.database import get_db
from schemas import LoginRequest, TokenResponse
from services.auth_service import authenticate_user, create_access_token

router = APIRouter(prefix="/auth", tags=["Auth"])

DbSession = Annotated[Session, Depends(get_db)]


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Exchange username and password for a JWT",
)
async def login(body: LoginRequest, db: DbSession) -> TokenResponse:
    """Return an 8-hour Bearer token when the credentials match a seeded user."""
    user = authenticate_user(db, body.username, body.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    token = create_access_token(username=user.username, role=user.role)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=int(JWT_EXPIRE_HOURS * 3600),
        username=user.username,
        role=user.role,
    )
