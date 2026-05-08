"""
Router de Autenticação — Login, registro e gestão de usuários.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse, RegisterRequest
from app.schemas.user import UserResponse, UserUpdate, UserListResponse, UserProfileUpdate
from app.utils.security import (
    hash_password, verify_password, create_access_token,
    get_current_user, require_admin,
)

router = APIRouter(prefix="/auth", tags=["Autenticação"])


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Autenticação via email/senha → retorna JWT."""
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuário desativado")

    token = create_access_token(str(user.id), user.role)

    return TokenResponse(
        access_token=token,
        user_id=str(user.id),
        role=user.role,
        name=user.name,
    )


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    data: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Registro de novo usuário (apenas admins)."""
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email já cadastrado")

    user = User(
        name=data.name,
        email=data.email,
        password_hash=hash_password(data.password),
        role=data.role,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Retorna dados do usuário autenticado."""
    return current_user


@router.patch("/me", response_model=UserResponse)
async def update_me(
    data: UserProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Atualiza o próprio perfil do usuário autenticado."""
    if data.email and data.email != current_user.email:
        existing = await db.execute(select(User).where(User.email == data.email))
        existing_user = existing.scalar_one_or_none()
        if existing_user and existing_user.id != current_user.id:
            raise HTTPException(status_code=400, detail="Email já cadastrado")

    if data.new_password:
        if not data.current_password:
            raise HTTPException(status_code=400, detail="Informe a senha atual para definir uma nova senha")
        if not verify_password(data.current_password, current_user.password_hash):
            raise HTTPException(status_code=400, detail="Senha atual incorreta")
        current_user.password_hash = hash_password(data.new_password)

    if data.name is not None:
        current_user.name = data.name
    if data.email is not None:
        current_user.email = str(data.email)

    await db.flush()
    await db.refresh(current_user)
    return current_user


@router.get("/users", response_model=UserListResponse)
async def list_users(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Lista todos os usuários (apenas admins)."""
    result = await db.execute(select(User).order_by(User.name))
    users = result.scalars().all()
    return UserListResponse(items=users, total=len(users))


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Atualiza um usuário (apenas admins)."""
    import uuid
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)

    await db.flush()
    await db.refresh(user)
    return user
