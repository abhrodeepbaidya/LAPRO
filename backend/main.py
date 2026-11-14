import os
import re
import secrets
import hmac
from datetime import datetime, timedelta, timezone
from typing import Generator, Optional

import jwt
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from pwdlib import PasswordHash
from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
    create_engine, func, select, desc, or_, inspect as sa_inspect, text
)
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./lapro_dev.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://") and "+psycopg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET or len(JWT_SECRET) < 32:
    raise RuntimeError("Set JWT_SECRET to a random secret of at least 32 characters")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "30"))
REFRESH_TOKEN_DAYS = int(os.getenv("REFRESH_TOKEN_DAYS", "14"))
OWNER_EMAIL = os.getenv("OWNER_EMAIL", "").strip().lower()
MASTER_PASSCODE = os.getenv("MASTER_PASSCODE", "")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
FRONTEND_ORIGINS = [
    item.strip() for item in os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:5500,http://127.0.0.1:5500,https://abhrodeepbaidya.github.io"
    ).split(",") if item.strip()
]
if "*" in FRONTEND_ORIGINS:
    raise RuntimeError("Wildcard CORS is not allowed when credentials are enabled")

engine_args = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_args["connect_args"] = {"check_same_thread": False}
engine = create_engine(DATABASE_URL, **engine_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Database models
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alias: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    google_sub: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(20), default="user", index=True)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    answer_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    restricted_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(20), index=True)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="published", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Comment(Base):
    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Like(Base):
    __tablename__ = "likes"
    __table_args__ = (UniqueConstraint("post_id", "user_id", name="uq_like_post_user"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class XPEvent(Base):
    __tablename__ = "xp_events"
    __table_args__ = (UniqueConstraint("event_key", name="uq_xp_event_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    points: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(50))
    event_key: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    target_type: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    reason: Mapped[str] = mapped_column(String(40))
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SupportTicket(Base):
    __tablename__ = "support_tickets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(30), index=True)
    subject: Mapped[str] = mapped_column(String(160))
    details: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    admin_reply: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(60))
    target_type: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[int] = mapped_column(Integer)
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserBlock(Base):
    __tablename__ = "user_blocks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    blocker_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    blocked_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlatformSetting(Base):
    __tablename__ = "platform_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    body: Mapped[str] = mapped_column(Text)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class BGMINews(Base):
    __tablename__ = "bgmi_news"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    tag: Mapped[str] = mapped_column(String(30), default="News")
    source_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="published", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(String(240))
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


Base.metadata.create_all(bind=engine)
# Add the nullable Google subject column to existing deployments.
if "google_sub" not in {column["name"] for column in sa_inspect(engine).get_columns("users")}:
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE users ADD COLUMN google_sub VARCHAR(255)"))
with engine.begin() as connection:
    connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_sub ON users (google_sub)"))

# ---------------------------------------------------------------------------
# API, schemas and helpers
# ---------------------------------------------------------------------------
app = FastAPI(
    title="LAPRO API",
    description="Anonymous community API: accounts, posts, comments, XP, moderation and inbox.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

password_hasher = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
ROLES = {"owner", "admin", "manager", "supervisor", "guard", "user"}
STAFF_ROLES = {"owner", "admin", "manager", "supervisor", "guard"}
CATEGORIES = {"thought", "feeling", "question", "fact", "kindness"}
REPORT_REASONS = {"spam", "harassment", "hate", "personal_info", "threat", "other"}


class RegisterInput(BaseModel):
    alias: str = Field(min_length=3, max_length=30, pattern=r"^[A-Za-z0-9_]+$")
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class LoginInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class GoogleAuthInput(BaseModel):
    credential: str = Field(min_length=20, max_length=10000)
    alias: Optional[str] = Field(default=None, min_length=3, max_length=30, pattern=r"^[A-Za-z0-9_]+$")


class RefreshInput(BaseModel):
    refresh_token: str


class PostInput(BaseModel):
    category: str
    body: str = Field(min_length=1, max_length=3000)


class CommentInput(BaseModel):
    body: str = Field(min_length=1, max_length=1500)


class ReportInput(BaseModel):
    target_type: str
    target_id: int = Field(gt=0)
    reason: str
    details: Optional[str] = Field(default=None, max_length=1000)


class SupportTicketInput(BaseModel):
    category: str = Field(min_length=3, max_length=30)
    subject: str = Field(min_length=4, max_length=160)
    details: str = Field(min_length=10, max_length=4000)


class SupportTicketUpdate(BaseModel):
    status: str = Field(pattern=r"^(reviewing|resolved|closed)$")
    admin_reply: Optional[str] = Field(default=None, max_length=2000)


class WarningInput(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    send_email: bool = False


class StaffPostInput(BaseModel):
    category: str = Field(min_length=3, max_length=20)
    body: str = Field(min_length=1, max_length=3000)


class ChatMaintenanceInput(BaseModel):
    enabled: bool
    duration_minutes: int = Field(default=60, ge=1, le=10080)
    notice: str = Field(default="Chat is temporarily disabled for maintenance. Please try again later.", min_length=10, max_length=240)


class MessageInput(BaseModel):
    recipient_id: int = Field(gt=0)
    body: str = Field(min_length=1, max_length=2000)


class BGMINewsInput(BaseModel):
    title: str = Field(min_length=5, max_length=160)
    body: str = Field(min_length=10, max_length=8000)
    tag: str = Field(default="News", max_length=30)
    source_url: Optional[str] = Field(default=None, max_length=1000)


class RoleInput(BaseModel):
    role: str


class RestrictionInput(BaseModel):
    days: int = Field(ge=1, le=3650)
    reason: str = Field(min_length=3, max_length=500)


class XPAdjustmentInput(BaseModel):
    points: int = Field(ge=-10000, le=10000)
    reason: str = Field(min_length=3, max_length=300)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    alias: str
    role: str
    xp: int
    status: str
    created_at: datetime


class PostOut(BaseModel):
    id: int
    author_id: int
    author_alias: str
    author_xp: int
    category: str
    body: str
    like_count: int
    comment_count: int
    created_at: datetime


def db_session() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def token_for(user: User, token_type: str, expires: timedelta) -> str:
    now = utcnow()
    return jwt.encode(
        {"sub": str(user.id), "type": token_type, "iat": now, "exp": now + expires,
         "jti": secrets.token_urlsafe(16)},
        JWT_SECRET, algorithm=JWT_ALGORITHM
    )


def decode_token(token: str, expected_type: str) -> int:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != expected_type:
            raise ValueError("wrong token type")
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(db_session)) -> User:
    user_id = decode_token(token, "access")
    user = db.get(User, user_id)
    if not user or user.status == "banned":
        raise HTTPException(status_code=401, detail="Account unavailable")
    if user.status == "restricted" and user.restricted_until:
        expiry = user.restricted_until
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= utcnow():
            user.status = "active"
            user.restricted_until = None
            # Persist automatic expiry of a temporary restriction.
            db.commit()
    return user


def require_roles(*roles: str):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return dependency


def ensure_can_post(user: User):
    if user.status == "banned":
        raise HTTPException(status_code=403, detail="Account is banned")
    if user.status == "restricted":
        expiry = user.restricted_until
        if expiry is None:
            raise HTTPException(status_code=403, detail="Account is restricted")
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry > utcnow():
            raise HTTPException(status_code=403, detail="Posting restriction is active")
        user.status = "active"
        user.restricted_until = None


def add_xp(db: Session, user: User, points: int, reason: str, event_key: str):
    if points == 0:
        return
    existing = db.scalar(select(XPEvent).where(XPEvent.event_key == event_key))
    if existing:
        return
    db.add(XPEvent(user_id=user.id, points=points, reason=reason, event_key=event_key))
    user.xp = max(0, user.xp + points)


def notify(db: Session, user_id: int, kind: str, message: str):
    db.add(Notification(user_id=user_id, kind=kind, message=message[:240]))


def audit(db: Session, actor: User, action: str, target_type: str, target_id: int, details: str = ""):
    db.add(AuditLog(actor_id=actor.id, action=action, target_type=target_type,
                    target_id=target_id, details=details[:2000]))


def post_payload(db: Session, post: Post) -> dict:
    author = db.get(User, post.author_id)
    return {
        "id": post.id, "author_id": post.author_id,
        "author_alias": author.alias if author else "Unknown",
        "author_xp": author.xp if author else 0,
        "category": post.category, "body": post.body,
        "like_count": db.scalar(select(func.count(Like.id)).where(Like.post_id == post.id)) or 0,
        "comment_count": db.scalar(select(func.count(Comment.id)).where(Comment.post_id == post.id)) or 0,
        "created_at": post.created_at,
    }


def create_tokens(user: User) -> dict:
    return {
        "access_token": token_for(user, "access", timedelta(minutes=ACCESS_TOKEN_MINUTES)),
        "refresh_token": token_for(user, "refresh", timedelta(days=REFRESH_TOKEN_DAYS)),
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_MINUTES * 60,
    }


# ---------------------------------------------------------------------------
# Health and authentication
# ---------------------------------------------------------------------------
@app.get("/")
def root():
    return {"service": "LAPRO API", "version": app.version, "docs": "/docs"}


@app.get("/health")
def health(db: Session = Depends(db_session)):
    db.execute(select(1))
    return {"status": "ok", "database": "connected"}


@app.post("/auth/register", response_model=UserOut, status_code=201)
def register(data: RegisterInput, db: Session = Depends(db_session)):
    alias = data.alias.strip()
    email = str(data.email).lower().strip()
    if db.scalar(select(User).where(or_(func.lower(User.email) == email, func.lower(User.alias) == alias.lower()))):
        raise HTTPException(status_code=409, detail="Email or alias already registered")
    role = "owner" if OWNER_EMAIL and email == OWNER_EMAIL else "user"
    user = User(alias=alias, email=email, password_hash=password_hasher.hash(data.password), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/master/login")
def master_login(data: LoginInput, db: Session = Depends(db_session)):
    if not MASTER_PASSCODE:
        raise HTTPException(status_code=503, detail="Master passcode is not configured")
    email = str(data.email).lower().strip()
    if not OWNER_EMAIL or email != OWNER_EMAIL or not hmac.compare_digest(data.password, MASTER_PASSCODE):
        raise HTTPException(status_code=401, detail="Incorrect owner email or passcode")
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if not user or user.role != "owner":
        raise HTTPException(status_code=403, detail="Owner account is not registered yet")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="Owner account is unavailable")
    return create_tokens(user)


@app.post("/auth/login")
def login(data: LoginInput, db: Session = Depends(db_session)):
    email = str(data.email).lower().strip()
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if not user or not password_hasher.verify(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if user.status == "banned":
        raise HTTPException(status_code=403, detail="Account is banned")
    return create_tokens(user)


@app.post("/auth/google")
def google_auth(data: GoogleAuthInput, db: Session = Depends(db_session)):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured on this server")
    try:
        claims = google_id_token.verify_oauth2_token(
            data.credential, google_requests.Request(), GOOGLE_CLIENT_ID
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Google credential is invalid or expired")
    if not claims.get("email_verified"):
        raise HTTPException(status_code=403, detail="Google account email is not verified")
    email = str(claims.get("email", "")).strip().lower()
    subject = str(claims.get("sub", "")).strip()
    if not email or not subject:
        raise HTTPException(status_code=401, detail="Google account is missing required identity claims")

    user = db.scalar(select(User).where(User.google_sub == subject))
    if not user:
        user = db.scalar(select(User).where(func.lower(User.email) == email))
        if user:
            if user.google_sub and user.google_sub != subject:
                raise HTTPException(status_code=409, detail="This email is already linked to another Google account")
            user.google_sub = subject
        else:
            base_alias = (data.alias or email.split("@", 1)[0]).strip()
            base_alias = re.sub(r"[^A-Za-z0-9_]", "_", base_alias)[:24]
            if len(base_alias) < 3:
                base_alias = "user_" + secrets.token_hex(3)
            alias = base_alias
            while db.scalar(select(User.id).where(func.lower(User.alias) == alias.lower())):
                alias = (base_alias[:23] + "_" + secrets.token_hex(2))[:30]
            role = "owner" if OWNER_EMAIL and email == OWNER_EMAIL else "user"
            user = User(
                alias=alias, email=email, google_sub=subject,
                password_hash=password_hasher.hash(secrets.token_urlsafe(48)),
                role=role,
            )
            db.add(user)
    if user.status == "banned":
        raise HTTPException(status_code=403, detail="Account is banned")
    db.commit()
    db.refresh(user)
    return create_tokens(user)


@app.post("/auth/refresh")
def refresh(data: RefreshInput, db: Session = Depends(db_session)):
    user_id = decode_token(data.refresh_token, "refresh")
    user = db.get(User, user_id)
    if not user or user.status == "banned":
        raise HTTPException(status_code=401, detail="Account unavailable")
    return create_tokens(user)


@app.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


# ---------------------------------------------------------------------------
# Community posts, comments, likes and public profile
# ---------------------------------------------------------------------------
@app.get("/posts")
def list_posts(
    category: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None, max_length=100),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(db_session),
):
    stmt = select(Post).where(Post.status == "published")
    if category:
        category = category.lower()
        if category not in CATEGORIES:
            raise HTTPException(status_code=400, detail="Invalid category")
        stmt = stmt.where(Post.category == category)
    if search:
        stmt = stmt.where(Post.body.ilike(f"%{search}%"))
    posts = db.scalars(stmt.order_by(desc(Post.created_at)).offset(offset).limit(limit)).all()
    return {"items": [post_payload(db, post) for post in posts], "limit": limit, "offset": offset}


@app.post("/posts", status_code=201)
def create_post(data: PostInput, user: User = Depends(get_current_user), db: Session = Depends(db_session)):
    ensure_can_post(user)
    category = data.category.lower()
    if category not in CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid category")
    body = data.body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="Post cannot be empty")
    post = Post(author_id=user.id, category=category, body=body)
    db.add(post)
    db.flush()
    db.commit()
    db.refresh(post)
    return post_payload(db, post)


@app.get("/posts/{post_id}")
def get_post(post_id: int, db: Session = Depends(db_session)):
    post = db.get(Post, post_id)
    if not post or post.status != "published":
        raise HTTPException(status_code=404, detail="Post not found")
    return post_payload(db, post)


@app.patch("/posts/{post_id}")
def edit_post(post_id: int, data: PostInput, user: User = Depends(get_current_user), db: Session = Depends(db_session)):
    ensure_can_post(user)
    post = db.get(Post, post_id)
    if not post or (post.author_id != user.id and user.role not in STAFF_ROLES):
        raise HTTPException(status_code=404, detail="Post not found")
    category = data.category.lower()
    if category not in CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid category")
    post.category, post.body, post.updated_at = category, data.body.strip(), utcnow()
    db.commit()
    return post_payload(db, post)


@app.delete("/posts/{post_id}")
def delete_post(post_id: int, user: User = Depends(get_current_user), db: Session = Depends(db_session)):
    post = db.get(Post, post_id)
    if not post or (post.author_id != user.id and user.role not in STAFF_ROLES):
        raise HTTPException(status_code=404, detail="Post not found")
    post.status = "removed"
    db.commit()
    return {"ok": True, "message": "Post removed"}


@app.get("/posts/{post_id}/comments")
def list_comments(post_id: int, db: Session = Depends(db_session)):
    post = db.get(Post, post_id)
    if not post or post.status != "published":
        raise HTTPException(status_code=404, detail="Post not found")
    rows = db.execute(
        select(Comment, User).join(User, User.id == Comment.author_id)
        .where(Comment.post_id == post_id).order_by(Comment.created_at.asc())
    ).all()
    return [{"id": c.id, "post_id": c.post_id, "author_id": c.author_id,
             "author_alias": u.alias, "body": c.body, "created_at": c.created_at} for c, u in rows]


@app.post("/posts/{post_id}/comments", status_code=201)
def add_comment(post_id: int, data: CommentInput, user: User = Depends(get_current_user), db: Session = Depends(db_session)):
    ensure_can_post(user)
    post = db.get(Post, post_id)
    if not post or post.status != "published":
        raise HTTPException(status_code=404, detail="Post not found")
    comment = Comment(post_id=post_id, author_id=user.id, body=data.body.strip())
    db.add(comment)
    db.flush()
    user.answer_count += 1
    add_xp(db, user, 1, "answer_posted", f"answer:{comment.id}")
    if user.answer_count % 50 == 0:
        add_xp(db, user, 10, "answer_50_milestone", f"user:{user.id}:answers:{user.answer_count}")
    if post.author_id != user.id:
        notify(db, post.author_id, "comment", f"{user.alias} replied to your post")
    db.commit()
    db.refresh(comment)
    return {"id": comment.id, "post_id": post_id, "author_id": user.id,
            "author_alias": user.alias, "body": comment.body, "created_at": comment.created_at}


@app.delete("/comments/{comment_id}")
def delete_comment(comment_id: int, user: User = Depends(get_current_user), db: Session = Depends(db_session)):
    comment = db.get(Comment, comment_id)
    if not comment or (comment.author_id != user.id and user.role not in STAFF_ROLES):
        raise HTTPException(status_code=404, detail="Comment not found")
    db.delete(comment)
    db.commit()
    return {"ok": True}


@app.post("/posts/{post_id}/like")
def toggle_like(post_id: int, user: User = Depends(get_current_user), db: Session = Depends(db_session)):
    post = db.get(Post, post_id)
    if not post or post.status != "published":
        raise HTTPException(status_code=404, detail="Post not found")
    existing = db.scalar(select(Like).where(Like.post_id == post_id, Like.user_id == user.id))
    if existing:
        db.delete(existing)
        db.commit()
        return {"liked": False, "like_count": db.scalar(select(func.count(Like.id)).where(Like.post_id == post_id))}
    db.add(Like(post_id=post_id, user_id=user.id))
    db.flush()
    count = db.scalar(select(func.count(Like.id)).where(Like.post_id == post_id)) or 0
    # XP is granted only to the post author at each new 10-like milestone.
    if post.author_id != user.id and count > 0 and count % 10 == 0:
        author = db.get(User, post.author_id)
        if author:
            add_xp(db, author, 1, "post_likes_milestone", f"post:{post_id}:likes:{count}")
            notify(db, author.id, "xp", "Your post reached a like milestone: +1 XP")
    db.commit()
    return {"liked": True, "like_count": count}


@app.get("/users/{user_id}")
def public_profile(user_id: int, db: Session = Depends(db_session)):
    user = db.get(User, user_id)
    if not user or user.status == "banned":
        raise HTTPException(status_code=404, detail="User not found")
    return {"id": user.id, "alias": user.alias, "role": user.role,
            "xp": user.xp, "answer_count": user.answer_count, "created_at": user.created_at}


@app.get("/users/{user_id}/posts")
def user_posts(user_id: int, limit: int = Query(default=25, ge=1, le=100), db: Session = Depends(db_session)):
    posts = db.scalars(select(Post).where(Post.author_id == user_id, Post.status == "published")
                       .order_by(desc(Post.created_at)).limit(limit)).all()
    return [post_payload(db, post) for post in posts]


# ---------------------------------------------------------------------------
# Reports, staff tools, moderation and audit trail
# ---------------------------------------------------------------------------
@app.post("/reports", status_code=201)
def create_report(data: ReportInput, user: User = Depends(get_current_user), db: Session = Depends(db_session)):
    target_type = data.target_type.lower()
    reason = data.reason.lower()
    if target_type not in {"post", "comment", "user"} or reason not in REPORT_REASONS:
        raise HTTPException(status_code=400, detail="Invalid report target or reason")
    report = Report(reporter_id=user.id, target_type=target_type, target_id=data.target_id,
                    reason=reason, details=data.details)
    db.add(report)
    db.commit()
    db.refresh(report)
    return {"id": report.id, "status": report.status}


@app.get("/staff/reports")
def staff_reports(
    report_status: str = Query(default="open", alias="status"),
    user: User = Depends(require_roles("owner", "admin", "manager", "supervisor", "guard")),
    db: Session = Depends(db_session),
):
    stmt = select(Report)
    if report_status != "all":
        stmt = stmt.where(Report.status == report_status)
    reports = db.scalars(stmt.order_by(desc(Report.created_at)).limit(200)).all()
    return [{"id": r.id, "reporter_id": r.reporter_id, "target_type": r.target_type,
             "target_id": r.target_id, "reason": r.reason, "details": r.details,
             "status": r.status, "created_at": r.created_at} for r in reports]


@app.patch("/staff/reports/{report_id}")
def resolve_report(
    report_id: int,
    report_status: str = Query(alias="status", pattern="^(reviewing|resolved|dismissed)$"),
    user: User = Depends(require_roles("owner", "admin", "manager", "supervisor", "guard")),
    db: Session = Depends(db_session),
):
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    report.status = report_status
    audit(db, user, "report_status_changed", "report", report_id, report_status)
    db.commit()
    return {"id": report.id, "status": report.status}


@app.patch("/staff/users/{user_id}/role")
def change_role(
    user_id: int, data: RoleInput,
    user: User = Depends(require_roles("owner", "admin")),
    db: Session = Depends(db_session),
):
    target = db.get(User, user_id)
    new_role = data.role.lower()
    if not target or new_role not in ROLES:
        raise HTTPException(status_code=404, detail="User or role not found")
    if target.role == "owner":
        raise HTTPException(status_code=403, detail="Owner role cannot be changed through this endpoint")
    if user.role == "admin" and new_role in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Admins cannot appoint owners or admins")
    target.role = new_role
    audit(db, user, "role_changed", "user", target.id, f"role={new_role}")
    db.commit()
    return {"user_id": target.id, "role": target.role}


@app.post("/staff/users/{user_id}/restrict")
def restrict_user(
    user_id: int, data: RestrictionInput,
    user: User = Depends(require_roles("owner", "admin", "manager", "supervisor")),
    db: Session = Depends(db_session),
):
    target = db.get(User, user_id)
    if not target or target.role == "owner" or (user.role != "owner" and target.role in {"admin", "manager"}):
        raise HTTPException(status_code=404, detail="User not found or action not allowed")
    target.restricted_until = utcnow() + timedelta(days=data.days)
    target.status = "restricted"
    audit(db, user, "user_restricted", "user", target.id, f"{data.days} days: {data.reason}")
    db.commit()
    return {"user_id": target.id, "status": target.status, "restricted_until": target.restricted_until}


@app.post("/staff/users/{user_id}/ban")
def ban_user(
    user_id: int, data: RestrictionInput,
    user: User = Depends(require_roles("owner", "admin")),
    db: Session = Depends(db_session),
):
    target = db.get(User, user_id)
    if not target or target.role == "owner" or (user.role == "admin" and target.role in {"admin", "manager"}):
        raise HTTPException(status_code=404, detail="User not found or action not allowed")
    target.status = "banned"
    target.restricted_until = utcnow() + timedelta(days=data.days)
    audit(db, user, "user_banned", "user", target.id, f"{data.days} days: {data.reason}")
    db.commit()
    return {"user_id": target.id, "status": target.status, "days": data.days}


@app.post("/staff/users/{user_id}/unban")
def unban_user(
    user_id: int,
    user: User = Depends(require_roles("owner", "admin")),
    db: Session = Depends(db_session),
):
    target = db.get(User, user_id)
    if not target or target.role == "owner":
        raise HTTPException(status_code=404, detail="User not found")
    target.status = "active"
    target.restricted_until = None
    audit(db, user, "user_unbanned", "user", target.id)
    db.commit()
    return {"user_id": target.id, "status": target.status}


@app.post("/staff/users/{user_id}/xp")
def adjust_xp(
    user_id: int, data: XPAdjustmentInput,
    user: User = Depends(require_roles("owner", "admin")),
    db: Session = Depends(db_session),
):
    target = db.get(User, user_id)
    if not target or target.role == "owner" and user.role != "owner":
        raise HTTPException(status_code=404, detail="User not found")
    event_key = f"staff-adjust:{user.id}:{target.id}:{secrets.token_urlsafe(12)}"
    add_xp(db, target, data.points, "staff_adjustment", event_key)
    audit(db, user, "xp_adjusted", "user", target.id, f"{data.points}: {data.reason}")
    db.commit()
    return {"user_id": target.id, "xp": target.xp}


@app.get("/staff/audit")
def staff_audit(
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(require_roles("owner", "admin")),
    db: Session = Depends(db_session),
):
    rows = db.scalars(select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)).all()
    return [{"id": x.id, "actor_id": x.actor_id, "action": x.action,
             "target_type": x.target_type, "target_id": x.target_id,
             "details": x.details, "created_at": x.created_at} for x in rows]


# ---------------------------------------------------------------------------
# User blocking, staff warnings, global content and chat moderation
# ---------------------------------------------------------------------------
@app.post("/users/{user_id}/block")
def block_user(user_id: int, user: User = Depends(get_current_user), db: Session = Depends(db_session)):
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="You cannot block yourself")
    target = db.get(User, user_id)
    if not target or target.role in {"owner", "admin"}:
        raise HTTPException(status_code=404, detail="User not found")
    existing = db.scalar(select(UserBlock).where(
        UserBlock.blocker_id == user.id, UserBlock.blocked_id == user_id
    ))
    if not existing:
        db.add(UserBlock(blocker_id=user.id, blocked_id=user_id))
        db.commit()
    return {"blocked": True, "user_id": user_id}


@app.delete("/users/{user_id}/block")
def unblock_user(user_id: int, user: User = Depends(get_current_user), db: Session = Depends(db_session)):
    existing = db.scalar(select(UserBlock).where(
        UserBlock.blocker_id == user.id, UserBlock.blocked_id == user_id
    ))
    if existing:
        db.delete(existing)
        db.commit()
    return {"blocked": False, "user_id": user_id}


@app.post("/staff/users/{user_id}/warning")
def warn_user(user_id: int, data: WarningInput,
              user: User = Depends(require_roles("owner", "admin", "manager", "supervisor")),
              db: Session = Depends(db_session)):
    target = db.get(User, user_id)
    if not target or target.role == "owner" or (user.role != "owner" and target.role in {"admin", "manager"}):
        raise HTTPException(status_code=404, detail="User not found or action not allowed")
    message = "LAPRO account warning: " + data.reason.strip()
    notify(db, target.id, "account_warning", message)
    audit(db, user, "user_warning_sent", "user", target.id, data.reason.strip())
    db.commit()
    return {"user_id": target.id, "warning_sent": True,
            "email_status": "not_configured" if data.send_email else "not_requested",
            "message": "In-app warning delivered. Email delivery requires verified SMTP/email provider configuration."}


@app.get("/staff/posts")
def staff_all_posts(
    post_status: str = Query(default="all", alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(require_roles("owner", "admin", "manager", "supervisor")),
    db: Session = Depends(db_session),
):
    stmt = select(Post)
    if post_status != "all":
        stmt = stmt.where(Post.status == post_status)
    rows = db.scalars(stmt.order_by(desc(Post.created_at)).limit(limit)).all()
    return [post_payload(db, post) for post in rows]


@app.post("/staff/posts", status_code=201)
def staff_publish_post(data: StaffPostInput,
                       user: User = Depends(require_roles("owner", "admin", "manager", "supervisor")),
                       db: Session = Depends(db_session)):
    category = data.category.lower().strip()
    if category not in CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid category")
    post = Post(author_id=user.id, category=category, body=data.body.strip())
    db.add(post)
    db.flush()
    audit(db, user, "staff_post_published", "post", post.id, category)
    db.commit()
    db.refresh(post)
    return post_payload(db, post)


@app.delete("/staff/posts/{post_id}")
def staff_delete_post(post_id: int,
                      user: User = Depends(require_roles("owner", "admin", "manager", "supervisor")),
                      db: Session = Depends(db_session)):
    post = db.get(Post, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    post.status = "removed"
    audit(db, user, "staff_post_removed", "post", post_id, "Removed from staff panel")
    db.commit()
    return {"ok": True, "id": post_id, "status": "removed"}


@app.delete("/staff/conversations/{user_a_id}/{user_b_id}")
def staff_delete_conversation(user_a_id: int, user_b_id: int,
                              user: User = Depends(require_roles("owner", "admin")),
                              db: Session = Depends(db_session)):
    if user_a_id == user_b_id or not db.get(User, user_a_id) or not db.get(User, user_b_id):
        raise HTTPException(status_code=404, detail="Conversation participants not found")
    rows = db.scalars(select(Message).where(
        or_(
            (Message.sender_id == user_a_id) & (Message.recipient_id == user_b_id),
            (Message.sender_id == user_b_id) & (Message.recipient_id == user_a_id),
        )
    )).all()
    count = len(rows)
    for row in rows:
        db.delete(row)
    audit(db, user, "conversation_deleted", "conversation", user_a_id,
          f"participants={user_a_id},{user_b_id}; messages_deleted={count}")
    db.commit()
    return {"ok": True, "messages_deleted": count}


# ---------------------------------------------------------------------------
# User feedback, bug reports and support tickets
# ---------------------------------------------------------------------------
@app.post("/support/tickets", status_code=201)
def create_support_ticket(
    data: SupportTicketInput, user: User = Depends(get_current_user), db: Session = Depends(db_session)
):
    category = data.category.strip().lower()
    if category not in {"bug", "technical_issue", "feature_request", "feedback", "complaint"}:
        raise HTTPException(status_code=400, detail="Invalid support category")
    ticket = SupportTicket(user_id=user.id, category=category, subject=data.subject.strip(),
                           details=data.details.strip())
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    notify(db, user.id, "support_received", f"LAPRO received your support request #{ticket.id}. Our team will review it.")
    db.commit()
    return {"id": ticket.id, "status": ticket.status, "message": "Support request submitted"}


@app.get("/support/tickets")
def my_support_tickets(user: User = Depends(get_current_user), db: Session = Depends(db_session)):
    rows = db.scalars(select(SupportTicket).where(SupportTicket.user_id == user.id)
                       .order_by(desc(SupportTicket.created_at)).limit(100)).all()
    return [{"id": t.id, "category": t.category, "subject": t.subject, "details": t.details,
             "status": t.status, "admin_reply": t.admin_reply, "created_at": t.created_at,
             "updated_at": t.updated_at} for t in rows]


@app.get("/staff/support/tickets")
def staff_support_tickets(
    ticket_status: str = Query(default="open", alias="status"),
    user: User = Depends(require_roles("owner", "admin", "manager", "supervisor")),
    db: Session = Depends(db_session),
):
    stmt = select(SupportTicket)
    if ticket_status != "all":
        stmt = stmt.where(SupportTicket.status == ticket_status)
    rows = db.scalars(stmt.order_by(desc(SupportTicket.created_at)).limit(300)).all()
    return [{"id": t.id, "user_id": t.user_id, "category": t.category, "subject": t.subject,
             "details": t.details, "status": t.status, "admin_reply": t.admin_reply,
             "created_at": t.created_at} for t in rows]


@app.patch("/staff/support/tickets/{ticket_id}")
def update_support_ticket(
    ticket_id: int, data: SupportTicketUpdate,
    user: User = Depends(require_roles("owner", "admin", "manager", "supervisor")),
    db: Session = Depends(db_session),
):
    ticket = db.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Support ticket not found")
    previous_status = ticket.status
    ticket.status = data.status
    if data.admin_reply is not None:
        ticket.admin_reply = data.admin_reply.strip()
    audit(db, user, "support_ticket_updated", "support_ticket", ticket_id,
          f"{previous_status} -> {ticket.status}")
    if ticket.status == "resolved" and previous_status != "resolved":
        message = f"Your LAPRO request #{ticket.id} has been resolved."
        if ticket.admin_reply:
            message += f" Team reply: {ticket.admin_reply}"
        notify(db, ticket.user_id, "support_resolved", message)
    elif ticket.status == "reviewing" and previous_status != "reviewing":
        notify(db, ticket.user_id, "support_reviewing",
               f"Your LAPRO request #{ticket.id} is now being reviewed by our team.")
    db.commit()
    return {"id": ticket.id, "status": ticket.status, "admin_reply": ticket.admin_reply}


# ---------------------------------------------------------------------------
# Chat maintenance controls
# ---------------------------------------------------------------------------
def chat_maintenance_state(db: Session) -> dict:
    row = db.get(PlatformSetting, "chat_maintenance")
    if not row:
        return {"enabled": False, "until": None,
                "notice": "Chat is temporarily disabled for maintenance. Please try again later."}
    try:
        state = __import__("json").loads(row.value)
    except (ValueError, TypeError):
        state = {}
    until = state.get("until")
    if state.get("enabled") and until:
        try:
            expiry = datetime.fromisoformat(until)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry <= utcnow():
                state["enabled"] = False
                row.value = __import__("json").dumps(state)
                db.commit()
        except ValueError:
            state["enabled"] = False
    return {"enabled": bool(state.get("enabled")), "until": state.get("until"),
            "notice": state.get("notice") or "Chat is temporarily disabled for maintenance. Please try again later."}


def ensure_chat_available(db: Session):
    state = chat_maintenance_state(db)
    if state["enabled"]:
        raise HTTPException(status_code=503, detail={
            "code": "CHAT_MAINTENANCE", "message": state["notice"], "until": state["until"]
        })


@app.get("/status/chat")
def public_chat_status(db: Session = Depends(db_session)):
    return chat_maintenance_state(db)


@app.put("/master/settings/chat-maintenance")
def set_chat_maintenance(data: ChatMaintenanceInput,
                         user: User = Depends(require_roles("owner")),
                         db: Session = Depends(db_session)):
    until = (utcnow() + timedelta(minutes=data.duration_minutes)).isoformat() if data.enabled else None
    state = {"enabled": data.enabled, "until": until, "notice": data.notice.strip()}
    row = db.get(PlatformSetting, "chat_maintenance")
    if row:
        row.value = __import__("json").dumps(state)
    else:
        db.add(PlatformSetting(key="chat_maintenance", value=__import__("json").dumps(state)))
    audit(db, user, "chat_maintenance_changed", "platform", 0,
          f"enabled={data.enabled}; until={until}")
    db.commit()
    return state


@app.put("/admin/settings/chat-maintenance")
def admin_set_chat_maintenance(data: ChatMaintenanceInput,
                               user: User = Depends(require_roles("admin")),
                               db: Session = Depends(db_session)):
    until = (utcnow() + timedelta(minutes=data.duration_minutes)).isoformat() if data.enabled else None
    state = {"enabled": data.enabled, "until": until, "notice": data.notice.strip()}
    row = db.get(PlatformSetting, "chat_maintenance")
    if row:
        row.value = __import__("json").dumps(state)
    else:
        db.add(PlatformSetting(key="chat_maintenance", value=__import__("json").dumps(state)))
    audit(db, user, "chat_maintenance_changed", "platform", 0,
          f"enabled={data.enabled}; until={until}")
    db.commit()
    return state


# ---------------------------------------------------------------------------
# Inbox and notifications
# ---------------------------------------------------------------------------
@app.post("/messages", status_code=201)
def send_message(data: MessageInput, user: User = Depends(get_current_user), db: Session = Depends(db_session)):
    ensure_chat_available(db)
    ensure_can_post(user)
    if data.recipient_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot message yourself")
    recipient = db.get(User, data.recipient_id)
    if not recipient or recipient.status == "banned":
        raise HTTPException(status_code=404, detail="Recipient not found")
    blocked = db.scalar(select(UserBlock).where(
        or_(
            (UserBlock.blocker_id == user.id) & (UserBlock.blocked_id == recipient.id),
            (UserBlock.blocker_id == recipient.id) & (UserBlock.blocked_id == user.id),
        )
    ))
    if blocked:
        raise HTTPException(status_code=403, detail="Messaging is unavailable between these accounts")
    message = Message(sender_id=user.id, recipient_id=recipient.id, body=data.body.strip())
    db.add(message)
    notify(db, recipient.id, "message", f"New message from {user.alias}")
    db.commit()
    db.refresh(message)
    return {"id": message.id, "sender_id": user.id, "recipient_id": recipient.id,
            "body": message.body, "created_at": message.created_at}


@app.get("/messages/{other_user_id}")
def conversation(
    other_user_id: int, limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user), db: Session = Depends(db_session),
):
    ensure_chat_available(db)
    rows = db.scalars(
        select(Message).where(
            or_(
                (Message.sender_id == user.id) & (Message.recipient_id == other_user_id),
                (Message.sender_id == other_user_id) & (Message.recipient_id == user.id),
            )
        ).order_by(desc(Message.created_at)).limit(limit)
    ).all()
    for message in rows:
        if message.recipient_id == user.id and message.read_at is None:
            message.read_at = utcnow()
    db.commit()
    return [{"id": m.id, "sender_id": m.sender_id, "recipient_id": m.recipient_id,
             "body": m.body, "read_at": m.read_at, "created_at": m.created_at}
            for m in reversed(rows)]


@app.get("/notifications")
def notifications(
    unread_only: bool = False, limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user), db: Session = Depends(db_session),
):
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read.is_(False))
    rows = db.scalars(stmt.order_by(desc(Notification.created_at)).limit(limit)).all()
    return [{"id": n.id, "kind": n.kind, "message": n.message,
             "read": n.read, "created_at": n.created_at} for n in rows]


@app.post("/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: int, user: User = Depends(get_current_user), db: Session = Depends(db_session)
):
    item = db.get(Notification, notification_id)
    if not item or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    item.read = True
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# XP and account status
# ---------------------------------------------------------------------------
@app.get("/bgmi/news")
def bgmi_news(
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(db_session),
):
    """Public BGMI updates/news. Only staff can publish through the staff endpoint."""
    rows = db.scalars(
        select(BGMINews).where(BGMINews.status == "published")
        .order_by(desc(BGMINews.created_at)).offset(offset).limit(limit)
    ).all()
    return [{
        "id": item.id, "title": item.title, "body": item.body, "tag": item.tag,
        "source_url": item.source_url, "author_id": item.author_id,
        "author_alias": db.get(User, item.author_id).alias if db.get(User, item.author_id) else "LAPRO Staff",
        "created_at": item.created_at,
    } for item in rows]


@app.post("/staff/bgmi/news", status_code=201)
def publish_bgmi_news(
    data: BGMINewsInput,
    user: User = Depends(require_roles("owner", "admin", "manager", "supervisor")),
    db: Session = Depends(db_session),
):
    source = data.source_url.strip() if data.source_url else None
    if source and not re.match(r"^https://", source, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Source URL must use HTTPS")
    item = BGMINews(
        author_id=user.id, title=data.title.strip(), body=data.body.strip(),
        tag=data.tag.strip() or "News", source_url=source
    )
    db.add(item)
    db.flush()
    audit(db, user, "bgmi_news_published", "bgmi_news", item.id, item.title)
    db.commit()
    db.refresh(item)
    return {
        "id": item.id, "title": item.title, "body": item.body, "tag": item.tag,
        "source_url": item.source_url, "author_id": user.id,
        "author_alias": user.alias, "created_at": item.created_at,
    }


@app.delete("/staff/bgmi/news/{news_id}")
def remove_bgmi_news(
    news_id: int,
    user: User = Depends(require_roles("owner", "admin", "manager", "supervisor")),
    db: Session = Depends(db_session),
):
    item = db.get(BGMINews, news_id)
    if not item:
        raise HTTPException(status_code=404, detail="BGMI news item not found")
    item.status = "removed"
    audit(db, user, "bgmi_news_removed", "bgmi_news", item.id, item.title)
    db.commit()
    return {"ok": True, "id": item.id}


@app.get("/xp/tiers")
def xp_tiers():
    return [
        {"name": "Purple Glow", "min_xp": 0, "max_xp": 49},
        {"name": "Blue-Purple Glow", "min_xp": 50, "max_xp": 99},
        {"name": "Red Glow", "min_xp": 100, "max_xp": 498},
        {"name": "Fire Blaze", "min_xp": 499, "max_xp": 499},
        {"name": "Green Glowers", "min_xp": 500, "max_xp": 999},
        {"name": "Golden Extreme", "min_xp": 1000, "max_xp": None},
    ]


@app.get("/xp/me")
def my_xp(user: User = Depends(get_current_user), db: Session = Depends(db_session)):
    events = db.scalars(select(XPEvent).where(XPEvent.user_id == user.id)
                        .order_by(desc(XPEvent.created_at)).limit(100)).all()
    return {"xp": user.xp, "answer_count": user.answer_count,
            "recent_events": [{"points": e.points, "reason": e.reason, "created_at": e.created_at}
                              for e in events]}


@app.get("/users")
def search_users(
    q: str = Query(min_length=2, max_length=30),
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(get_current_user), db: Session = Depends(db_session),
):
    rows = db.scalars(select(User).where(
        User.status == "active", func.lower(User.alias).like(f"%{q.lower()}%")
    ).limit(limit)).all()
    return [{"id": x.id, "alias": x.alias, "xp": x.xp} for x in rows]
