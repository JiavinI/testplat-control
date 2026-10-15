"""启动临时 file:// 仓库 + Fake harness 后端 + Vite，调用 Playwright 截图。"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("PHASE4_SHOT_OUT", ROOT / "frontend" / "screenshots" / "phase4_0"))
WORK = Path(os.environ.get("PHASE4_SHOT_WORK", ROOT / ".phase4_shot_work"))
OUT.mkdir(parents=True, exist_ok=True)
WORK.mkdir(parents=True, exist_ok=True)


def _git(args: list[str], cwd: Path) -> None:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    r = subprocess.run(
        ["git", *args], cwd=str(cwd), env=env, capture_output=True, timeout=60, check=False
    )
    if r.returncode != 0:
        raise RuntimeError(f"git_failed:{args[0]}")


def _free_port() -> int:
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def build_repo() -> tuple[Path, str]:
    sys.path.insert(0, str(ROOT))
    from tests.repo_support import DEFAULT_FILES, write_tree

    repo = WORK / "shot-assets"
    if repo.exists():
        shutil.rmtree(repo)
    repo.mkdir(parents=True)
    files = dict(DEFAULT_FILES)
    write_tree(repo, files)
    _git(["init", "-b", "main"], cwd=repo)
    _git(["config", "user.email", "shot@example.com"], cwd=repo)
    _git(["config", "user.name", "Shot"], cwd=repo)
    _git(["add", "-A"], cwd=repo)
    _git(["commit", "-m", "shot assets"], cwd=repo)
    return repo, repo.resolve().as_uri()


def main() -> int:
    repo, url = build_repo()
    data_dir = WORK / "data"
    data_dir.mkdir(exist_ok=True)
    repos_file = WORK / "repos.yaml"
    repos_file.write_text(
        f"data_dir: {data_dir.resolve()}\nrepos:\n  main:\n    url: {url}\n    branch: main\n",
        encoding="utf-8",
    )
    db = WORK / "control.db"
    if db.exists():
        db.unlink()

    backend_port = _free_port()
    frontend_port = _free_port()
    log_dir = WORK / "logs"
    log_dir.mkdir(exist_ok=True)

    env = os.environ.copy()
    env["TESTPLAT_REPOS_FILE"] = str(repos_file)
    env["MATRIX_SQLITE_PATH"] = str(db)
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
    pids = [backend, frontend]
    try:
        import urllib.request

        deadline = time.time() + 90
        while time.time() < deadline:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{backend_port}/health", timeout=1)
                urllib.request.urlopen(f"http://127.0.0.1:{frontend_port}", timeout=1)
                break
            except Exception:
                time.sleep(0.4)
        else:
            raise RuntimeError("services_start_timeout")

        # 确保已同步（启动 lifespan 会同步；再点一次）
        import urllib.request

        req = urllib.request.Request(
            f"http://127.0.0.1:{backend_port}/repos/main/sync", method="POST"
        )
        urllib.request.urlopen(req, timeout=60).read()

        shooter = ROOT / "frontend" / "scripts" / "e2e-phase4_0-screenshots.mjs"
        r = subprocess.run(
            ["pnpm", "exec", "node", str(shooter)],
            cwd=str(ROOT / "frontend"),
            env={
                **env,
                "E2E_BASE_URL": f"http://127.0.0.1:{frontend_port}",
                "E2E_OUT_DIR": str(OUT),
                "E2E_REPO": "main",
                "E2E_PROJECT": "demo",
                "E2E_BACKEND": f"http://127.0.0.1:{backend_port}",
            },
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        (log_dir / "shooter.out").write_text(r.stdout + "\n" + r.stderr, encoding="utf-8")
        if r.returncode != 0:
            raise RuntimeError(f"shooter_failed:{r.returncode}:{r.stderr[-400:]}")
        print(r.stdout)
        return 0
    finally:
        for p in pids:
            try:
                p.send_signal(signal.SIGTERM)
            except Exception:
                pass
        for p in pids:
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()


if __name__ == "__main__":
    raise SystemExit(main())
