"""启动资产仓、Fake 后端和 Vite，拍摄 Phase 4.1a 的 390 / 1440 截图。"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("PHASE4_1A_SHOT_OUT", ROOT / "frontend" / "screenshots" / "phase4_1a"))
WORK = Path(
    os.environ.get(
        "PHASE4_1A_SHOT_WORK",
        str(Path(tempfile.gettempdir()) / "phase4_1a_shot_work"),
    )
)
ASSETS_SHA = "f226b4a88b68fd582f717f5f0ff3652c1f56eb7e"


def _git(args: list[str], cwd: Path) -> None:
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


def _free_port() -> int:
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _wait_http(url: str, deadline: float) -> None:
    import urllib.request

    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except Exception:
            time.sleep(0.4)
    raise RuntimeError(f"服务未就绪: {url}")


def prepare_assets() -> str:
    sys.path.insert(0, str(ROOT))
    from tests.platform_gate import default_assets_checkout

    src = default_assets_checkout(ROOT)
    if not src.is_dir():
        raise RuntimeError("assets_checkout_missing")
    dest = WORK / "assets"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".venv", "__pycache__"))
    _git(["checkout", "-B", "phase4-1a-pin", ASSETS_SHA], cwd=dest)
    _git(["config", "user.email", "shot@example.com"], cwd=dest)
    _git(["config", "user.name", "Shot"], cwd=dest)
    return dest.resolve().as_uri()


def main() -> int:
    from cryptography.fernet import Fernet

    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    OUT.mkdir(parents=True, exist_ok=True)
    url = prepare_assets()
    data_dir = WORK / "data"
    data_dir.mkdir()
    repos_file = WORK / "repos.yaml"
    repos_file.write_text(
        "data_dir: "
        + str(data_dir.resolve())
        + "\nrepos:\n  assets:\n    url: "
        + url
        + "\n    branch: phase4-1a-pin\n",
        encoding="utf-8",
    )
    db = WORK / "control.db"
    backend_port = _free_port()
    frontend_port = _free_port()
    log_dir = WORK / "logs"
    log_dir.mkdir()
    env = os.environ.copy()
    env["TESTPLAT_REPOS_FILE"] = str(repos_file)
    env["DATABASE_URL"] = f"sqlite:///{db}"
    env["TESTPLAT_MASTER_KEY"] = Fernet.generate_key().decode("ascii")
    env["PYTHONUNBUFFERED"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    backend = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "testplat_control.harness_fake:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(backend_port),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=(log_dir / "backend.log").open("w"),
        stderr=subprocess.STDOUT,
    )
    # 与默认 npm run dev 相同，使用 frontend/vite.config.ts（changeOrigin 为 false）。
    front_env = env.copy()
    front_env["VITE_DEV_PROXY_TARGET"] = f"http://127.0.0.1:{backend_port}"
    frontend = subprocess.Popen(
        [
            "pnpm",
            "exec",
            "vite",
            "--host",
            "127.0.0.1",
            "--port",
            str(frontend_port),
            "--strictPort",
        ],
        cwd=str(ROOT / "frontend"),
        env=front_env,
        stdout=(log_dir / "frontend.log").open("w"),
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.time() + 90
        _wait_http(f"http://127.0.0.1:{backend_port}/health", deadline)
        _wait_http(f"http://127.0.0.1:{frontend_port}", deadline)
        shooter = ROOT / "frontend" / "scripts" / "e2e-phase4_1a-screenshots.mjs"
        result = subprocess.run(
            ["pnpm", "exec", "node", str(shooter)],
            cwd=str(ROOT / "frontend"),
            env={
                **env,
                "E2E_BASE_URL": f"http://127.0.0.1:{frontend_port}",
                "E2E_OUT_DIR": str(OUT),
                "E2E_REPO": "assets",
                "E2E_PROJECT": "gsb",
                "E2E_USERNAME": "shotop",
                "E2E_PASSWORD": "shot-pass-1",
                "E2E_ACCOUNT_PASSWORD": "gsb-pass-shot",
            },
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        (log_dir / "shooter.out").write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
        if result.returncode != 0:
            tail = (result.stderr or result.stdout)[-500:]
            raise RuntimeError(f"shooter_failed:{result.returncode}:{tail}")
        print(result.stdout)
        return 0
    finally:
        for proc in (backend, frontend):
            try:
                proc.send_signal(signal.SIGTERM)
            except Exception:
                pass
        for proc in (backend, frontend):
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
