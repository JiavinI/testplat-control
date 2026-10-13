"""测试与显式验收 harness 用的 Fake Engine。

仅通过 DI / dependency_overrides 注入；默认 provider 不会选择本实现。

Fake 与真实 Engine 共用**同一份公开 DTO**：Case 结果直接构造 Engine 0.4 的
``CaseExecutionOutcome`` / ``StepOutcome``（它们在构造期强制步骤顺序、计数、
fail-fast 与脱敏不变量），而不是 Control 自己拼 dict。因此 Fake 的输出形状不可能
与真实 Engine 漂移；``tests/test_case_contract.py`` 用同一套断言校验两者。

鉴权（Phase 3.3b）：Fake 不解析资产 YAML，因此用“请求里的 ``default_identity``，
或构造参数 ``auth_identity`` 指定的身份”模拟资产声明。被选中身份为 ``UnavailableAuth`` /
不存在 → 与真实 Engine 一样抛 preflight ``InvalidEnvironmentError``；为
``StaticHeaderAuth`` / ``LoginAuth`` → 结果与每个非 skipped 步骤带公开七键 ``auth``，
请求快照里凭证头值为 ``***``。``login_failed`` 模式供前端门禁。
Fake **从不**调用 ``SecretStr.reveal()``：它不需要秘密值就能产生同形结果。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import overload

from testplat_engine import (
    ApiExecutionOutcome,
    ApiExecutionRequest,
    AuthTable,
    CaseExecutionOutcome,
    CaseExecutionRequest,
    EngineError,
    InvalidEnvironmentError,
    LoginAuth,
    StaticHeaderAuth,
    StepOutcome,
    UnavailableAuth,
)
from testplat_engine.interface import JsonObject

DEFAULT_CASE_STEPS: tuple[str, ...] = ("create", "get")


def _public_auth_static(
    name: str,
    header_names: Sequence[str],
    overridden: Sequence[str] = (),
) -> JsonObject:
    """静态 header 身份的公开七键 auth（tier/cookie_names/login_ref 固定）。"""
    return {
        "identity": name,
        "kind": "static_headers",
        "tier": None,
        "header_names": list(header_names),
        "overridden_headers": list(overridden),
        "cookie_names": [],
        "login_ref": None,
    }


def _public_auth_login(
    name: str,
    material: LoginAuth,
    *,
    overridden: Sequence[str] = (),
    login_ref: int = 0,
    cookie_names: Sequence[str] | None = None,
) -> JsonObject:
    """login 身份的公开七键 auth。"""
    cookies = (
        list(cookie_names)
        if cookie_names is not None
        else (["session"] if material.session_cookie else [])
    )
    return {
        "identity": name,
        "kind": "login",
        "tier": material.tier,
        "header_names": list(material.header_names),
        "overridden_headers": list(overridden),
        "cookie_names": cookies,
        "login_ref": login_ref,
    }


def _masked_headers(auth: JsonObject | None) -> dict[str, str]:
    """与真实 Engine 公开面一致：注入的凭证头只露名字，值恒为 ``***``。"""
    if auth is None:
        return {}
    return {name: "***" for name in auth["header_names"]}  # type: ignore[union-attr]


def _ok_step(
    step_id: str,
    *,
    duration: float = 0.01,
    output: str | None = None,
    auth: JsonObject | None = None,
) -> StepOutcome:
    """构造一个 success 步骤（含 Engine 同形的 request/response 快照）。"""
    return StepOutcome(
        step_id=step_id,
        type="api",
        status="success",
        duration_seconds=duration,
        name=f"步骤 {step_id}",
        request={
            "method": "GET",
            "url": f"http://127.0.0.1/fake/{step_id}",
            "headers": _masked_headers(auth),
            "body": None,
            "body_type": "json",
        },
        response={"status_code": 200, "headers": {}, "body": {"id": f"{step_id}-1"}},
        output=output,
        auth=auth,
    )


def _skipped_steps(step_ids: Sequence[str], *, reason: str = "fail_fast") -> list[StepOutcome]:
    return [
        StepOutcome(
            step_id=step_id,
            type="api",
            status="skipped",
            duration_seconds=0.0,
            name=f"步骤 {step_id}",
            skip_reason=reason,
        )
        for step_id in step_ids
    ]


def build_case_outcome(
    case_id: str,
    step_ids: Sequence[str] = DEFAULT_CASE_STEPS,
    *,
    fail_at: str | None = None,
    fail_kind: str = "assertion",
    auth: JsonObject | None = None,
    logins: Sequence[JsonObject] = (),
    skip_reason: str = "fail_fast",
) -> CaseExecutionOutcome:
    """构造确定性的 Case 业务结果：全部成功，或在 ``fail_at`` 步业务失败（其后 skipped）。

    ``auth`` 为每个发出请求的步骤的公开身份；skipped 恒为 null（与 Engine 一致），
    但 ``login_failed`` 失败步骤可带 ``auth.login_ref``（A6）。
    """
    steps: list[StepOutcome] = []
    ids = list(step_ids)
    for index, step_id in enumerate(ids):
        if step_id == fail_at:
            if fail_kind == "login_failed":
                error = {
                    "kind": "login_failed",
                    "message": "登录失败",
                    "login": {
                        "identity": None if auth is None else auth.get("identity"),
                        "strategy": "generic_flow",
                        "failed_step": "login",
                        "reason": "assertion",
                    },
                }
                failed = StepOutcome(
                    step_id=step_id,
                    type="api",
                    status="failed",
                    duration_seconds=0.01,
                    name=f"步骤 {step_id}",
                    # A6：login_failed 步骤 request/response 为 null
                    request=None,
                    response=None,
                    error=error,
                    auth=auth,
                )
                steps.append(failed)
                steps.extend(_skipped_steps(ids[index + 1 :], reason="login_failed"))
                break
            error = (
                {
                    "kind": "variable_resolution",
                    "message": f"步骤 {step_id} 的变量无法解析",
                    "step_id": step_id,
                    "path": "created.body.missing",
                }
                if fail_kind == "variable_resolution"
                else {"kind": "assertion", "message": "断言失败: 响应不符合成功条件"}
            )
            failed = StepOutcome(
                step_id=step_id,
                type="api",
                status="failed",
                duration_seconds=0.01,
                name=f"步骤 {step_id}",
                request=None
                if fail_kind == "variable_resolution"
                else {
                    "method": "GET",
                    "url": f"http://127.0.0.1/fake/{step_id}",
                    "headers": _masked_headers(auth),
                    "body": None,
                    "body_type": "json",
                },
                response=None
                if fail_kind == "variable_resolution"
                else {"status_code": 200, "headers": {}, "body": {"status": "bad"}},
                error=error,
                auth=None if fail_kind == "variable_resolution" else auth,
            )
            steps.append(failed)
            steps.extend(_skipped_steps(ids[index + 1 :], reason=skip_reason))
            break
        steps.append(_ok_step(step_id, output="created" if index == 0 else None, auth=auth))
    status = "failed" if fail_at in ids else "success"
    return CaseExecutionOutcome(
        case_id=case_id,
        status=status,  # type: ignore[arg-type]
        duration_seconds=0.02,
        steps=tuple(steps),
        logins=list(logins),
    )


def build_partial_outcome(
    case_id: str,
    kind: str,
    step_ids: Sequence[str] = DEFAULT_CASE_STEPS,
    *,
    fail_at: str | None = None,
) -> CaseExecutionOutcome:
    """构造满足 Engine 不变量的 ``partial_outcome``：前序 success、当前 failed、其后 skipped。"""
    ids = list(step_ids)
    current = fail_at or ids[len(ids) // 2]
    index = ids.index(current)
    steps = [_ok_step(step_id) for step_id in ids[:index]]
    messages = {
        "timeout": "API 请求超时",
        "transport": "API 传输失败",
        "internal": "执行引擎内部错误",
    }
    steps.append(
        StepOutcome(
            step_id=current,
            type="api",
            status="failed",
            duration_seconds=0.01,
            name=f"步骤 {current}",
            error={"kind": kind, "stage": "execution", "message": messages[kind]},
        )
    )
    steps.extend(_skipped_steps(ids[index + 1 :]))
    return CaseExecutionOutcome(
        case_id=case_id,
        status="failed",
        duration_seconds=0.03,
        steps=tuple(steps),
        logins=[],
    )


def _fake_login_record(
    identity: str, material: LoginAuth, *, status: str = "success"
) -> JsonObject:
    """构造已脱敏的假登录记录（供前端门禁）。"""
    return {
        "identity": identity,
        "strategy": material.strategy,
        "tier": material.tier,
        "status": status,
        "duration_seconds": 0.01,
        "steps": [
            {
                "name": "login",
                "request": {
                    "method": "POST",
                    "url": "http://127.0.0.1/fake/login",
                    "headers": {},
                    "body": {"username": "buyer", "password": "***"},
                    "body_type": "json",
                },
                "response": {
                    "status_code": 200 if status == "success" else 401,
                    "headers": {},
                    "body": {"token": "***"} if status == "success" else {"error": "bad"},
                },
            }
        ],
        "probe": None,
        "error": None if status == "success" else {"reason": "assertion", "failed_step": "login"},
    }


class FakeEngineAdapter:
    """确定性 EnginePort 替身。

    - 默认返回 success。
    - ``fail_passwords`` 中的 password 触发单 API 业务 failed。
    - ``system_error`` 非空时对 API 与 Case 请求都直接抛出该系统异常（错误映射单测）。
    - Case 请求：``case_step_ids`` 决定步骤；``case_fail_at`` 非空时在该步业务失败
      （``case_fail_kind`` 选 assertion / variable_resolution / login_failed），其后 skipped。
    - ``case_outcome`` 非空时 Case 请求原样返回该 outcome（用于精确构造场景）。
    - ``api_fail_kind="login_failed"`` 时单 API 返回 login_failed 形状。
    """

    def __init__(
        self,
        *,
        fail_passwords: frozenset[str] | None = None,
        system_error: EngineError | None = None,
        delay: float = 0.0,
        case_step_ids: Sequence[str] = DEFAULT_CASE_STEPS,
        case_fail_at: str | None = None,
        case_fail_kind: str = "assertion",
        case_outcome: CaseExecutionOutcome | None = None,
        auth_identity: str | None = None,
        auth_overridden_headers: Sequence[str] = (),
        api_fail_kind: str | None = None,
    ) -> None:
        self.fail_passwords = fail_passwords or frozenset({"wrong-password"})
        self.system_error = system_error
        self.delay = delay
        self.case_step_ids = tuple(case_step_ids)
        self.case_fail_at = case_fail_at
        self.case_fail_kind = case_fail_kind
        self.case_outcome = case_outcome
        self.auth_identity = auth_identity
        self.auth_overridden_headers = tuple(auth_overridden_headers)
        self.api_fail_kind = api_fail_kind
        self.calls: list[ApiExecutionRequest | CaseExecutionRequest] = []

    @overload
    async def execute(self, request: ApiExecutionRequest) -> ApiExecutionOutcome: ...

    @overload
    async def execute(self, request: CaseExecutionRequest) -> CaseExecutionOutcome: ...

    async def execute(
        self, request: ApiExecutionRequest | CaseExecutionRequest
    ) -> ApiExecutionOutcome | CaseExecutionOutcome:
        """按配置返回业务结果或抛出系统错误；按请求类型判别 API / Case。"""
        import asyncio

        self.calls.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.system_error is not None:
            raise self.system_error
        auth, logins = self._resolve_auth(request.auth)

        if isinstance(request, CaseExecutionRequest):
            if self.case_outcome is not None:
                return self.case_outcome
            return build_case_outcome(
                request.case_id,
                self.case_step_ids,
                fail_at=self.case_fail_at,
                fail_kind=self.case_fail_kind,
                auth=auth,
                logins=logins,
            )

        if self.api_fail_kind == "login_failed":
            return ApiExecutionOutcome(
                status="failed",
                request=None,
                response=None,
                error={
                    "kind": "login_failed",
                    "message": "登录失败",
                    "login": {
                        "identity": None if auth is None else auth.get("identity"),
                        "strategy": "generic_flow",
                        "failed_step": "login",
                        "reason": "assertion",
                    },
                },
                auth=auth,
                logins=logins,
            )

        password = request.params.get("password")
        failed = isinstance(password, str) and password in self.fail_passwords
        if failed:
            return ApiExecutionOutcome(
                status="failed",
                request={
                    "api_id": request.api_id,
                    "params": dict(request.params),
                    "body_type": "json",
                },
                response=None,
                error={"kind": "assertion", "message": "assertion failed"},
                auth=auth,
                logins=logins,
            )
        return ApiExecutionOutcome(
            status="success",
            request={
                "api_id": request.api_id,
                "params": dict(request.params),
                "body_type": "json",
                **({"headers": _masked_headers(auth)} if auth is not None else {}),
            },
            response={"status_code": 200, "body": {"ok": True}},
            error=None,
            auth=auth,
            logins=logins,
        )

    def _resolve_auth(self, table: AuthTable | None) -> tuple[JsonObject | None, list[JsonObject]]:
        """模拟 Engine 预检的身份解析，返回公开 auth（七键）与 logins。"""
        name = self.auth_identity
        if name is None and table is not None:
            name = table.default_identity
        if name is None:
            return None, []
        material = None if table is None else table.identities.get(name)
        if material is None:
            raise InvalidEnvironmentError(
                public_message=f"身份不存在: {name}", log_reason=f"fake: identity {name} missing"
            )
        if isinstance(material, UnavailableAuth):
            raise InvalidEnvironmentError(
                public_message=f"身份 {name} 不可用: {material.public_reason}",
                log_reason=f"fake: identity {name} unavailable",
            )
        if isinstance(material, StaticHeaderAuth):
            return (
                _public_auth_static(name, material.header_names, self.auth_overridden_headers),
                [],
            )
        if isinstance(material, LoginAuth):
            failed = self.api_fail_kind == "login_failed" or self.case_fail_kind == "login_failed"
            record = _fake_login_record(name, material, status="failed" if failed else "success")
            return (
                _public_auth_login(
                    name, material, overridden=self.auth_overridden_headers, login_ref=0
                ),
                [record],
            )
        raise InvalidEnvironmentError(
            public_message=f"身份 {name} 的凭证类型不受支持",
            log_reason=f"fake: identity {name} unknown kind",
        )
