"""Run an isolated browser preview for the schema 0.3 scenario example.

Usage: bash scripts/dev.sh python scripts/verify_scenario_workspace.py [--serve]
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen


class EchoHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length))
        self.server.events.append(payload)  # type: ignore[attr-defined]
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--frontend-port", type=int, default=5283)
    parser.add_argument("--backend-port", type=int, default=8213)
    parser.add_argument("--output", type=Path, default=Path("/tmp/testplat-scenario-preview"))
    args = parser.parse_args()
    control = Path(__file__).resolve().parents[1]
    assets = control.parent / "testplat-assets" / "examples" / "scenario-parameters"
    os.environ.update(
        DATABASE_URL="sqlite:///:memory:",
        TESTPLAT_REPOS_FILE="",
        TESTPLAT_MASTER_KEY="",
        TESTPLAT_LEGACY_GIT_CONFIG="false",
    )
    sys.path.insert(0, str(control))

    import uvicorn
    from cryptography.fernet import Fernet
    from fastapi.testclient import TestClient

    from testplat_control.api.platform_session import require_user
    from testplat_control.config import settings
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
    target = ThreadingHTTPServer(("127.0.0.1", 0), EchoHandler)
    target.events = []
    target_thread = threading.Thread(target=target.serve_forever, daemon=True)
    target_thread.start()
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
                for path in assets.rglob("*")
                if path.is_file() and path.name != "README.md"
            }
            files["testplat.yaml"] = (
                'schema_version: "1"\nprojects:\n  demo:\n'
                "    name: 场景参数隔离示例\n    assets: projects/demo\n"
                "    config: projects/demo/config\n    default_env: test\n"
            )
            files["projects/demo/config/.gitkeep"] = ""
            bootstrap_synced_project(
                client, Path(temp), files, repo_key="isolated", project_key="demo"
            )
            origin = f"http://127.0.0.1:{target.server_port}"
            response = client.post(
                "/repos/isolated/projects/demo/environments",
                json={"env": "test", "api_hosts": {"scenario_fake": origin}},
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

            completed = subprocess.run(
                ["node", "scripts/e2e-scenario-workspace.mjs"],
                cwd=control / "frontend",
                env={**os.environ, "E2E_BASE_URL": address, "E2E_OUT_DIR": str(args.output)},
                capture_output=True,
                text=True,
                timeout=180,
            )
            if completed.returncode:
                print(completed.stdout)
                print(completed.stderr[-3000:])
                raise SystemExit(completed.returncode)
            expected = [
                {"enabled": True, "item": {"quantity": 1}},
                {"enabled": True, "item": {"quantity": 2}},
                {
                    "first": {"enabled": True, "item": {"quantity": 1}},
                    "second": {"enabled": True, "item": {"quantity": 2}},
                },
            ]
            assert [event["value"] for event in target.events] == expected
            result = {
                "real_control_and_local_engine": True,
                "assets": "schema-0.3 scenario example",
                "database": "isolated-memory",
                "target": "loopback-fake",
                "business_requests": len(target.events),
                "flow_call_isolation_and_output_transfer": "passed",
                "url": f"{address}/scenarios/isolated/demo",
                "browser": json.loads(completed.stdout),
            }
            (args.output / "report.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n"
            )
            print(json.dumps(result, ensure_ascii=False), flush=True)
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
        target.shutdown()
        target.server_close()
        target_thread.join(10)


if __name__ == "__main__":
    main()
