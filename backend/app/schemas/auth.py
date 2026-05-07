"""Schemas de autenticação."""

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    role: str
    name: str


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str = "collaborator"
