"""Fake 与真实 Engine 使用同一份 DTO 契约。

Fake 直接构造 Engine 0.2 的公开 ``CaseExecutionOutcome`` / ``StepOutcome``，真实 Engine
用注入的脚本化 HTTP client 在进程内运行（不开端口）。这里用**同一组断言**检查两者：
类型相同、序列化键集合相同、都能被 Control 的 ``CaseResult`` schema 无损接收、
都满足顺序/计数/fail-fast 不变量。任何一边漂移，这组测试都会失败。
"""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from testplat_engine import (
    CaseExecutionOutcome,
    CaseExecutionRequest,
    EngineTimeoutError,
    SingleApiEngine,
    StepOutcome,
)
from testplat_engine.ports.http_client import HttpClient, HttpResponse

from testplat_control.adapters.fake_engine import (
    FakeEngineAdapter,
    build_case_outcome,
    build_partial_outcome,
)
from testplat_control.adapters.package_engine import PackageEngineAdapter
from testplat_control.api.case_schemas import CaseResult
from testplat_control.services.execution_service import case_result_payload
from tests.case_support import assert_case_result_invariants, write_assets

ENV = {"api_hosts": {"local": "http://127.0.0.1:9", "dead": "http://127.0.0.1:1"}}


class _ScriptedClient(HttpClient):
    """按路径返回固定响应；/demo/slow 抛超时。不访问网络。"""

    async def request(self, method: str, url: str, **kwargs: Any) -> HttpResponse:
        if url.endswith("/demo/slow"):
            raise httpx.ReadTimeout("scripted timeout")
        if url.endswith("/demo/resources"):
            return HttpResponse(201, {"content-type": "application/json"}, {"id": "res-42"})
        return HttpResponse(200, {"content-type": "application/json"}, {"ok": True})


@pytest.fixture
def assets(tmp_path: Path) -> Path:
    write_assets(tmp_path / "assets")
    return tmp_path / "assets"


def _request(assets: Path, case_id: str, **params: Any) -> CaseExecutionRequest:
    return CaseExecutionRequest(
        case_id=case_id, assets_root=assets, environment=ENV, params=params, timeout_seconds=5
    )


def _real_engine() -> PackageEngineAdapter:
    return PackageEngineAdapter(delegate=SingleApiEngine(http_client=_ScriptedClient()))


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _payload_and_check(outcome: CaseExecutionOutcome, step_ids: list[str]) -> dict[str, Any]:
    """统一检查：JSON 可序列化、被 CaseResult 无损接收、满足不变量。"""
    payload = case_result_payload(outcome)
    json.dumps(payload)  # 必须 JSON 可序列化
    parsed = CaseResult.model_validate(payload)
    assert parsed.model_dump(mode="json")["steps"][0]["step_id"] == step_ids[0]
    assert_case_result_invariants(payload, step_ids)
    return payload


def _shape(payload: dict[str, Any]) -> tuple[set[str], set[str]]:
    return set(payload), set(payload["steps"][0])


def test_fake_and_real_engine_share_the_same_dto_types(assets: Path) -> None:
    fake_outcome = _run(FakeEngineAdapter().execute(_request(assets, "case.demo.create_then_get")))
    real_outcome = _run(_real_engine().execute(_request(assets, "case.demo.create_then_get")))

    for outcome in (fake_outcome, real_outcome):
        assert type(outcome) is CaseExecutionOutcome
        assert all(type(step) is StepOutcome for step in outcome.steps)
    fake_payload = _payload_and_check(fake_outcome, ["create", "get"])
    real_payload = _payload_and_check(real_outcome, ["create", "get"])
    assert _shape(fake_payload) == _shape(real_payload)
    assert [s["status"] for s in real_payload["steps"]] == ["success", "success"]
    # 单步骤内部的键集合也必须一致（含 request/response 子结构）。
    for fake_step, real_step in zip(fake_payload["steps"], real_payload["steps"], strict=True):
        assert set(fake_step) == set(real_step)
        assert set(fake_step["request"]) == set(real_step["request"])
        assert set(fake_step["response"]) == set(real_step["response"])


def test_business_failure_shapes_match(assets: Path) -> None:
    fake = build_case_outcome(
        "case.demo.assert_failed", ("bad_assert", "after"), fail_at="bad_assert"
    )
    real = _run(_real_engine().execute(_request(assets, "case.demo.assert_failed")))

    fake_payload = _payload_and_check(fake, ["bad_assert", "after"])
    real_payload = _payload_and_check(real, ["bad_assert", "after"])
    assert _shape(fake_payload) == _shape(real_payload)
    assert fake_payload["steps"][0]["error"]["kind"] == "assertion"
    assert real_payload["steps"][0]["error"]["kind"] == "assertion"
    fake_statuses = [s["status"] for s in fake_payload["steps"]]
    assert fake_statuses == [s["status"] for s in real_payload["steps"]]
    assert fake_payload["steps"][1]["skip_reason"] == real_payload["steps"][1]["skip_reason"]


def test_variable_resolution_failure_shapes_match(assets: Path) -> None:
    fake = build_case_outcome(
        "case.demo.missing_runtime_path",
        ("create", "consume", "after"),
        fail_at="consume",
        fail_kind="variable_resolution",
    )
    real = _run(_real_engine().execute(_request(assets, "case.demo.missing_runtime_path")))

    for outcome in (fake, real):
        payload = _payload_and_check(outcome, ["create", "consume", "after"])
        consume = payload["steps"][1]
        assert consume["request"] is None and consume["response"] is None
        assert set(consume["error"]) == {"kind", "message", "step_id", "path"}


def test_partial_outcome_shapes_match_for_system_errors(assets: Path) -> None:
    """真实 Engine 抛出的 timeout 与 Fake 构造的 partial_outcome 形状一致、都满足不变量。"""
    with pytest.raises(EngineTimeoutError) as info:
        _run(_real_engine().execute(_request(assets, "case.demo.timeout")))
    real_partial = info.value.partial_outcome
    assert real_partial is not None
    fake_partial = build_partial_outcome(
        "case.demo.timeout", "timeout", ("create", "slow", "after"), fail_at="slow"
    )

    error = {"kind": "timeout", "stage": "execution", "message": info.value.public_message}
    for partial in (real_partial, fake_partial):
        payload = case_result_payload(partial, error=error)
        CaseResult.model_validate(payload)
        assert_case_result_invariants(payload, ["create", "slow", "after"])
        assert [s["status"] for s in payload["steps"]] == ["success", "failed", "skipped"]
        assert payload["steps"][1]["error"]["kind"] == "timeout"
        assert payload["steps"][1]["error"]["stage"] == "execution"
    assert _shape(case_result_payload(real_partial)) == _shape(case_result_payload(fake_partial))


def test_both_adapters_expose_the_single_async_execute_seam() -> None:
    """唯一跨仓入口：Fake 与 PackageEngineAdapter 都只有 async execute(request)。"""
    for adapter in (FakeEngineAdapter(), _real_engine()):
        assert inspect.iscoroutinefunction(adapter.execute)
        assert list(inspect.signature(adapter.execute).parameters) == ["request"]
