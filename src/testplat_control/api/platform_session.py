"""平台注册、登录、注销与当前操作人。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from testplat_control.database.session import get_db
from testplat_control.services.platform_auth import (
    PlatformPrincipal,
    assert_same_origin,
    authenticate,
    clear_session_cookie,
    issue_session,
    principal_from_request,
    register_user,
    revoke_current_session,
    set_session_cookie,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthBody(BaseModel):
    username: str = Field(..., description="平台用户名")
    password: str = Field(..., description="平台密码；只用于本次校验，响应不回显")


class MeResponse(BaseModel):
    username: str = Field(..., description="当前操作人")


def require_user(request: Request, db: Session = Depends(get_db)) -> PlatformPrincipal:
    """配置与执行接口的会话依赖。未登录 401。会话不进入 Engine。"""
    assert_same_origin(request)
    principal = principal_from_request(db, request)
    if principal is None:
        raise HTTPException(status_code=401, detail="未登录")
    return principal


def _login_response(principal: PlatformPrincipal, token: str, request: Request) -> Response:
    response = Response(
        content=MeResponse(username=principal.username).model_dump_json(),
        media_type="application/json",
        status_code=200,
    )
    set_session_cookie(response, request, token)
    return response


@router.post("/register", response_model=MeResponse)
async def register(
    body: AuthBody,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """注册并建立会话。所有登录用户能力相同。"""
    assert_same_origin(request)
    principal = register_user(db, body.username, body.password)
    token = issue_session(db, principal)
    return _login_response(principal, token, request)


@router.post("/login", response_model=MeResponse)
async def login(
    body: AuthBody,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """登录。失败文案不区分用户是否存在。"""
    assert_same_origin(request)
    principal = authenticate(db, body.username, body.password)
    token = issue_session(db, principal)
    return _login_response(principal, token, request)


@router.post("/logout")
async def logout(
    request: Request,
    db: Session = Depends(get_db),
    user: PlatformPrincipal = Depends(require_user),
) -> Response:
    """注销当前会话。"""
    del user
    revoke_current_session(db, request)
    response = Response(status_code=204)
    clear_session_cookie(response)
    return response


@router.get("/me", response_model=MeResponse)
async def me(user: PlatformPrincipal = Depends(require_user)) -> MeResponse:
    """当前操作人。不返回密码哈希。"""
    return MeResponse(username=user.username)
