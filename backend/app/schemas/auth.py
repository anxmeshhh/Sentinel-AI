import uuid

from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=200)
    password: str = Field(..., min_length=8, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RequestOtpRequest(BaseModel):
    email: EmailStr
    purpose: str = "login"  # "login" | "email_verify"


class VerifyOtpRequest(BaseModel):
    email: EmailStr
    purpose: str = "login"
    code: str = Field(..., min_length=4, max_length=10)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    email_verified: bool

    model_config = {"from_attributes": True}
