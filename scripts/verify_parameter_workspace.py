"""隔离浏览器＋真实 Control／Engine＋本机假目标参数保存验收。

Control 目录：bash scripts/dev.sh python scripts/verify_parameter_workspace.py。
需已有 Vite（默认 5173）；全部应用 API 转到独立内存库，不读预览数据或账号。
"""

import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


def main() -> None:
    control = Path(__file__).resolve().parents[1]
    # 必须先覆盖所有持久化配置再导入 Control，不能从 .env 继承真实数据。
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    os.environ["TESTPLAT_REPOS_FILE"] = ""
    os.environ["TESTPLAT_MASTER_KEY"] = ""
    os.environ["TESTPLAT_LEGACY_GIT_CONFIG"] = "false"
    sys.path.insert(0, str(control))

    import uvicorn
    from fastapi.testclient import TestClient

    from testplat_control.api.platform_session import require_user
    from testplat_control.main import app
    from testplat_control.services.platform_auth import PlatformPrincipal
    from tests.repo_support import bootstrap_synced_project
    from tests.test_parameter_sets import _prepare
    from tests.test_phase4_1a_fake_target import _Capture, _project_files, _start, _stop

    app.dependency_overrides[require_user] = lambda: PlatformPrincipal(
        id="fixture", username="fixture-user"
    )
    login, business = _start(_Capture()), _start(_Capture())
    server = None
    thread = None
    try:
        with (
            tempfile.TemporaryDirectory(prefix="testplat-fullstack-") as temp,
            TestClient(app) as client,
            socket.socket() as fixture_socket,
        ):
            ctx = bootstrap_synced_project(
                client, Path(temp), _project_files(), repo_key="demo", project_key="demo"
            )
            _prepare({"ctx": ctx, "client": client, "login": login, "business": business})
            fixture_socket.bind(("127.0.0.1", 0))
            fixture_socket.listen()
            address = f"http://127.0.0.1:{fixture_socket.getsockname()[1]}"
            server = uvicorn.Server(
                uvicorn.Config(app, lifespan="off", log_level="error", access_log=False)
            )
            thread = threading.Thread(
                target=lambda: server.run(sockets=[fixture_socket]), daemon=True
            )
            thread.start()
            for _ in range(200):
                if server.started:
                    break
                time.sleep(0.05)
            if not server.started:
                raise RuntimeError("Isolated fixture server failed to start")
            try:
                completed = subprocess.run(
                    ["node", "scripts/e2e-parameter-storage-real.mjs"],
                    cwd=str(control / "frontend"),
                    env={**os.environ, "E2E_PARAMETER_FIXTURE_URL": address},
                    capture_output=True, text=True, timeout=120,
                )
            finally:
                server.should_exit = True
                thread.join(10)
            print(completed.stdout)
            if completed.returncode:
                print(completed.stderr)
                raise SystemExit(completed.returncode)
    finally:
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(10)
        app.dependency_overrides.pop(require_user, None)
        _stop(login)
        _stop(business)


if __name__ == "__main__":
    main()
