"""Case 资产详情、运行与历史详情路由（两段式：/repos/{repo}/projects/{project}/...）。"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from testplat_control.api.case_schemas import (
    CaseAssetDetailResponse,
    CaseExecutionRecordDetailResponse,
    CaseResult,
    CaseRunRequest,
    CaseRunResponse,
)
from testplat_control.api.platform_session import require_user
from testplat_control.database.models import ExecutionRecord
from testplat_control.database.session import get_db
from testplat_control.deps import get_engine_port
from testplat_control.ports.engine import EnginePort
from testplat_control.services.case_asset_service import find_case_file
from testplat_control.services.execution_service import run_case
from testplat_control.services.platform_auth import PlatformPrincipal
from testplat_control.services.project_access import (
    ensure_snapshot_dirs,
    get_project,
    get_repos_config,
    require_env,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/repos/{repo}/projects/{project}", tags=["cases"])


def _load_case_result(record: ExecutionRecord) -> CaseResult | None:
    """把 ``result_json`` 解析为 CaseResult；缺失或不符合 schema 返回 None。"""
    if not record.result_json:
        return None
    try:
        return CaseResult.model_validate(json.loads(record.result_json))
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning(
            "Case 执行记录 %s 的 result_json 无法按 CaseResult 解析 exc_type=%s",
            record.id,
            type(exc).__name__,
        )
        return None


@router.get("/cases/{case_id}", response_model=CaseAssetDetailResponse)
async def get_case_detail(
    repo: str,
    project: str,
    case_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> CaseAssetDetailResponse:
    """获取 Case 资产的文件级元信息。"""
    row = get_project(db, repo, project)
    _, assets_root, _ = ensure_snapshot_dirs(get_repos_config(request), row)
    info = find_case_file(assets_root, case_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseAssetDetailResponse(
        case_id=info.case_id,
        path=info.path,
        file_name=info.file_name,
        size_bytes=info.size_bytes,
        modified_at=info.modified_at,
    )


@router.post("/cases/{case_id}/run", response_model=CaseRunResponse)
async def run_case_asset(
    repo: str,
    project: str,
    case_id: str,
    body: CaseRunRequest,
    request: Request,
    db: Session = Depends(get_db),
    engine: EnginePort = Depends(get_engine_port),
    user: PlatformPrincipal = Depends(require_user),
) -> CaseRunResponse:
    """串行运行一个 Case，并保存执行记录。"""
    row = get_project(db, repo, project)
    env = require_env(db, row, body.env)
    commit_sha, assets_root, config_root = ensure_snapshot_dirs(get_repos_config(request), row)
    record = await run_case(
        db=db,
        project=row,
        case_id=case_id,
        params=body.params,
        engine=engine,
        env=env,
        commit_sha=commit_sha,
        assets_root=assets_root,
        config_root=config_root,
        timeout_seconds=body.timeout_seconds,
        operator=user.username,
    )
    result = _load_case_result(record)
    if result is None or not record.id:
        raise HTTPException(status_code=500, detail="Execution result is not valid")
    duration = None if record.duration is None else float(record.duration)
    return CaseRunResponse(
        record_id=record.id,
        status=result.status,
        duration=duration,
        result=result,
        commit_sha=record.commit_sha,
        operator=record.operator,
        config_revision=record.config_revision,
    )


@router.get(
    "/case-execution-records/{record_id}",
    response_model=CaseExecutionRecordDetailResponse,
)
async def get_case_execution_record(
    repo: str,
    project: str,
    record_id: str,
    db: Session = Depends(get_db),
) -> CaseExecutionRecordDetailResponse:
    """获取 Case 执行记录详情。"""
    row = get_project(db, repo, project)
    record = (
        db.query(ExecutionRecord)
        .filter(
            ExecutionRecord.id == record_id,
            ExecutionRecord.project_id == row.id,
            ExecutionRecord.asset_type == "case",
        )
        .first()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Execution record not found")
    return CaseExecutionRecordDetailResponse.from_model(record, _load_case_result(record))
