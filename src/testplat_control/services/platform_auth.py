"""平台用户与会话。

会话 cookie 只放随机 token，库中存其 SHA-256。不进入 Engine AuthTable。
变更请求若带 Origin，必须与当前站点一致；浏览器跨站 POST 会带 Origin。
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, Response
from sqlalchemy.orm import Session

from testplat_control.config import settings
from testplat_control.database.models import PlatformSession, PlatformUser
from testplat_control.services.crypto import hash_password, password_matches

COOKIE_NAME = "testplat_session"
SESSION_TTL = timedelta(days=7)
USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,31}$")
MIN_PASSWORD = 8
MAX_PASSWORD = 128
_AUTH_FAILED = "用户名或密码错误"


@dataclass(frozen=True, slots=True)
class PlatformPrincipal:
    """请求内使用的操作人。不含密码哈希。"""

    id: str
    username: str


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def assert_same_origin(request: Request) -> None:
    """变更接口：带了 Origin 就必须同源。缺省 Origin 留给非浏览器客户端。"""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if not origin:
        return
    expected = str(request.base_url).rstrip("/")
    if origin.rstrip("/") != expected:
        raise HTTPException(status_code=403, detail="Origin 与当前站点不一致")


def validate_username(username: str) -> str:
    if not isinstance(username, str) or not USERNAME_RE.fullmatch(username):
        raise HTTPException(
            status_code=422, detail="用户名需为 3–32 位字母、数字或下划线，且以字母开头"
        )
    return username


def validate_password(password: str) -> str:
    if not isinstance(password, str) or not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        raise HTTPException(status_code=422, detail="密码长度需在 8–128 之间")
    if any(ch in password for ch in "\r\n\x00"):
        raise HTTPException(status_code=422, detail="密码含非法控制字符")
    return password


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def register_user(db: Session, username: str, password: str) -> PlatformPrincipal:
    username = validate_username(username)
    password = validate_password(password)
    exists = db.query(PlatformUser).filter(PlatformUser.username == username).first()
    if exists is not None:
        raise HTTPException(status_code=409, detail="用户名已存在")
    user = PlatformUser(
        id=secrets.token_hex(16),
        username=username,
        password_hash=hash_password(password),
        created_at=_now(),
    )
    db.add(user)
    db.commit()
    return PlatformPrincipal(id=user.id, username=user.username)


def authenticate(db: Session, username: str, password: str) -> PlatformPrincipal:
    """登录。用户不存在与密码错误使用同一文案。"""
    if not isinstance(username, str) or not isinstance(password, str):
        raise HTTPException(status_code=401, detail=_AUTH_FAILED)
    user = db.query(PlatformUser).filter(PlatformUser.username == username).first()
    stored = None if user is None else user.password_hash
    if not password_matches(stored, password) or user is None:
        raise HTTPException(status_code=401, detail=_AUTH_FAILED)
    return PlatformPrincipal(id=user.id, username=user.username)


def issue_session(db: Session, principal: PlatformPrincipal) -> str:
    """创建会话并返回原始 token（只此一次出现，库中不保存）。"""
    token = secrets.token_urlsafe(32)
    row = PlatformSession(
        id=secrets.token_hex(16),
        token_hash=_token_hash(token),
        user_id=principal.id,
        expires_at=_now() + SESSION_TTL,
        created_at=_now(),
        revoked_at=None,
    )
    db.add(row)
    db.commit()
    return token


def principal_from_request(db: Session, request: Request) -> PlatformPrincipal | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    row = db.query(PlatformSession).filter(PlatformSession.token_hash == _token_hash(token)).first()
    if row is None or row.revoked_at is not None or row.expires_at <= _now():
        return None
    user = db.query(PlatformUser).filter(PlatformUser.id == row.user_id).first()
    if user is None:
        return None
    return PlatformPrincipal(id=user.id, username=user.username)


def revoke_current_session(db: Session, request: Request) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return
    row = db.query(PlatformSession).filter(PlatformSession.token_hash == _token_hash(token)).first()
    if row is not None and row.revoked_at is None:
        row.revoked_at = _now()
        db.commit()


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    secure = bool(settings.testplat_cookie_secure) or request.url.scheme == "https"
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/")
