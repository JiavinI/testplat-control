"""日志硬约束回归：Engine 异常里的秘密不得出现在 Control 的任何日志中。

规则（与 ``execution_service`` 模块文档一致）：不得使用 ``logger.exception`` / ``exc_info``，
不得记录 ``EngineError.log_reason``、``__cause__`` 或异常原文，只记 kind、stage、
运行/记录 ID 与异常类型名。

做法：向 Engine 异常的 ``log_reason`` 与 ``__cause__`` 链里注入 password / token / Cookie /
``secret-internal-detail``，再用 caplog 取出**所有** logger 的所有 record，逐条检查
message、args、exc_text、完整 format 输出以及 ``format_exception(exc_info)``。
覆盖 timeout / transport / internal 三类，并分别走 Fake（只测 Control）与真实 Engine
（注入会抛带秘密异常的 HTTP client，连同 Engine 自身的日志点一起验证）。
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import testplat_engine as eng
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from testplat_engine import (
    AssetNotFoundError,
    EngineError,
    EngineInternalError,
    EngineTimeoutError,
    EngineTransportError,
    EngineUnavailableError,
    InvalidAssetError,
    InvalidEnvironmentError,
    InvalidInputError,
    SingleApiEngine,
)
from testplat_engine.ports.http_client import HttpClient, HttpResponse

from testplat_control.adapters.fake_engine import FakeEngineAdapter, build_partial_outcome
from testplat_control.adapters.package_engine import PackageEngineAdapter
from testplat_control.database.models import ExecutionRecord
from testplat_control.database.session import SessionLocal
from testplat_control.deps import get_engine_port
from testplat_control.engine_bootstrap import EngineBootstrapError
from testplat_control.main import app
from tests.case_support import create_project, write_assets, write_env

PASSWORD = "pw-LOGLEAK-password-9f3a"
TOKEN = "tok-LOGLEAK-token-71bc"
COOKIE = "sid-LOGLEAK-cookie-55de"
INTERNAL = "secret-internal-detail"
LEAKY = f"password={PASSWORD} token={TOKEN} Cookie: session={COOKIE} {INTERNAL}"
SECRETS = (PASSWORD, TOKEN, COOKIE, INTERNAL)

CASE_ID = "case.demo.create_then_get"
client = TestClient(app)


def assert_logs_clean(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """逐 record、逐字段检查：不含秘密、没有 exc_info / traceback。返回 records 供正向断言。"""
    assert caplog.records, "没有捕获到任何日志，测试将失去意义"
    formatter = logging.Formatter("%(levelname)s %(name)s %(message)s")
    for record in caplog.records:
        assert record.exc_info is None, f"不得使用 exc_info/logger.exception: {record!r}"
        assert not record.stack_info
        fields = [
            record.getMessage(),
            str(record.msg),
            repr(record.args),
            record.exc_text or "",
            formatter.format(record),
        ]
        if record.exc_info:  # 防御：即使将来有人加了 exc_info，也能在这里发现 traceback 泄漏
            fields.append("".join(traceback.format_exception(*record.exc_info)))
        for secret in SECRETS:
            for text in fields:
                assert secret not in text, f"日志泄漏 {secret!r}: {text!r}"
    for secret in SECRETS:
        assert secret not in caplog.text
    return list(caplog.records)


def leaky(error: EngineError) -> EngineError:
    """给异常对象挂上带秘密的 log_reason 之外的痕迹：__cause__ 链与 __context__。"""
    error.__cause__ = RuntimeError(f"cause: {LEAKY}")
    error.__cause__.__cause__ = ValueError(f"root cause: {LEAKY}")
    return error


def leaky_system_error(kind: str, case_id: str | None) -> EngineError:
    """构造 timeout / transport / internal(execution) 异常；Case 请求带 partial_outcome。"""
    partial = build_partial_outcome(case_id, kind) if case_id else None
    if kind == "timeout":
        return leaky(EngineTimeoutError(log_reason=LEAKY, partial_outcome=partial))
    if kind == "transport":
        return leaky(EngineTransportError(log_reason=LEAKY, partial_outcome=partial))
    return leaky(EngineInternalError("execution", log_reason=LEAKY, partial_outcome=partial))


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    assets, config = tmp_path / "assets", tmp_path / "config"
    write_assets(assets)
    (assets / "api" / "common").mkdir(parents=True)
    (assets / "api" / "common" / "health.yaml").write_text(
        "id: api.common.health\nname: h\nhost: local\nmethod: GET\nurl: /health\n"
        "success:\n  status_code: 200\n",
        encoding="utf-8",
    )
    write_env(config, "http://127.0.0.1:9")
    return assets, config


@pytest.fixture
def project_id(dirs: tuple[Path, Path]) -> Iterator[str]:
    yield create_project(client, *dirs)
    app.dependency_overrides.pop(get_engine_port, None)


def _use(engine: Any) -> None:
    app.dependency_overrides[get_engine_port] = lambda: engine


def _run_case(pid: str):
    return client.post(f"/projects/{pid}/cases/{CASE_ID}/run", json={"params": {}})


def _run_api(pid: str):
    return client.post(f"/projects/{pid}/assets/api.common.health/run", json={"params": {}})


EXPECTED_HTTP = {"timeout": 504, "transport": 502, "internal": 500}


# ------------------------------------------------------------ Fake：只验证 Control 的日志点


@pytest.mark.parametrize("kind", ["timeout", "transport", "internal"])
def test_case_execution_errors_do_not_log_secrets(
    project_id: str, caplog: pytest.LogCaptureFixture, kind: str
) -> None:
    caplog.set_level(logging.DEBUG)
    _use(FakeEngineAdapter(system_error=leaky_system_error(kind, CASE_ID)))

    response = _run_case(project_id)

    assert response.status_code == EXPECTED_HTTP[kind]
    records = assert_logs_clean(caplog)
    # 正向断言：确实记录了安全字段（kind/stage/类型名），而不是什么都没记。
    text = "\n".join(r.getMessage() for r in records)
    assert f"kind={kind}" in text and "stage=execution" in text
    assert "cause_type=RuntimeError" in text
    for secret in SECRETS:
        assert secret not in response.text


@pytest.mark.parametrize("kind", ["timeout", "transport", "internal"])
def test_api_execution_errors_do_not_log_secrets(
    project_id: str, caplog: pytest.LogCaptureFixture, kind: str
) -> None:
    """同一日志点也服务单 API；Phase 2.5 路径同样不得泄漏。"""
    caplog.set_level(logging.DEBUG)
    _use(FakeEngineAdapter(system_error=leaky_system_error(kind, None)))

    response = _run_api(project_id)

    assert response.status_code == EXPECTED_HTTP[kind]
    assert_logs_clean(caplog)
    saved = SessionLocal().query(ExecutionRecord).filter_by(project_id=project_id).all()
    assert saved and all(s not in (r.result_json or "") for r in saved for s in SECRETS)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: AssetNotFoundError(log_reason=LEAKY),
        lambda: InvalidAssetError(log_reason=LEAKY),
        lambda: InvalidInputError(log_reason=LEAKY),
        lambda: InvalidEnvironmentError(log_reason=LEAKY),
        lambda: EngineInternalError("preflight", log_reason=LEAKY),
    ],
    ids=["asset_not_found", "invalid_asset", "invalid_input", "invalid_environment", "internal"],
)
def test_case_preflight_errors_do_not_log_secrets(
    project_id: str, caplog: pytest.LogCaptureFixture, factory: Callable[[], EngineError]
) -> None:
    caplog.set_level(logging.DEBUG)
    _use(FakeEngineAdapter(system_error=leaky(factory())))

    response = _run_case(project_id)

    assert response.status_code in (404, 422, 500)
    assert "stage=preflight" in "\n".join(r.getMessage() for r in assert_logs_clean(caplog))


def test_unclassified_exception_logs_only_type_name(
    project_id: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    _use(FakeEngineAdapter(system_error=RuntimeError(LEAKY)))  # type: ignore[arg-type]

    for response in (_run_case(project_id), _run_api(project_id)):
        assert response.status_code == 500
        assert all(s not in response.text for s in SECRETS)

    text = "\n".join(r.getMessage() for r in assert_logs_clean(caplog))
    assert "exc_type=RuntimeError" in text


def test_persistence_failure_does_not_log_sql_parameters(
    project_id: str, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """落库失败：SQLAlchemy 异常文本含 SQL 参数（result_json），不得进日志。"""
    caplog.set_level(logging.DEBUG)
    _use(FakeEngineAdapter())

    def _boom(self: Any) -> None:
        raise OperationalError(
            "INSERT INTO execution_records", {"result_json": LEAKY}, Exception(LEAKY)
        )

    monkeypatch.setattr("sqlalchemy.orm.Session.commit", _boom)

    response = _run_case(project_id)

    assert response.status_code == 500
    assert response.json() == {"detail": "Failed to persist execution record"}
    text = "\n".join(r.getMessage() for r in assert_logs_clean(caplog))
    assert "exc_type=OperationalError" in text


def test_environment_errors_do_not_log_secrets(
    dirs: tuple[Path, Path], caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """环境加载：YAML 异常原文含出错行片段、OSError 文本含路径与内容，均不得进日志。"""
    caplog.set_level(logging.DEBUG)
    assets, config = dirs
    _use(FakeEngineAdapter())
    bad = config / "envs" / "broken.yaml"
    bad.write_text(f"password: [{LEAKY}\n", encoding="utf-8")
    pid = create_project(client, assets, config, env="broken")

    assert _run_case(pid).status_code == 422

    def _unreadable(self: Path, *args: Any, **kwargs: Any) -> str:
        raise PermissionError(LEAKY)

    monkeypatch.setattr(Path, "read_text", _unreadable)
    pid2 = create_project(client, assets, config, env="test")
    assert _run_case(pid2).status_code == 422
    text = "\n".join(r.getMessage() for r in assert_logs_clean(caplog))
    assert "exc_type=PermissionError" in text


def test_corrupt_result_json_does_not_log_stored_content(
    project_id: str, caplog: pytest.LogCaptureFixture
) -> None:
    """类型化历史详情解析失败时，只记记录 ID 与异常类型名，不回显存档内容。"""
    caplog.set_level(logging.DEBUG)
    now = datetime.now(UTC)
    db = SessionLocal()
    db.add(
        ExecutionRecord(
            id=f"{project_id[:8]}-corrupt",
            project_id=project_id,
            asset_type="case",
            asset_id=CASE_ID,
            status="failed",
            start_time=now,
            end_time=now,
            duration=0.0,
            result_json=f'{{"case_id": "{LEAKY}", "steps": "oops"}}',
        )
    )
    db.commit()
    db.close()

    response = client.get(f"/projects/{project_id}/case-execution-records/{project_id[:8]}-corrupt")

    assert response.status_code == 200 and response.json()["result"] is None
    text = "\n".join(r.getMessage() for r in assert_logs_clean(caplog))
    assert "ValidationError" in text


def test_startup_diagnostics_do_not_log_engine_exception_text(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """启动期 create_engine 失败：诊断信息与日志只含异常类型名，不含构造异常原文。"""
    caplog.set_level(logging.DEBUG)

    def _bad_factory() -> Any:
        raise RuntimeError(LEAKY)

    monkeypatch.setattr(eng, "create_engine", _bad_factory)

    with pytest.raises(EngineBootstrapError) as info:
        with TestClient(app):
            pass

    assert all(s not in str(info.value) for s in SECRETS)
    assert "RuntimeError" in str(info.value)
    assert_logs_clean(caplog)


def test_package_adapter_unavailable_reason_has_no_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_engine 构造失败转成 EngineUnavailableError：log_reason 只保留类型名。"""

    def _bad_factory() -> Any:
        raise RuntimeError(LEAKY)

    monkeypatch.setattr(eng, "create_engine", _bad_factory)

    with pytest.raises(EngineUnavailableError) as info:
        PackageEngineAdapter()
    assert info.value.log_reason is not None
    assert all(s not in info.value.log_reason for s in SECRETS)


