"""Signup, login, OTP, and Google/Microsoft OAuth.

Deliberately not integrated into get_workspace_id or any existing route yet
(see api/deps.py's get_current_user docstring) - this ships as a complete,
working, standalone auth subsystem first; wiring it into workspace
resolution/RBAC is IA.md v2 §8.2's next step, not bundled into this one.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.auth import create_access_token
from app.core.config import get_settings
from app.core.oauth import GOOGLE_CONFIGURED, MICROSOFT_CONFIGURED, oauth
from app.models.otp_code import OtpPurpose
from app.models.user import User
from app.schemas.auth import LoginRequest, RequestOtpRequest, SignupRequest, TokenResponse, UserOut, VerifyOtpRequest
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _purpose(value: str) -> OtpPurpose:
    try:
        return OtpPurpose(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="purpose must be 'login' or 'email_verify'")


@router.post("/signup", status_code=202)
def signup(payload: SignupRequest, session: Session = Depends(get_db)) -> dict:
    try:
        user = auth_service.create_user_with_password(
            session, email=payload.email, name=payload.name, password=payload.password
        )
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    auth_service.generate_and_send_otp(session, user=user, purpose=OtpPurpose.EMAIL_VERIFY)
    return {"detail": "Account created - check your email for a verification code"}


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, session: Session = Depends(get_db)) -> TokenResponse:
    try:
        user = auth_service.authenticate_with_password(session, email=payload.email, password=payload.password)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/request-otp", status_code=202)
def request_otp(payload: RequestOtpRequest, session: Session = Depends(get_db)) -> dict:
    purpose = _purpose(payload.purpose)
    user = auth_service.get_user_by_email(session, payload.email)
    if user is None:
        # Don't reveal whether the email has an account - same response either way.
        return {"detail": "If that account exists, a code has been sent"}
    auth_service.generate_and_send_otp(session, user=user, purpose=purpose)
    return {"detail": "If that account exists, a code has been sent"}


@router.post("/verify-otp", response_model=TokenResponse)
def verify_otp(payload: VerifyOtpRequest, session: Session = Depends(get_db)) -> TokenResponse:
    purpose = _purpose(payload.purpose)
    user = auth_service.get_user_by_email(session, payload.email)
    if user is None:
        raise HTTPException(status_code=400, detail="Incorrect code")
    try:
        auth_service.verify_otp(session, user=user, purpose=purpose, code=payload.code)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


# --- OAuth ---

def _redirect_with_token(user_id: uuid.UUID) -> RedirectResponse:
    token = create_access_token(user_id)
    settings = get_settings()
    return RedirectResponse(f"{settings.frontend_base_url}/auth/callback#token={token}")


@router.get("/google/login")
async def google_login(request: Request):
    if not GOOGLE_CONFIGURED:
        raise HTTPException(status_code=501, detail="Google sign-in is not configured yet")
    redirect_uri = f"{get_settings().backend_base_url}/auth/google/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, session: Session = Depends(get_db)):
    if not GOOGLE_CONFIGURED:
        raise HTTPException(status_code=501, detail="Google sign-in is not configured yet")
    token = await oauth.google.authorize_access_token(request)
    userinfo = token.get("userinfo") or {}
    user = auth_service.find_or_create_oauth_user(
        session,
        provider="google",
        sub=userinfo["sub"],
        email=userinfo["email"],
        name=userinfo.get("name", userinfo["email"]),
    )
    return _redirect_with_token(user.id)


@router.get("/microsoft/login")
async def microsoft_login(request: Request):
    if not MICROSOFT_CONFIGURED:
        raise HTTPException(status_code=501, detail="Microsoft sign-in is not configured yet")
    redirect_uri = f"{get_settings().backend_base_url}/auth/microsoft/callback"
    return await oauth.microsoft.authorize_redirect(request, redirect_uri)


@router.get("/microsoft/callback")
async def microsoft_callback(request: Request, session: Session = Depends(get_db)):
    if not MICROSOFT_CONFIGURED:
        raise HTTPException(status_code=501, detail="Microsoft sign-in is not configured yet")
    token = await oauth.microsoft.authorize_access_token(request)
    userinfo = token.get("userinfo") or {}
    user = auth_service.find_or_create_oauth_user(
        session,
        provider="microsoft",
        sub=userinfo["sub"],
        email=userinfo["email"],
        name=userinfo.get("name", userinfo["email"]),
    )
    return _redirect_with_token(user.id)
