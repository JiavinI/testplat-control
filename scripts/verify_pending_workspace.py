"""Run an isolated browser preview for the GO2 schema 0.3 pending candidate.

Usage: bash scripts/dev.sh python scripts/verify_pending_workspace.py [--serve]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import urlopen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--frontend-port", type=int, default=5293)
    parser.add_argument("--backend-port", type=int, default=8223)
    parser.add_argument("--output", type=Path, default=Path("/tmp/testplat-pending-preview"))
    args = parser.parse_args()
    control = Path(__file__).resolve().parents[1]
    assets = control.parent / "testplat-assets" / "examples" / "go2-pending"
    os.environ.update(
        DATABASE_URL="sqlite:///:memory:",
        TESTPLAT_REPOS_FILE="",
        TESTPLAT_MASTER_KEY="",
        TESTPLAT_LEGACY_GIT_CONFIG="false",
    )
    sys.path.insert(0, str(control))

    import httpx
    import uvicorn
    import yaml
    from cryptography.fernet import Fernet
    from fastapi.testclient import TestClient
    from testplat_engine import SingleApiEngine
    from testplat_engine.plugins.httpx_client import HttpxClient

    from testplat_control.api.platform_session import require_user
    from testplat_control.config import settings
    from testplat_control.deps import get_engine_port
    from testplat_control.main import app
    from testplat_control.services.platform_auth import PlatformPrincipal
    from tests.repo_support import bootstrap_synced_project

    # Refuse a collision before starting any preview process.
    reservations: list[socket.socket] = []
    try:
        for port in (args.frontend_port, args.backend_port):
            reservation = socket.socket()
            reservation.bind(("127.0.0.1", port))
            reservations.append(reservation)
    except OSError as exc:
        for reservation in reservations:
            reservation.close()
        raise SystemExit(f"端口已占用，未启动预览: {exc}") from exc
    for reservation in reservations:
        reservation.close()

    settings.testplat_master_key = Fernet.generate_key().decode()
    app.dependency_overrides[require_user] = lambda: PlatformPrincipal(
        id="scenario-preview", username="场景隔离预览（虚构操作人）"
    )
    # Reuse the candidate's maintained fake wire contract; no production config read.
    spec = importlib.util.spec_from_file_location(
        "pending_fixture", assets.parents[1] / "tests/test_go2_pending.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载候选假服务 fixture")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = module.FakeOrderService()
    engine = SingleApiEngine(
        client_factory=lambda: HttpxClient(transport=httpx.MockTransport(target.handler))
    )
    app.dependency_overrides[get_engine_port] = lambda: engine
    backend_socket = socket.socket()
    backend_thread = None
    frontend = None
    server = None
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").unlink(missing_ok=True)
    try:
        with (
            tempfile.TemporaryDirectory(prefix="testplat-scenario-preview-") as temp,
            TestClient(app) as client,
            (args.output / "vite.log").open("w") as vite_log,
        ):
            files = {
                f"projects/demo/{path.relative_to(assets)}": path.read_text()
                for path in (assets / "scenarios").rglob("*.yaml")
            }
            for suffix in module.API_SUFFIXES:
                relative = f"api/gsb/b2/{suffix}.yaml"
                files[f"projects/demo/{relative}"] = (
                    assets.parents[1] / "projects/gsb" / relative
                ).read_text()
            files["testplat.yaml"] = yaml.safe_dump(
                {
                    "schema_version": "1",
                    "projects": {
                        "demo": {
                            "name": "GO2 隔离候选",
                            "assets": "projects/demo",
                            "config": "projects/demo/config",
                            "default_env": "test",
                            "workspace": {
                                "platform": "gsb",
                                "platform_name": "GSB",
                                "project": "go2",
                                "project_name": "GO2",
                            },
                        }
                    },
                }
            )
            files["projects/demo/config/auth/_profiles.yaml"] = yaml.safe_dump(
                {"identities": {"fake_header": {"headers": {"Authorization": "${secret:token}"}}}}
            )
            bootstrap_synced_project(
                client, Path(temp), files, repo_key="isolated", project_key="demo"
            )
            response = client.post(
                "/repos/isolated/projects/demo/environments",
                json={"env": "test", "api_hosts": {"gsb": "http://pending.invalid"}},
            )
            assert response.status_code == 201, response.text
            response = client.post(
                "/repos/isolated/projects/demo/environments/test/accounts",
                json={
                    "account_name": "gsb.b2.primary",
                    "login_profile": "fake_header",
                    "credentials": {"token": module.FAKE_AUTH},
                },
            )
            assert response.status_code == 201, response.text
            backend_socket.bind(("127.0.0.1", args.backend_port))
            backend_socket.listen()
            server = uvicorn.Server(
                uvicorn.Config(app, lifespan="off", log_level="error", access_log=False)
            )
            backend_thread = threading.Thread(
                target=lambda: server.run(sockets=[backend_socket]), daemon=True
            )
            backend_thread.start()
            address = f"http://127.0.0.1:{args.frontend_port}"
            frontend = subprocess.Popen(
                [
                    "npm",
                    "run",
                    "dev",
                    "--",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.frontend_port),
                    "--strictPort",
                ],
                cwd=control / "frontend",
                env={
                    **os.environ,
                    "VITE_DEV_PROXY_TARGET": f"http://127.0.0.1:{args.backend_port}",
                },
                stdout=vite_log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            for _ in range(200):
                if frontend.poll() is not None:
                    raise RuntimeError("独立前端启动失败，请检查输出目录中的 vite.log")
                try:
                    with urlopen(f"{address}/api/auth/me", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("独立预览启动超时")

            browser_reports = []
            for problem, expected_calls, expected_creates in [
                (None, 8, 1),
                ("no_second_sku", 2, 0),
                ("wrong_amount", 8, 1),
            ]:
                target.problem = problem
                target.calls.clear()
                target.created.clear()
                completed = subprocess.run(
                    ["node", "scripts/e2e-pending-workspace.mjs"],
                    cwd=control / "frontend",
                    env={
                        **os.environ,
                        "E2E_BASE_URL": address,
                        "E2E_OUT_DIR": str(args.output),
                        "E2E_PROBLEM": problem or "success",
                    },
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                if completed.returncode:
                    print(completed.stdout)
                    print(completed.stderr[-3000:])
                    raise SystemExit(completed.returncode)
                assert len(target.calls) == expected_calls
                assert len(target.created) == expected_creates
                browser_reports.append(
                    {
                        "problem": problem,
                        "fake_requests": len(target.calls),
                        "browser": json.loads(completed.stdout),
                    }
                )
            result = {
                "real_control_and_local_engine": True,
                "assets": "GO2 pending candidate + seven current API contracts",
                "database": "isolated-memory",
                "target": "httpx.MockTransport (no network)",
                "auth": "ephemeral encrypted fake static header account",
                "url": f"{address}/scenarios/isolated/demo",
                "runs": browser_reports,
            }
            (args.output / "report.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n"
            )
            print(json.dumps(result, ensure_ascii=False), flush=True)
            target.problem = None
            if args.serve:
                print("隔离场景预览已保留；Ctrl-C 停止并清理临时数据。", flush=True)
                while frontend.poll() is None and backend_thread.is_alive():
                    time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        if frontend is not None and frontend.poll() is None:
            import signal

            os.killpg(frontend.pid, signal.SIGTERM)
            frontend.wait(timeout=10)
        if server is not None:
            server.should_exit = True
        if backend_thread is not None:
            backend_thread.join(10)
        backend_socket.close()
        app.dependency_overrides.pop(require_user, None)
        app.dependency_overrides.pop(get_engine_port, None)


if __name__ == "__main__":
    main()
