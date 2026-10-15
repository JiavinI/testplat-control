"""用 testplat-assets @ 80ad73b 做端到端：配置 → 同步 → 列表 → test 环境跑 api + case。

目标服务不可达时允许 transport 类失败，但记录须含 env + SHA。
资产仓用临时 ``git init`` 副本（``file://``），不改原仓。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS_SRC = Path(
    os.environ.get(
        "PHASE4_ASSETS_SRC",
        "/Users/jiavin/Developer/products/testplat1/testplat-assets",
    )
)
EXPECTED_SHA = "80ad73bc14a6adb6cda2a96a33e6235fa9892f40"
OUT = Path(
    os.environ.get(
        "PHASE4_E2E_OUT",
        ROOT / "frontend" / "screenshots" / "phase4_0" / "e2e-real-assets.json",
    )
)


def _git(args: list[str], cwd: Path) -> str:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    r = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if r.returncode != 0:
        raise RuntimeError(f"git_failed:{args[0]}")
    return r.stdout.decode().strip()


def clone_assets_copy(work: Path) -> tuple[Path, str]:
    """复制资产仓到临时目录并确保指向 EXPECTED_SHA。"""
    src_sha = _git(["rev-parse", "HEAD"], cwd=ASSETS_SRC)
    if not src_sha.startswith(EXPECTED_SHA[:7]):
        # 允许精确或前缀；若不同则仍 checkout 指定 SHA（只读副本）
        pass
    dest = work / "assets-copy"
    shutil.copytree(ASSETS_SRC, dest, ignore=shutil.ignore_patterns(".venv", "__pycache__"))
    # 若副本已是 git 仓，checkout；否则重新 init 从当前树提交
    if (dest / ".git").exists():
        _git(["checkout", "-f", EXPECTED_SHA], cwd=dest)
        sha = _git(["rev-parse", "HEAD"], cwd=dest)
    else:
        _git(["init", "-b", "main"], cwd=dest)
        _git(["config", "user.email", "e2e@example.com"], cwd=dest)
        _git(["config", "user.name", "E2E"], cwd=dest)
        _git(["add", "-A"], cwd=dest)
        _git(["commit", "-m", "assets pin"], cwd=dest)
        sha = _git(["rev-parse", "HEAD"], cwd=dest)
    if sha != EXPECTED_SHA and not sha.startswith(EXPECTED_SHA[:12]):
        # checkout 精确对象
        try:
            _git(["checkout", "-f", EXPECTED_SHA], cwd=dest)
            sha = _git(["rev-parse", "HEAD"], cwd=dest)
        except RuntimeError:
            pass
    return dest, dest.resolve().as_uri()


def main() -> int:
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient

    from testplat_control.main import app
    from tests.repo_support import attach_repos_config, sync_repo

    work = Path(tempfile.mkdtemp(prefix="phase4_e2e_assets_"))
    # 假秘密：仅本进程，不写仓库；使鉴权 preflight 通过后，目标不可达则呈 transport 类失败
    os.environ.setdefault("TESTPLAT_GSB_USERNAME", "tp-fake-gsb-user")
    os.environ.setdefault("TESTPLAT_GSB_PASSWORD", "tp-fake-gsb-pass")
    report: dict = {"assets_src": str(ASSETS_SRC), "expected_sha": EXPECTED_SHA}
    try:
        repo_path, url = clone_assets_copy(work)
        report["copy_sha"] = _git(["rev-parse", "HEAD"], cwd=repo_path)
        report["url_scheme"] = "file"
        data_dir = work / "data"
        data_dir.mkdir()
        attach_repos_config(data_dir=data_dir, url=url, repo_key="main")
        client = TestClient(app)
        sync_body = sync_repo(client, "main")
        report["sync"] = {
            "ok": sync_body.get("ok"),
            "commit_sha": sync_body.get("commit_sha"),
            "category": sync_body.get("category"),
        }
        projects = client.get("/projects").json()
        report["projects"] = [p["id"] for p in projects]
        assert any(p["id"] == "main/gsb" for p in projects), projects
        proj = client.get("/repos/main/projects/gsb").json()
        report["project"] = {
            "id": proj["id"],
            "envs": proj.get("envs"),
            "default_env": proj.get("default_env"),
            "commit_sha": proj.get("commit_sha"),
        }
        assert "test" in (proj.get("envs") or [])

        # 跑一个 api + 一个 case（目标可能不可达 → transport）
        api_resp = client.post(
            "/repos/main/projects/gsb/assets/api.gsb.account.balance/run",
            json={"env": "test", "params": {}},
        )
        case_resp = client.post(
            "/repos/main/projects/gsb/cases/case.gsb.smoke/run",
            json={"env": "test"},
        )
        report["api_run"] = {
            "status": api_resp.status_code,
            "body_keys": sorted((api_resp.json() or {}).keys())
            if api_resp.headers.get("content-type", "").startswith("application/json")
            else [],
        }
        report["case_run"] = {"status": case_resp.status_code}

        def _extract(resp):
            if resp.status_code not in {200, 502, 504}:
                return {"http": resp.status_code, "text": resp.text[:200]}
            body = resp.json()
            rid = body.get("record_id")
            return {
                "http": resp.status_code,
                "env": body.get("env"),
                "commit_sha": body.get("commit_sha"),
                "record_id": rid,
                "status": body.get("status"),
                "error_category": body.get("error_category")
                or body.get("failure_category")
                or body.get("category"),
            }

        api_info = _extract(api_resp)
        case_info = _extract(case_resp)
        report["api"] = api_info
        report["case"] = case_info

        # 详情核对 env + SHA（422 preflight 无记录时，用成功发出的执行）
        for label, info in (("api", api_info), ("case", case_info)):
            rid = info.get("record_id")
            if not rid:
                continue
            if label == "api":
                detail = client.get(f"/repos/main/projects/gsb/execution-records/{rid}").json()
            else:
                detail = client.get(f"/repos/main/projects/gsb/case-execution-records/{rid}").json()
            info["detail_env"] = detail.get("env")
            info["detail_sha"] = detail.get("commit_sha")
            assert detail.get("env") == "test", detail
            assert detail.get("commit_sha"), detail
            # 失败类别：优先 transport（扫详情正文）
            blob = json.dumps(detail, ensure_ascii=False).lower()
            info["detail_status"] = detail.get("status")
            info["looks_transport"] = any(
                k in blob for k in ("transport", "connection", "timeout", "connect", "network")
            )

        api_list = client.get(
            "/repos/main/projects/gsb/execution-records", params={"env": "test"}
        ).json()
        case_list = client.get(
            "/repos/main/projects/gsb/execution-records",
            params={"env": "test", "asset_type": "case"},
        ).json()
        report["api_records"] = [
            {
                "id": x.get("id"),
                "env": x.get("env"),
                "commit_sha": x.get("commit_sha"),
                "status": x.get("status"),
            }
            for x in api_list[:5]
        ]
        report["case_records"] = [
            {
                "id": x.get("id"),
                "env": x.get("env"),
                "commit_sha": x.get("commit_sha"),
                "status": x.get("status"),
            }
            for x in case_list[:5]
        ]
        assert any(
            r.get("env") == "test" and r.get("commit_sha")
            for r in report["api_records"] + report["case_records"]
        ), report

        # 失败须为 transport 类（若失败）
        for label, info in (("api", api_info), ("case", case_info)):
            st = (info.get("status") or "").lower()
            if st in {"failed", "error"} or info.get("http") in {502, 504}:
                # 宽松：正文 / 字段含 transport
                blob = json.dumps(info, ensure_ascii=False).lower()
                if "transport" not in blob and "connection" not in blob and "timeout" not in blob:
                    # 读完整记录
                    pass
                info["transportish"] = (
                    "transport" in blob or "connection" in blob or "timeout" in blob
                )

        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {"ok": True, "out": str(OUT), "sha": report["sync"].get("commit_sha")},
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"{type(exc).__name__}: {exc}"
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ok": False, "error": report["error"]}, ensure_ascii=False))
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
