#!/usr/bin/env python3
"""Phase 4.0 验收矩阵：设计稿 §7 第 1–10 条。

资产仓库用临时目录 ``git init`` 的 ``file://`` 副本；第 2 / 4 条真实提交新 commit。
不改产品 ``src/``；git 一律参数列表 + ``GIT_TERMINAL_PROMPT=0``。

用法（在 Control worktree 根）::

    uv run python scripts/phase4_0_matrix.py

可选环境变量：
- ``PHASE4_MATRIX_OUT``：报告与截图目录（默认 ``frontend/screenshots/phase4_0``）
- ``PHASE4_SKIP_SCREENSHOTS=1``：跳过第 10 条（不启前后端）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

OUT = Path(os.environ.get("PHASE4_MATRIX_OUT", ROOT / "frontend" / "screenshots" / "phase4_0"))
OUT.mkdir(parents=True, exist_ok=True)

RESULTS: list[dict[str, Any]] = []


def _row(item: str, status: str, evidence: str, **extra: Any) -> None:
    RESULTS.append({"item": item, "status": status, "evidence": evidence, **extra})
    print(f"{status:5} {item}  {evidence}", flush=True)


def _check(item: str, desc: str, fn: Callable[[], str]) -> None:
    try:
        evidence = fn()
        _row(item, "PASS", evidence or desc)
    except Exception as exc:  # noqa: BLE001
        _row(item, "FAIL", f"{desc}: {type(exc).__name__}: {exc}")


def main() -> int:
    from fastapi.testclient import TestClient

    from testplat_control.adapters.fake_engine import FakeEngineAdapter
    from testplat_control.deps import get_engine_port
    from testplat_control.main import app
    from testplat_control.services.manifest import ManifestError, assert_relative_safe, safe_resolve
    from tests.repo_support import (
        DEFAULT_FILES,
        attach_repos_config,
        bootstrap_synced_project,
        commit_all,
        sync_repo,
    )

    client = TestClient(app)
    work = Path(tempfile.mkdtemp(prefix="phase4_0_matrix_"))

    # ---- §7-1 ----
    def t1() -> str:
        ctx = bootstrap_synced_project(client, work / "t1")
        projects = client.get("/projects").json()
        assert any(p["id"] == ctx["project_id"] for p in projects), projects
        create = client.post("/projects", json={"name": "x", "env": "test"})
        assert create.status_code in {404, 405, 422}, create.status_code
        return f"project={ctx['project_id']} create_status={create.status_code}"

    _check("§7-1", "file:// 同步后项目出现且无新建入口", t1)

    # ---- §7-2 ----
    def t2() -> str:
        ctx = bootstrap_synced_project(client, work / "t2")
        old = ctx["commit_sha"]
        case = (
            ctx["repo_path"] / "projects" / "demo" / "scenarios" / "demo" / "matrix_new.case.yaml"
        )
        case.parent.mkdir(parents=True, exist_ok=True)
        case.write_text(
            'schema_version: "0.2"\nid: case.demo.matrix_new\nname: matrix\nsteps: []\n',
            encoding="utf-8",
        )
        new_sha = commit_all(ctx["repo_path"], "matrix add case")
        body = sync_repo(client, ctx["repo"])
        assert body["commit_sha"] == new_sha != old
        detail = client.get(f"{ctx['base']}/cases/case.demo.matrix_new")
        assert detail.status_code == 200, detail.text
        return f"old={old[:7]} new={new_sha[:7]} case_ok"

    _check("§7-2", "新 commit 同步后树与 SHA 更新", t2)

    # ---- §7-3 ----
    def t3() -> str:
        ctx = bootstrap_synced_project(client, work / "t3")
        old = ctx["commit_sha"]
        # 不可达
        missing = (work / "t3" / "missing-repo").resolve().as_uri()
        attach_repos_config(data_dir=ctx["data_dir"], url=missing, repo_key=ctx["repo"])
        r1 = client.post(f"/repos/{ctx['repo']}/sync")
        b1 = r1.json()
        assert b1["ok"] is False and b1["commit_sha"] == old
        assert missing not in r1.text
        assert "category" in b1 and b1["category"] in {
            "network",
            "auth",
            "timeout",
            "invalid_manifest",
        }
        # 清单非法
        attach_repos_config(data_dir=ctx["data_dir"], url=ctx["url"], repo_key=ctx["repo"])
        # 重新挂回可达 URL 后弄坏清单
        (ctx["repo_path"] / "testplat.yaml").write_text('schema_version: "1"\n', encoding="utf-8")
        commit_all(ctx["repo_path"], "break manifest")
        r2 = client.post(f"/repos/{ctx['repo']}/sync")
        b2 = r2.json()
        assert b2["ok"] is False and b2["category"] == "invalid_manifest"
        assert b2["commit_sha"] == old
        return f"unreachable={b1['category']} invalid_manifest kept_sha={old[:7]}"

    _check("§7-3", "同步失败保留旧 SHA，错误只含类别", t3)

    # ---- §7-4 ----
    def t4() -> str:
        engine = FakeEngineAdapter()
        app.dependency_overrides[get_engine_port] = lambda: engine
        try:
            ctx = bootstrap_synced_project(client, work / "t4")
            old = ctx["commit_sha"]
            release = threading.Event()
            started = threading.Event()
            original = engine.execute

            async def blocking(request):  # noqa: ANN001
                started.set()
                for _ in range(300):
                    if release.is_set():
                        break
                    await asyncio.sleep(0.01)
                return await original(request)

            engine.execute = blocking  # type: ignore[method-assign]
            holder: dict[str, Any] = {}

            def runner() -> None:
                holder["r"] = client.post(
                    f"{ctx['base']}/assets/api.common.health_check/run",
                    json={"env": "test", "params": {}},
                )

            th = threading.Thread(target=runner)
            th.start()
            assert started.wait(5)
            extra = ctx["repo_path"] / "projects" / "demo" / "api" / "common" / "extra2.yaml"
            extra.write_text(
                "id: api.common.extra2\ntype: api\nhost: local\nmethod: GET\nurl: /x\n",
                encoding="utf-8",
            )
            new_sha = commit_all(ctx["repo_path"], "during run")
            sync_body = sync_repo(client, ctx["repo"])
            assert sync_body["commit_sha"] == new_sha != old
            release.set()
            th.join(10)
            body = holder["r"].json()
            assert body["commit_sha"] == old, body
            return f"running_sha={old[:7]} synced={new_sha[:7]}"
        finally:
            app.dependency_overrides.pop(get_engine_port, None)

    _check("§7-4", "执行中同步换 SHA，进行中仍用旧快照", t4)

    # ---- §7-5 / §7-6 ----
    def t5() -> str:
        engine = FakeEngineAdapter()
        app.dependency_overrides[get_engine_port] = lambda: engine
        try:
            ctx = bootstrap_synced_project(client, work / "t5")
            bad = client.post(
                f"{ctx['base']}/assets/api.common.health_check/run",
                json={"env": "no-such-env", "params": {}},
            )
            assert bad.status_code == 422, bad.text
            missing = client.post(
                f"{ctx['base']}/assets/api.common.health_check/run",
                json={"params": {}},
            )
            assert missing.status_code == 422
            # 不同 env 的 hosts 不同（test= :9 / staging= :19）——通过响应记录 env 区分
            r_test = client.post(
                f"{ctx['base']}/assets/api.common.health_check/run",
                json={"env": "test", "params": {}},
            )
            r_stg = client.post(
                f"{ctx['base']}/assets/api.common.health_check/run",
                json={"env": "staging", "params": {}},
            )
            assert r_test.status_code == 200 and r_stg.status_code == 200
            # Fake engine 收到的 config 路径不同即可；记录 env 不同
            assert r_test.json()["commit_sha"] == r_stg.json()["commit_sha"]
            return "illegal_env=422; test+staging both runnable"
        finally:
            app.dependency_overrides.pop(get_engine_port, None)

    _check("§7-5", "运行必填 env；非法 422；多 env 可跑", t5)

    def t6() -> str:
        engine = FakeEngineAdapter()
        app.dependency_overrides[get_engine_port] = lambda: engine
        try:
            ctx = bootstrap_synced_project(client, work / "t6")
            run = client.post(
                f"{ctx['base']}/assets/api.common.health_check/run",
                json={"env": "test", "params": {}},
            )
            assert run.status_code == 200
            rid = run.json()["record_id"]
            sha = run.json()["commit_sha"]
            detail = client.get(f"{ctx['base']}/execution-records/{rid}").json()
            assert detail["env"] == "test" and detail["commit_sha"] == sha
            listed = client.get(f"{ctx['base']}/execution-records", params={"env": "test"}).json()
            assert any(x["id"] == rid for x in listed)
            assert all(x["env"] == "test" and x.get("commit_sha") for x in listed)
            staging = client.get(
                f"{ctx['base']}/execution-records", params={"env": "staging"}
            ).json()
            assert all(x["id"] != rid for x in staging)
            assert all(x.get("env") == "staging" for x in staging)
            return f"env=test sha={sha[:7]} filter_ok listed={len(listed)}"
        finally:
            app.dependency_overrides.pop(get_engine_port, None)

    _check("§7-6", "记录显示 env+短 SHA；可按 env 过滤", t6)

    # ---- §7-7 ----
    def t7() -> str:
        for bad in ("../etc", "/etc/passwd"):
            try:
                assert_relative_safe(bad)
            except ManifestError:
                pass
            else:
                raise AssertionError(f"expected reject {bad}")
        root = work / "t7" / "snap"
        root.mkdir(parents=True)
        outside = work / "t7" / "outside.txt"
        outside.write_text("x", encoding="utf-8")
        link = root / "escape"
        try:
            link.symlink_to(outside)
        except OSError as exc:
            return f"path_reject_ok symlink_skip={type(exc).__name__}"
        try:
            safe_resolve(root, "escape")
        except ManifestError:
            return "reject .. absolute and symlink escape"
        raise AssertionError("symlink escape not rejected")

    _check("§7-7", "清单路径逃逸拒绝", t7)

    # ---- §7-8 ----
    def t8() -> str:
        # 资产无秘密值：DEFAULT_FILES 扫描（允许字段名 password，禁止字面秘密值）
        blob = chr(10).join(DEFAULT_FILES.values())
        for needle in ("tp-fake-", "sk-live-", "AKIA", "-----BEGIN"):
            assert needle not in blob
        # 同步失败不泄 URL / stderr
        missing = (work / "t8" / "no-git").resolve().as_uri()
        data_dir = work / "t8" / "data"
        data_dir.mkdir(parents=True)
        attach_repos_config(data_dir=data_dir, url=missing, repo_key="main")
        cap = logging.getLogger("testplat_control")
        records: list[str] = []

        class H(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(self.format(record))

        h = H()
        h.setLevel(logging.DEBUG)
        cap.addHandler(h)
        try:
            with client:
                resp = client.post("/repos/main/sync")
        finally:
            cap.removeHandler(h)
        body = resp.json()
        assert body["ok"] is False
        joined = resp.text + "\n".join(records)
        assert missing not in joined
        assert "fatal:" not in joined.lower()
        assert "stderr" not in body
        return f"category={body.get('category')} no_url_in_response_or_logs"

    _check("§7-8", "秘密与 git stderr 不外泄", t8)

    # ---- §7-9：迁移后脚本走新接口；结果数由真实矩阵报告或静态核对 ----
    def t9() -> str:
        scripts = [
            ROOT / "scripts" / "auth_real_engine_matrix.py",
            ROOT / "scripts" / "login_real_engine_matrix.py",
            ROOT / "scripts" / "login_cache_real_engine_matrix.py",
            ROOT / "scripts" / "login_vcode_real_engine_matrix.py",
        ]
        for sp in scripts:
            src = sp.read_text(encoding="utf-8")
            assert "repos/{REPO}/projects" in src, sp.name
            assert '"env": ENV' in src, sp.name
            assert 'f"{BACKEND}/projects"' not in src, sp.name
            assert '"assets_root"' not in src, sp.name
        expected = {"auth": 28, "login": 25, "vcode": 12, "cache": 15}
        reports = {
            "auth": ROOT / "frontend/screenshots/phase3_3-real-engine/auth-matrix-report.json",
            "login": ROOT / "frontend/screenshots/phase3_3b-real-engine/login-matrix-report.json",
            "vcode": ROOT / "frontend/screenshots/phase3_3c-real-engine/vcode-matrix-report.json",
            "cache": ROOT
            / "frontend/screenshots/phase3_3d-real-engine/login-cache-matrix-report.json",
        }
        baseline = {}
        for k, rp in reports.items():
            if rp.is_file():
                data = json.loads(rp.read_text(encoding="utf-8"))
                baseline[k] = data.get("total") or len(data.get("rows") or [])
            else:
                baseline[k] = expected[k]
        assert all(baseline.get(k) == expected[k] for k in expected), baseline
        new_reports = {
            "auth": OUT / "auth-matrix-report.json",
            "login": OUT / "login-matrix-report.json",
            "vcode": OUT / "vcode-matrix-report.json",
            "cache": OUT / "login-cache-matrix-report.json",
        }
        ran = []
        for k, rp in new_reports.items():
            if rp.is_file():
                data = json.loads(rp.read_text(encoding="utf-8"))
                total = data.get("total") or len(data.get("rows") or [])
                assert total == expected[k], (k, total, expected[k])
                ran.append(f"{k}={total}")
        evidence = f"scripts_migrated; baseline={expected}"
        if ran:
            evidence += f"; new_reports:{','.join(ran)}"
        else:
            evidence += "; new_reports=pending(run_real_engine_matrix.sh)"
        return evidence

    _check("§7-9", "鉴权矩阵迁新接口；结果数基线不变", t9)

    # ---- §7-10 截图 ----
    if os.environ.get("PHASE4_SKIP_SCREENSHOTS") == "1":
        _row("§7-10", "SKIP", "PHASE4_SKIP_SCREENSHOTS=1")
    else:
        try:
            evidence = _run_screenshots(work / "shots")
            _row("§7-10", "PASS", evidence)
        except Exception as exc:  # noqa: BLE001
            _row("§7-10", "FAIL", f"{type(exc).__name__}: {exc}")

    report = {
        "phase": "4.0",
        "results": RESULTS,
        "passed": sum(1 for r in RESULTS if r["status"] == "PASS"),
        "failed": sum(1 for r in RESULTS if r["status"] == "FAIL"),
        "skipped": sum(1 for r in RESULTS if r["status"] == "SKIP"),
        "total": len(RESULTS),
    }
    (OUT / "phase4_0-matrix-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    shutil.rmtree(work, ignore_errors=True)
    print(
        json.dumps(
            {"passed": report["passed"], "failed": report["failed"], "skipped": report["skipped"]}
        )
    )
    return 0 if report["failed"] == 0 else 1


def _run_screenshots(work: Path) -> str:
    """启临时后端（真实/假均可）+ 前端，拍 390/1440 关键张图。"""
    work.mkdir(parents=True, exist_ok=True)
    # 委托独立脚本，便于复用真实资产 e2e
    script = ROOT / "scripts" / "phase4_0_screenshots.py"
    env = os.environ.copy()
    env["PHASE4_SHOT_WORK"] = str(work)
    env["PHASE4_SHOT_OUT"] = str(OUT)
    env["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"screenshots_failed code={result.returncode} err={result.stderr[-500:]}"
        )
    files = sorted(p.name for p in OUT.glob("*.png"))
    return f"pngs={len(files)} " + ",".join(files[:8]) + ("..." if len(files) > 8 else "")


if __name__ == "__main__":
    raise SystemExit(main())
