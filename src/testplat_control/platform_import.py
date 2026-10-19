"""Additive old-config import. Default: review only; never print credential values.

Invoke with scripts/dev.sh python -m testplat_control.platform_import --help.
DATABASE_URL must be explicit so this tool cannot accidentally select a preview DB.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ImportConflictError(Exception):
    """A fixed, non-secret error suitable for CLI output."""


@dataclass(repr=False)
class AccountSpec:
    name: str
    profile: str
    credentials: dict[str, str] = field(repr=False)


@dataclass(repr=False)
class OwnerSpec:
    key: str
    hosts: dict[str, str]
    accounts: list[AccountSpec] = field(repr=False)


def _load(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text())
        if not isinstance(value, dict):
            raise ValueError
        return value
    except Exception:
        raise ImportConflictError("旧配置缺失或无效；未显示文件内容") from None


def build_plan(
    source: Path, *, allow_e3e3_b2_rename: bool = False, skip_e3e3_b2: bool = False
) -> list[OwnerSpec]:
    try:
        env = _load(source / "envs/test.yaml")
        secrets = _load(source / "secrets/test.secrets.yaml")
        hosts = env["api_hosts"]
        plans = []
        for project, owner, users in [
            ("go2", "gsb", {"b1": "18583220150"}),
            ("e3e3", "gsb_e3e3", {"b1": "泡泡象", "b2": "张建雨"}),
        ]:
            web = _load(source / f"envs/test/{project}.yaml")["web_hosts"]
            accounts = []
            for role, username in users.items():
                if project == "e3e3" and role == "b2" and skip_e3e3_b2:
                    continue
                old = secrets["accounts"][project][role]["primary"]
                if str(old["username"]) != username:
                    if not (project == "e3e3" and role == "b2" and allow_e3e3_b2_rename):
                        raise ImportConflictError(
                            f"{project} {role}.primary 的旧用户名不同，须确认密码对应关系"
                        )
                accounts.append(
                    AccountSpec(
                        f"gsb.{role}.primary",
                        "gsb_login",
                        {"username": username, "password": old["password"]},
                    )
                )
            mapping = {key: hosts[key] for key in ("unified_login", "gsb")}
            mapping.update({key: web[key] for key in ("sso", "portal") if key in web})
            if "gsb" in web:
                mapping["gsb_web"] = web["gsb"]
            plans.append(OwnerSpec(owner, mapping, accounts))
        for key, name, profile in [
            ("admin_go2", "admin_go2.default", "admin_go2_login"),
            ("daifa_admin", "df_admin.default", "df_admin_pending"),
            ("daifa_picker", "df_picker.default", "df_picker_login"),
        ]:
            old = secrets["logins"][key]["default"]
            if key == "daifa_picker":
                credentials = {"username": old["phone"], "password": old["verification_code"]}
            else:
                credentials = {k: old[k] for k in ("username", "password")}
                if key == "daifa_admin":
                    credentials["login_password"] = old["login_password"]
            mapping = {key: hosts[key]}
            web = env.get("web_hosts", {})
            if key in web:
                mapping[key + "_web"] = web[key]
            plans.append(OwnerSpec(key, mapping, [AccountSpec(name, profile, credentials)]))
        from testplat_control.services.environment_store import (
            validate_api_hosts,
            validate_credentials,
        )

        for plan in plans:
            validate_api_hosts(plan.hosts)
            for account in plan.accounts:
                validate_credentials(account.credentials)
        return plans
    except ImportConflictError:
        raise
    except Exception:
        raise ImportConflictError("旧配置字段缺失或类型不符；未显示凭据") from None


def import_plan(db, plans: list[OwnerSpec], *, repo: str, operator: str, apply: bool) -> dict:
    from testplat_control.database.models import Project, ProjectEnvironment, TestAccount
    from testplat_control.services.crypto import encrypt_credentials
    from testplat_control.services.environment_store import (
        create_account,
        create_environment,
        update_environment,
    )
    from testplat_control.services.workspaces import configuration_project

    # Preflight every target before writing. Re-running preserves all existing values.
    for plan in plans:
        project = db.get(Project, f"{repo}/{plan.key}")
        if (
            project is None
            or project.archived
            or configuration_project(db, project).id != project.id
        ):
            raise ImportConflictError("目标工作区未同步或配置归属不正确，请先同步 Assets")
    if apply:
        # Fail before any environment commit when the caller forgot the existing master key.
        encrypt_credentials({})
    summary = {
        "environments_created": 0,
        "hosts_added": 0,
        "accounts_created": 0,
        "accounts_preserved": 0,
        "applied": apply,
    }
    for plan in plans:
        project_id = f"{repo}/{plan.key}"
        row = db.query(ProjectEnvironment).filter_by(project_id=project_id, env="test").first()
        if row is None:
            summary["environments_created"] += 1
            missing = dict(plan.hosts)
            if apply:
                row = create_environment(
                    db,
                    project_id=project_id,
                    env="test",
                    api_hosts=missing,
                    timeout_seconds=30,
                    case_params={},
                    enabled=True,
                    operator=operator,
                )
        else:
            missing = {k: v for k, v in plan.hosts.items() if k not in row.api_hosts}
            if apply and missing:
                row = update_environment(
                    db,
                    project_id=project_id,
                    env="test",
                    expected_revision=row.revision,
                    operator=operator,
                    fields={"api_hosts": {**row.api_hosts, **missing}},
                )
        summary["hosts_added"] += len(missing)
        for spec in plan.accounts:
            existing = (
                db.query(TestAccount)
                .filter_by(project_id=project_id, env="test", account_name=spec.name)
                .first()
            )
            if existing is not None:
                summary["accounts_preserved"] += 1
                continue
            summary["accounts_created"] += 1
            if apply:
                create_account(
                    db,
                    project_id=project_id,
                    env="test",
                    account_name=spec.name,
                    display_name=None,
                    business_role=None,
                    login_profile=spec.profile,
                    credentials=spec.credentials,
                    enabled=True,
                    operator=operator,
                )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--repo", default="main")
    parser.add_argument("--operator", default="platform-import")
    correspondence = parser.add_mutually_exclusive_group()
    correspondence.add_argument("--allow-e3e3-b2-rename", action="store_true")
    correspondence.add_argument("--skip-e3e3-b2", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    os.environ["DATABASE_URL"] = args.database_url
    try:
        plans = build_plan(
            args.source,
            allow_e3e3_b2_rename=args.allow_e3e3_b2_rename,
            skip_e3e3_b2=args.skip_e3e3_b2,
        )
        from testplat_control.database.session import SessionLocal

        with SessionLocal() as db:
            result = import_plan(
                db, plans, repo=args.repo, operator=args.operator, apply=args.apply
            )
        import json

        print(json.dumps(result))
    except Exception as exc:
        message = (
            str(exc)
            if isinstance(exc, ImportConflictError)
            else "导入停止；请检查配置、密钥和数据库状态（未输出敏感异常）"
        )
        raise SystemExit(message) from None


if __name__ == "__main__":
    main()
