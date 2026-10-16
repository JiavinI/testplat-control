"""用 testplat-assets 指定提交做端到端：Web 环境与账号 → 同步 → 跑 api + case。

目标服务不可达时允许 transport / timeout，但执行记录须含 operator、env、commit、config_revision。
不把真实 GSB 业务成功当作通过条件。资产仓用临时副本，不改原仓。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SHA = "f226b4a88b68fd582f717f5f0ff3652c1f56eb7e"
OUT = Path(
    os.environ.get(
        "PHASE4_E2E_OUT",
        ROOT / "frontend" / "screenshots" / "phase4_1a" / "e2e-real-assets.json",
    )
)
PLATFORM_USER = "e2eop"
PLATFORM_PASSWORD = "e2e-pass-1"
ACCOUNT_USER = "gsb-user-e2e"
ACCOUNT_PASSWORD = "gsb-pass-e2e"


def _assets_src() -> Path:
    sys.path.insert(0, str(ROOT))
    from tests.platform_gate import default_assets_checkout

    return default_assets_checkout(ROOT)


def _git(args: list[str], cwd: Path) -> str:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git_failed:{args[0]}")
    return result.stdout.decode().strip()


def clone_assets_copy(work: Path, assets_src: Path) -> tuple[Path, str]:
    """复制资产仓到临时目录并停在 EXPECTED_SHA。"""
    dest = work / "assets-copy"
    shutil.copytree(assets_src, dest, ignore=shutil.ignore_patterns(".venv", "__pycache__"))
    _git(["checkout", "-B", "phase4-1a-pin", EXPECTED_SHA], cwd=dest)
    _git(["config", "user.email", "e2e@example.com"], cwd=dest)
    _git(["config", "user.name", "E2E"], cwd=dest)
    sha = _git(["rev-parse", "HEAD"], cwd=dest)
    if sha != EXPECTED_SHA:
        raise RuntimeError("assets_sha_mismatch")
    return dest, dest.resolve().as_uri()


def _template_hosts(repo: Path) -> dict[str, str]:
    payload = yaml.safe_load(
        (repo / "projects/gsb/config/envs/test.yaml").read_text(encoding="utf-8")
    )
    hosts = payload.get("api_hosts") or {}
    return {str(key): str(value) for key, value in hosts.items()}


def _record_meta(client, record_id: str) -> dict:
    detail = client.get(f"/repos/main/projects/gsb/execution-records/{record_id}")
    if detail.status_code != 200:
        detail = client.get(f"/repos/main/projects/gsb/case-execution-records/{record_id}")
    body = detail.json()
    return {
        "http": detail.status_code,
        "operator": body.get("operator"),
        "env": body.get("env"),
        "commit_sha": body.get("commit_sha"),
        "config_revision": body.get("config_revision"),
        "status": body.get("status"),
    }


def main() -> int:
    assets_src = _assets_src()
    # 主密钥必须在导入 Control 之前写入，进程不会自动生成。
    os.environ["TESTPLAT_MASTER_KEY"] = Fernet.generate_key().decode("ascii")
    os.environ.pop("TESTPLAT_REPOS_FILE", None)
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient

    from testplat_control.main import app
    from tests.platform_gate import establish
    from tests.repo_support import attach_repos_config, commit_all, sync_repo

    work = Path(tempfile.mkdtemp(prefix="phase4_e2e_assets_"))
    report: dict = {
        "assets_src": str(assets_src),
        "expected_sha": EXPECTED_SHA,
        "real_gsb_business_pass_required": False,
    }
    try:
        if not assets_src.is_dir():
            raise RuntimeError("assets_checkout_missing")
        repo_path, url = clone_assets_copy(work, assets_src)
        report["copy_sha"] = _git(["rev-parse", "HEAD"], cwd=repo_path)
        hosts = _template_hosts(repo_path)
        data_dir = work / "data"
        data_dir.mkdir()
        attach_repos_config(data_dir=data_dir, url=url, repo_key="main", branch="phase4-1a-pin")
        client = TestClient(app)
        establish(client, username=PLATFORM_USER, password=PLATFORM_PASSWORD)
        sync_body = sync_repo(client, "main")
        report["sync"] = {
            "ok": sync_body.get("ok"),
            "commit_sha": sync_body.get("commit_sha"),
            "category": sync_body.get("category"),
        }
        projects = client.get("/projects").json()
        report["projects"] = [item["id"] for item in projects]
        assert any(item["id"] == "main/gsb" for item in projects), projects
        before_web = client.get("/repos/main/projects/gsb").json()
        assert "test" in (before_web.get("envs") or [])
        profiles = client.get("/repos/main/projects/gsb/login-profiles")
        assert profiles.status_code == 200, profiles.status_code
        names = [item["name"] for item in profiles.json()["profiles"]]
        assert "gsb_login" in names
        assert ACCOUNT_PASSWORD not in profiles.text

        base = "/repos/main/projects/gsb"
        for env_name in ("test", "pre"):
            created = client.post(
                f"{base}/environments",
                json={
                    "env": env_name,
                    "api_hosts": hosts,
                    "timeout_seconds": 2,
                    "case_params": {"product_keyword": "示例商品"},
                    "enabled": True,
                },
            )
            assert created.status_code == 201, created.status_code
            account = client.post(
                f"{base}/environments/{env_name}/accounts",
                json={
                    "account_name": "gsb",
                    "display_name": "商家",
                    "business_role": "采购",
                    "login_profile": "gsb_login",
                    "credentials": {"username": ACCOUNT_USER, "password": ACCOUNT_PASSWORD},
                },
            )
            assert account.status_code == 201, account.status_code
            assert "password" not in account.text or ACCOUNT_PASSWORD not in account.text

        listed = client.get(f"{base}/environments/test/accounts")
        assert listed.status_code == 200
        assert ACCOUNT_PASSWORD not in listed.text

        api_resp = client.post(
            f"{base}/assets/api.gsb.account.balance/run",
            json={"env": "test", "params": {}},
        )
        case_resp = client.post(
            f"{base}/cases/case.gsb.smoke/run",
            json={"env": "test", "params": {"product_keyword": "示例商品"}},
        )
        report["api_http"] = api_resp.status_code
        report["case_http"] = case_resp.status_code
        for label, response in (("api", api_resp), ("case", case_resp)):
            assert response.status_code in {200, 502, 504}, response.status_code
            assert ACCOUNT_PASSWORD not in response.text
            assert PLATFORM_PASSWORD not in response.text

        records = client.get(f"{base}/execution-records", params={"env": "test", "limit": 10})
        assert records.status_code == 200, records.status_code
        assert ACCOUNT_PASSWORD not in records.text
        rows = records.json()
        assert rows, "missing execution record"
        metas = []
        for row in rows[:2]:
            meta = _record_meta(client, row["id"])
            metas.append(meta)
            assert meta["operator"] == PLATFORM_USER
            assert meta["env"] == "test"
            assert meta["commit_sha"] == report["sync"]["commit_sha"]
            assert isinstance(meta["config_revision"], int) and meta["config_revision"] >= 1
        report["records"] = metas
        report["real_gsb_outcome"] = "metadata_only"

        # 同步回归：改 Git 模板后，Web 地址与启停保持原样，commit 可以前进。
        kept = client.get(f"{base}/environments/pre").json()
        marker = "http://127.0.0.1:9"
        (repo_path / "projects/gsb/config/envs/test.yaml").write_text(
            f"api_hosts:\n  gsb: {marker}\n  unified_login: {marker}\n",
            encoding="utf-8",
        )
        new_sha = commit_all(repo_path, "template only")
        synced = sync_repo(client, "main")
        assert synced["commit_sha"] == new_sha != report["sync"]["commit_sha"]
        again = client.get(f"{base}/environments/pre").json()
        assert again["api_hosts"] == kept["api_hosts"]
        assert again["enabled"] is True
        assert again["revision"] == kept["revision"]
        assert marker not in json.dumps(again["api_hosts"])
        report["sync_regression"] = {
            "old_sha": report["sync"]["commit_sha"],
            "new_sha": new_sha,
            "web_unchanged": True,
        }

        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "out": str(OUT)}, ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001
        detail = f"{type(exc).__name__}: {exc}"
        for secret in (
            ACCOUNT_PASSWORD,
            PLATFORM_PASSWORD,
            os.environ.get("TESTPLAT_MASTER_KEY", ""),
        ):
            if secret:
                detail = detail.replace(secret, "[redacted]")
        report["error"] = detail[:500]
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ok": False, "error": report["error"]}, ensure_ascii=False))
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
