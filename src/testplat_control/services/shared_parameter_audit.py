"""共享参数只读盘点。禁止导入应用／数据库 session、初始化表或执行请求。"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

from testplat_engine.adapters.filesystem.case_loader import load_case

from testplat_control.parsers.yaml_parser import YamlParser
from testplat_control.services.api_parameter_schema import (
    _matches_type,
    asset_default_params,
    build_param_infos,
)
from testplat_control.services.case_asset_service import case_id_for_relative_path
from testplat_control.services.manifest import is_valid_key, load_manifest, safe_resolve
from testplat_control.services.parameter_sets import SENSITIVE, compose_parameters, validate_values

# 只在 Engine 已接受的 Case 模型中投影引用，不定义第二套 Case schema。
_PLACEHOLDER = re.compile(r"\$\{([^{}]*)\}")


def _object(raw: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("object required")
    return value


def _type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return "invalid"


def _equal(left: Any, right: Any) -> bool:
    # Python 的 False == 0 / True == 1 不能冒充 JSON 类型相同。
    if _type(left) != _type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_equal(a, b) for a, b in zip(left, right))
    return left == right


def _refs(value: Any) -> set[str]:
    if isinstance(value, str):
        return {
            ref.removeprefix("params.") for ref in _PLACEHOLDER.findall(value)
            if ref.startswith("params.")
        }
    if isinstance(value, Mapping):
        return set().union(*(_refs(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_refs(item) for item in value))
    return set()


def _safe_label(value: Any) -> str:
    # 仍只输出标识，不输出参数值；敏感名称不写进引用路径。
    return "[sensitive key omitted]" if SENSITIVE.search(str(value)) else str(value)


def _path_exists(value: Any, path: str) -> bool:
    node = value
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return False
        node = node[part]
    return True


def _scan(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    assets, gaps = [], []
    for area in ("api", "scenarios"):
        directory = root / area
        if not directory.exists():
            continue
        if directory.is_symlink() or not directory.resolve().is_relative_to(root.resolve()):
            gaps.append({"asset": area, "kind": "symlink_not_scanned"})
            continue
        for dirpath, dirs, files in os.walk(directory, followlinks=False):
            for name in list(dirs):
                if (Path(dirpath) / name).is_symlink():
                    gaps.append({"asset": area, "kind": "symlink_not_scanned"})
                    dirs.remove(name)
                elif name.startswith("."):
                    dirs.remove(name)
            for name in sorted(files):
                path = Path(dirpath) / name
                if name.startswith(".") or path.suffix not in {".yaml", ".yml"}:
                    continue
                relative = path.relative_to(root)
                label = relative.as_posix()
                if path.is_symlink():
                    gaps.append({"asset": label, "kind": "symlink_not_scanned"})
                    continue
                try:
                    if area == "api":
                        parsed = YamlParser.parse_api_yaml(path)
                        form = build_param_infos(parsed["inputs"])
                        # 运行入口按路径生成的 asset id 定位，不采用文件里的另一 id。
                        asset_id = ".".join(relative.with_suffix("").parts)
                        assets.append({
                            "id": asset_id, "type": "api", "form": form,
                            "defaults": asset_default_params(parsed["inputs"]), "refs": set(),
                        })
                    else:
                        case_id = case_id_for_relative_path(relative)
                        if case_id is None:
                            gaps.append({"asset": label, "kind": "non_runnable_scenario"})
                            continue
                        case = load_case(case_id, root)
                        refs = set().union(*(_refs(step.params) for step in case.steps))
                        assets.append({
                            "id": case.id, "type": "case", "form": None,
                            "defaults": dict(case.params), "refs": refs,
                        })
                except Exception:
                    # YAML／Engine 异常可能携带原文或值，绝不输出异常文本。
                    gaps.append({"asset": label, "kind": "asset_analysis_failed"})
    return sorted(assets, key=lambda item: (item["type"], item["id"])), gaps


def _snapshot(data_dir: Path, project: dict[str, Any]) -> Path:
    if not is_valid_key(project["repo"]) or not is_valid_key(project["project_key"]):
        raise ValueError("invalid project key")
    sha = project["commit_sha"]
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("invalid sha")
    root = safe_resolve(data_dir, f"{project['repo']}/snap/{sha}")
    manifest = load_manifest(root)
    return safe_resolve(root, manifest.projects[project["project_key"]].assets)


def _read(database: Path) -> dict[str, Any]:
    # 不导入 database.session（该模块 import 会 create_all）。不读取账号和 Host。
    uri = database.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")  # 多张表来自同一个一致性快照。
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        projects = {row["id"]: dict(row) for row in db.execute(
            "SELECT id, repo, project_key, archived, commit_sha FROM projects ORDER BY id"
        )}
        bindings = {row["project_id"]: dict(row) for row in db.execute(
            "SELECT project_id, platform, business_project, configuration_project_id "
            "FROM workspace_bindings ORDER BY project_id"
        )} if "workspace_bindings" in tables else {}
        envs = [dict(row) for row in db.execute(
            "SELECT project_id, env, enabled, case_params, revision FROM project_environments "
            "ORDER BY project_id, env"
        )]
        saved = [dict(row) for row in db.execute(
            'SELECT project_id, asset_type, asset_id, scope, env_key, "values", revision '
            'FROM parameter_sets ORDER BY project_id, asset_type, asset_id, scope, env_key'
        )] if "parameter_sets" in tables else []
        return {
            "projects": projects, "bindings": bindings, "environments": envs,
            "saved": saved, "parameter_sets_available": "parameter_sets" in tables,
        }


def _impact(asset, key, shared, saved, override):
    declared = {item.name: item for item in asset["form"]} if asset["form"] is not None else None
    # Case 路由把整份共享对象传给每个场景；未引用仍要列成“仅注入”。
    if declared is not None and key not in declared:
        return None
    names = set(declared) if declared is not None else None
    defaults = asset["defaults"]
    before, sources = compose_parameters(defaults, saved, shared, override, {}, names=names)
    after, _ = compose_parameters(
        defaults, saved, {k: v for k, v in shared.items() if k != key}, override, {}, names=names,
    )
    paths = sorted(ref for ref in asset["refs"] if ref.split(".")[0] == key)
    same = key in before and key in after and _equal(before[key], after[key])
    removal = "unchanged" if same else "changed" if key in after else "removed"
    nested_refs = [ref for ref in paths if "." in ref]
    broken = [ref for ref in paths if not _path_exists(after, ref)]
    overlaps = []
    for scope, layer in (("asset_default", saved), ("environment_override", override)):
        if key in layer:
            overlaps.append({
                "scope": scope, "relation": "same_value" if _equal(layer[key], shared[key])
                else "different_value",
            })
    expected = declared[key].type if declared is not None else None
    migratable = expected is None or _matches_type(expected, shared[key])
    try:
        validate_values({key: shared[key]})
    except Exception:
        migratable = False
    if isinstance(shared[key], float) and not math.isfinite(shared[key]):
        migratable = False
    return {
        "asset_id": asset["id"], "asset_type": asset["type"],
        "consumer": "api_declared" if declared is not None else
        "case_reference" if paths else "case_injected_without_reference",
        "reference_paths": [_safe_label(ref) for ref in paths],
        "nested_reference_count": len(nested_refs),
        "current_source": sources.get(key),
        "shared_type_compatible": _matches_type(expected, shared[key]) if expected else None,
        "can_save_as_business_parameter": migratable,
        "existing_values": overlaps,
        "remove_shared_key": removal,
        "unresolved_references_after_removal": len(broken),
        "copy_to_asset_environment": "preserves_effective_value" if key not in override
        else "same_as_existing" if _equal(override[key], shared[key]) else
        "would_overwrite_existing_override",
    }


def build_audit(database: Path, data_dir: Path) -> dict[str, Any]:
    state = _read(database)
    projects, bindings = state["projects"], state["bindings"]
    report: dict[str, Any] = {
        "database_mode": "read_only", "parameter_sets_table_available":
        state["parameter_sets_available"], "workspaces": [], "shared_environments": [],
        "analysis_gaps": [], "migration_safety": "review_required_no_automatic_copy_or_delete",
    }
    scanned, owners, stored = {}, {}, {}
    for project_id, project in projects.items():
        binding = bindings.get(project_id, {})
        owner_id = binding.get("configuration_project_id", project_id)
        owner = projects.get(owner_id)
        owner_binding = bindings.get(owner_id, {})
        valid_owner = owner and owner["repo"] == project["repo"] and not (
            owner["archived"] and not project["archived"]
        ) and owner_binding.get("configuration_project_id", owner_id) == owner_id
        if not valid_owner:
            report["analysis_gaps"].append({"project_id": project_id, "kind": "invalid_owner"})
        owners[project_id] = owner_id
        report["workspaces"].append({
            "project_id": project_id, "configuration_project_id": owner_id,
            "platform": binding.get("platform"),
            "business_project": binding.get("business_project"),
            "archived": bool(project["archived"]), "commit_sha": project["commit_sha"],
        })
        try:
            assets, gaps = _scan(_snapshot(data_dir, project))
            scanned[project_id] = assets
            report["analysis_gaps"].extend({"project_id": project_id, **gap} for gap in gaps)
        except Exception:
            scanned[project_id] = []
            report["analysis_gaps"].append({
                "project_id": project_id, "kind": "snapshot_unavailable_or_invalid",
            })
        report["workspaces"][-1]["api_count"] = sum(
            asset["type"] == "api" for asset in scanned[project_id]
        )
        report["workspaces"][-1]["case_count"] = sum(
            asset["type"] == "case" for asset in scanned[project_id]
        )
    for row in state["saved"]:
        try:
            stored[(row["project_id"], row["asset_type"], row["asset_id"], row["scope"],
                    row["env_key"])] = (_object(row["values"]), row["revision"])
        except Exception:
            report["analysis_gaps"].append({
                "project_id": row["project_id"], "kind": "stored_parameter_unreadable",
            })
    for env in state["environments"]:
        owner_id = env["project_id"]
        try:
            shared = _object(env["case_params"])
        except Exception:
            report["analysis_gaps"].append({
                "project_id": owner_id, "environment": env["env"],
                "kind": "shared_parameters_unreadable",
            })
            continue
        members = [pid for pid, owner in owners.items() if owner == owner_id]
        if not members:
            report["analysis_gaps"].append({
                "project_id": owner_id, "environment": env["env"],
                "kind": "environment_has_no_configuration_consumers",
            })
        section = {
            "configuration_project_id": owner_id, "environment": env["env"],
            "enabled": bool(env["enabled"]), "environment_revision": env["revision"],
            "workspaces": members, "parameter_count": len(shared), "keys": [],
        }
        for key in sorted(shared):
            consumers = []
            for pid in members:
                for asset in scanned[pid]:
                    prefix = (pid, asset["type"], asset["id"])
                    saved, default_revision = stored.get((*prefix, "asset_default", ""), ({}, 0))
                    override, env_revision = stored.get(
                        (*prefix, "environment_override", env["env"]), ({}, 0),
                    )
                    impact = _impact(asset, key, shared, saved, override)
                    if impact is not None:
                        consumers.append({
                            "project_id": pid, "archived": bool(projects[pid]["archived"]),
                            "default_revision": default_revision,
                            "override_revision": env_revision, **impact,
                        })
            section["keys"].append({
                "name": _safe_label(key), "value_type": _type(shared[key]),
                "consumers": consumers, "automatic_removal_allowed": False,
            })
        report["shared_environments"].append(section)
    report["summary"] = {
        "workspace_count": len(report["workspaces"]),
        "environment_count": len(report["shared_environments"]),
        "nonempty_shared_environments": sum(
            bool(section["keys"]) for section in report["shared_environments"]
        ),
        "shared_key_count": sum(len(section["keys"]) for section in report["shared_environments"]),
        "analysis_gap_count": len(report["analysis_gaps"]),
    }
    return report


def _cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("`", "'").replace("\n", " ").replace("\r", " ")


def to_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 共享环境参数消费者与迁移影响清单", "",
        "只读盘点；不含参数值、Host、账号或凭据。不初始化表、不物化快照、不执行请求。", "",
        f"- 工作区：{report['summary']['workspace_count']}；数据库环境："
        f"{report['summary']['environment_count']}；非空共享环境："
        f"{report['summary']['nonempty_shared_environments']}；共享键："
        f"{report['summary']['shared_key_count']}；分析缺口："
        f"{report['summary']['analysis_gap_count']}。",
        "- 按资产参数表："
        f"{'存在' if report['parameter_sets_table_available'] else '尚不存在（未创建）'}。",
        "- 所有项目均需审查；本报告不授权复制或删除共享值。", "",
        "## 工作区与版本", "",
        "| 实际工作区 | 平台／业务项目 | 配置归属 | 归档 | API／Case 数 | Assets SHA |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for workspace in report["workspaces"]:
        lines.append("| " + " | ".join(_cell(value) for value in (
            workspace['project_id'],
            f"{workspace['platform'] or '-'} / {workspace['business_project'] or '-'}",
            workspace['configuration_project_id'], workspace['archived'],
            f"{workspace['api_count']} / {workspace['case_count']}",
            workspace['commit_sha'] or '-',
        )) + " |")
    for section in report["shared_environments"]:
        lines.extend([
            "",
            f"## {_cell(section['configuration_project_id'])} · "
            f"{_cell(section['environment'])}",
            "", f"环境启用：{section['enabled']}；revision：{section['environment_revision']}；"
            f"共享工作区：{', '.join(_cell(pid) for pid in section['workspaces'])}。", "",
        ])
        if not section["keys"]:
            lines.append("共享 case_params 为空，无需迁移；保留原状。")
        for key in section["keys"]:
            lines.extend([
                f"### {_cell(key['name'])}（{key['value_type']}）", "",
                "| 工作区／资产 | 消费方式 | 当前来源 | 删除共享键 | 复制到环境层 | "
                "类型可用／可保存 | 已保存默认／覆盖版本 | 现有值比较 | 未解析引用数 |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | ---: |",
            ])
            if not key["consumers"]:
                lines.append("| 未发现消费者（不能据此删除） | | | | | | | | |")
            for consumer in key["consumers"]:
                overlaps = ', '.join(f"{item['scope']}:{item['relation']}"
                                     for item in consumer["existing_values"]) or '-'
                lines.append("| " + " | ".join(_cell(value) for value in (
                    f"{consumer['project_id']} · {consumer['asset_id']}", consumer['consumer'],
                    consumer['current_source'], consumer['remove_shared_key'],
                    consumer['copy_to_asset_environment'],
                    f"{consumer['shared_type_compatible']} / "
                    f"{consumer['can_save_as_business_parameter']}",
                    f"{consumer['default_revision']} / {consumer['override_revision']}",
                    overlaps, consumer['unresolved_references_after_removal'],
                )) + " |")
            lines.append("")
    lines.extend(["", "## 分析缺口", ""])
    lines.extend(
        "- " + _cell(json.dumps(gap, ensure_ascii=False))
        for gap in report["analysis_gaps"]
    )
    if not report["analysis_gaps"]:
        lines.append("无。")
    lines.extend([
        "", "## 判读与后续操作", "",
        "- `api_declared`：Control 表单声明该输入；未声明的共享键不会注入单接口。",
        "- `case_reference`：Engine 校验后的步骤参数明确引用该共享键，包括嵌套路径；"
        "`case_injected_without_reference`：共享对象仍传给 Case，但没有发现步骤引用，"
        "不等于无消费者。",
        "- 删除影响按无临时输入计算，比较 Git 默认、页面默认、共享环境、资产环境覆盖；"
        "`changed`／`removed` 表示有效参数变化，`unchanged` 只代表当前值相同。",
        "- `would_overwrite_existing_override` 必须选择保留或替换；不得自动复制。"
        "布尔与数字严格区分，null 作为值。嵌套对象整体替换，不做深合并。",
        "- 类型不符、敏感嵌套键、停用环境、归档工作区或任何分析缺口需单独处理。"
        "未引用参数、未发现消费者均不自动授权清空。",
        "- 静态盘点不能代替真实业务验收；确认目标后先在隔离库逐项模拟复制及移除，"
        "保留原共享值直至全部消费者验证完成。", "",
    ])
    return '\n'.join(lines)