# --------------------------------------------- 真实 Engine：连同 Engine 日志点一起验证


class _LeakyClient(HttpClient):
    """总是抛出带秘密文本的异常的 HTTP 客户端（不访问网络）。"""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def request(self, method: str, url: str, **kwargs: Any) -> HttpResponse:
        raise self._exc


_REAL_FAILURES: list[tuple[str, Callable[[], Exception]]] = [
    ("timeout", lambda: httpx.ReadTimeout(LEAKY)),
    ("transport", lambda: httpx.ConnectError(LEAKY)),
    ("internal", lambda: RuntimeError(LEAKY)),
]


@pytest.mark.parametrize(("kind", "make_exc"), _REAL_FAILURES, ids=[k for k, _ in _REAL_FAILURES])
def test_real_engine_case_failures_do_not_log_secrets(
    project_id: str,
    caplog: pytest.LogCaptureFixture,
    kind: str,
    make_exc: Callable[[], Exception],
) -> None:
    caplog.set_level(logging.DEBUG)
    _use(PackageEngineAdapter(delegate=SingleApiEngine(http_client=_LeakyClient(make_exc()))))

    response = _run_case(project_id)

    assert response.status_code == EXPECTED_HTTP[kind]
    assert all(s not in response.text for s in SECRETS)
    records = assert_logs_clean(caplog)
    names = {r.name for r in records}
    assert any(n.startswith("testplat_engine") for n in names), "应覆盖 Engine 自身日志点"
    assert any(n.startswith("testplat_control") for n in names)

    (row,) = (
        SessionLocal()
        .query(ExecutionRecord)
        .filter_by(project_id=project_id, asset_type="case")
        .all()
    )
    assert row.status == "failed"
    assert all(s not in (row.result_json or "") for s in SECRETS)


@pytest.mark.parametrize(("kind", "make_exc"), _REAL_FAILURES, ids=[k for k, _ in _REAL_FAILURES])
def test_real_engine_api_failures_do_not_log_secrets(
    project_id: str,
    caplog: pytest.LogCaptureFixture,
    kind: str,
    make_exc: Callable[[], Exception],
) -> None:
    caplog.set_level(logging.DEBUG)
    _use(PackageEngineAdapter(delegate=SingleApiEngine(http_client=_LeakyClient(make_exc()))))

    response = _run_api(project_id)

    assert response.status_code == EXPECTED_HTTP[kind]
    assert_logs_clean(caplog)
