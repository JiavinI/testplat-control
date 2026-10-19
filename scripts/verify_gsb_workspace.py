"""独立 GSB 浏览器验收；真实 Assets/Control/Engine，仅内存库和本机假目标。

bash scripts/dev.sh python scripts/verify_gsb_workspace.py [--serve]
--serve 在浏览器验收后保留隔离预览，Ctrl-C 清理服务和临时 Git 副本。
"""

import argparse
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
    parser.add_argument("--frontend-port", type=int, default=5183)
    parser.add_argument("--backend-port", type=int, default=8013)
    parser.add_argument("--output", type=Path, default=Path("/tmp/testplat-gsb-preview"))
    args = parser.parse_args()
    control = Path(__file__).resolve().parents[1]
    assets = control.parent / "testplat-assets"
    # 在任何应用 import 之前隔离配置，既不读取预览 env.sh，也不继承真实库或主密钥。
    os.environ.update(
        DATABASE_URL="sqlite:///:memory:",
        TESTPLAT_REPOS_FILE="",
        TESTPLAT_MASTER_KEY="",
        TESTPLAT_LEGACY_GIT_CONFIG="false",
    )
    sys.path.insert(0, str(control))

    from http.server import ThreadingHTTPServer

    import uvicorn
    from cryptography.fernet import Fernet
    from fastapi.testclient import TestClient

    from testplat_control.api.platform_session import require_user
    from testplat_control.config import settings
    from testplat_control.main import app
    from testplat_control.services.platform_auth import PlatformPrincipal
    from tests.repo_support import bootstrap_synced_project
    from tests.test_gsb_migration import Handler

    settings.testplat_master_key = Fernet.generate_key().decode()
    # 仅本脚本创建的 loopback 应用使用虚构操作人，不修改正式鉴权实现。
    app.dependency_overrides[require_user] = lambda: PlatformPrincipal(
        id="gsb-preview", username="隔离预览（虚构操作人）"
    )
    target = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    target.events = []
    target_thread = threading.Thread(target=target.serve_forever, daemon=True)
    target_thread.start()
    server = None
    backend_thread = None
    frontend = None
    backend_socket = socket.socket()
    backend_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").unlink(missing_ok=True)
    try:
        with (
            tempfile.TemporaryDirectory(prefix="testplat-gsb-preview-") as temp,
            TestClient(app) as client,
            (args.output / "vite.log").open("w") as vite_log,
        ):
            files = {"testplat.yaml": (assets / "testplat.yaml").read_text()}
            files.update(
                {
                    str(p.relative_to(assets)): p.read_text()
                    for p in (assets / "projects").rglob("*.yaml")
                }
            )
            bootstrap_synced_project(
                client, Path(temp), files, repo_key="isolated", project_key="gsb"
            )
            origin = f"http://127.0.0.1:{target.server_port}"
            for project in ("gsb", "gsb_e3e3"):
                base = f"/repos/isolated/projects/{project}/environments"
                for env in ("test", "pre"):
                    response = client.post(
                        base,
                        json={"env": env, "api_hosts": {"gsb": origin, "unified_login": origin}},
                    )
                    assert response.status_code == 201
                    for account in ("buyer", "alternate"):
                        response = client.post(
                            f"{base}/{env}/accounts",
                            json={
                                "account_name": account,
                                "display_name": account,
                                "login_profile": "gsb_login",
                                "credentials": {
                                    "username": account,
                                    "password": "fake-isolated-password",
                                },
                            },
                        )
                        assert response.status_code == 201
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
                    "npm", "run", "dev", "--", "--host", "127.0.0.1",
                    "--port", str(args.frontend_port), "--strictPort",
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
                    raise RuntimeError("独立前端启动失败，请检查隔离预览 vite.log")
                try:
                    with urlopen(f"{address}/api/auth/me", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("独立预览启动超时")
            completed = subprocess.run(
                ["node", "scripts/e2e-gsb-workspace.mjs"],
                cwd=control / "frontend",
                env={**os.environ, "E2E_BASE_URL": address, "E2E_OUT_DIR": str(args.output)},
                capture_output=True,
                text=True,
                timeout=180,
            )
            if completed.returncode:
                # 不转储页面、HTTP 日志或凭据；截图保存在隔离输出目录。
                print(completed.stdout)
                print(completed.stderr[-3000:])
                raise SystemExit(completed.returncode)
            business = [e for e in target.events if e["path"] != "/site/login"]
            assert len(business) == 6, "阻断用例不应触发额外业务请求"
            assert [e["token"] for e in business[:3]] == [
                "fake-token-go2-buyer", "fake-token-go2-alternate", None,
            ]
            assert business[0]["body"]["productCount"] == 2
            assert business[3]["token"] == "fake-token-e3e3-buyer"
            assert business[4]["body"]["items"][0]["productId"] == "fixture-product"
            assert business[4]["body"]["items"][0]["price"] == 12.5
            assert business[5]["body"]["takeStates"] == ["WAIT"]
            assert business[5]["body"]["errorPrintTag"] == 0
            assert "orderState" not in business[5]["body"]
            result = {
                "real_control_and_engine": True,
                "current_assets": True,
                "database": "isolated-memory",
                "target": "loopback-fake",
                "business_requests": len(business),
                "project_and_identity_headers": "passed",
                "required_and_json_guards": "passed",
                "json_types": "passed",
                "url": f"{address}/apis/isolated/gsb",
                "browser": json.loads(completed.stdout),
            }
            (args.output / "report.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n"
            )
            print(json.dumps(result, ensure_ascii=False), flush=True)
            if args.serve:
                print("隔离预览已保留；Ctrl-C 停止并清理临时数据。", flush=True)
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
        target.shutdown()
        target.server_close()
        target_thread.join(10)


if __name__ == "__main__":
    main()
