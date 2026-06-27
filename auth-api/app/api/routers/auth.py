from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from app.database import get_db
from app.models import User, Tenant, UserRole
from app.auth import hash_password, verify_password, create_access_token, get_current_user, require_role

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    tenant_slug: str
    role: str = "user"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    tenant: str


class UserResponse(BaseModel):
    id: str
    email: str
    role: str
    tenant: str

    class Config:
        from_attributes = True


@router.post("/register", response_model=UserResponse, status_code=201,
             dependencies=[Depends(require_role("admin"))])
def register(body: RegisterRequest, db: Session = Depends(get_db),
             current_user: User = Depends(get_current_user)):
    # Admin can only add users to their own tenant
    tenant = db.query(Tenant).filter(
        Tenant.slug == body.tenant_slug,
        Tenant.id == current_user.tenant_id
    ).first()
    if not tenant:
        raise HTTPException(
            status_code=403,
            detail="You can only add users to your own tenant"
        )

    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    role = UserRole(body.role) if body.role in UserRole._value2member_map_ else UserRole.user

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        tenant_id=tenant.id,
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return UserResponse(
        id=str(user.id),
        email=user.email,
        role=user.role,
        tenant=tenant.slug
    )


@router.post("/login", response_model=TokenResponse)
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == form.username).first()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    token = create_access_token(data={
        "sub": str(user.id),
        "tenant": str(user.tenant_id),
        "role": user.role,
    })
    return TokenResponse(
        access_token=token,
        role=user.role,
        tenant=user.tenant.slug
    )


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        role=current_user.role,
        tenant=current_user.tenant.slug,
    )
