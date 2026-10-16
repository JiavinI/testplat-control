#!/usr/bin/env python3
"""默认 ``npm run dev`` 下验收注册、登录、保存环境和注销。

后端 Origin 校验保持原样。本脚本只起独立临时库，不导入 Control。
报告只写状态码，不写密码、主密钥或会话 token。
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(
    os.environ.get(
        "PHASE4_VITE_LOGIN_OUT",
        ROOT / "frontend" / "screenshots" / "phase4_1a" / "vite-login-check.json",
    )
)
DIRECT_USER = "vitegate"
DIRECT_PASS = "vite-pass-1"
BROWSER_USER = "vitebrow"
BROWSER_PASS = "vite-pass-2"


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
    raise RuntimeError("服务未就绪")


def _git(args: list[str], cwd: Path) -> None:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git_failed:{args[0]}")


def _init_repo(repo: Path) -> str:
    repo.mkdir(parents=True)
    files = {
        "testplat.yaml": """\
schema_version: "1"
projects:
  demo:
    name: Demo
    assets: projects/demo
    config: projects/demo/config
    default_env: test
""",
        "projects/demo/api/common/health_check.yaml": """\
id: api.common.health_check
type: api
name: 健康检查
host: local
method: GET
url: /health
request: {}
success:
  status_code: 200
""",
        "projects/demo/config/envs/test.yaml": """\
api_hosts:
  local: http://127.0.0.1:9
""",
    }
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(["init", "-b", "main"], cwd=repo)
    _git(["config", "user.email", "vite@example.com"], cwd=repo)
    _git(["config", "user.name", "Vite"], cwd=repo)
    _git(["add", "-A"], cwd=repo)
    _git(["commit", "-m", "vite login fixture"], cwd=repo)
    return repo.resolve().as_uri()


def _redact(text: str, secrets: list[str]) -> str:
    cleaned = text
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "[redacted]")
    return cleaned


def _stop(proc: subprocess.Popen[str] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.send_signal(signal.SIGTERM)
    except Exception:
        return
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="phase4_vite_login_"))
    master = Fernet.generate_key().decode("ascii")
    secrets = [DIRECT_PASS, BROWSER_PASS, master]
    report: dict[str, object] = {
        "vite_entry": "npm run dev",
        "config": "frontend/vite.config.ts",
        "change_origin": False,
    }
    backend: subprocess.Popen[str] | None = None
    frontend: subprocess.Popen[str] | None = None
    try:
        url = _init_repo(work / "repo")
        data_dir = work / "data"
        data_dir.mkdir()
        repos_file = work / "repos.yaml"
        repos_file.write_text(
            "data_dir: "
            + str(data_dir.resolve())
            + "\nrepos:\n  main:\n    url: "
            + url
            + "\n    branch: main\n",
            encoding="utf-8",
        )
        backend_port = _free_port()
        frontend_port = _free_port()
        log_dir = work / "logs"
        log_dir.mkdir()
        env = os.environ.copy()
        env["DATABASE_URL"] = f"sqlite:///{work / 'control.db'}"
        env["TESTPLAT_MASTER_KEY"] = master
        env["TESTPLAT_REPOS_FILE"] = str(repos_file)
        env["PYTHONUNBUFFERED"] = "1"
        env["GIT_TERMINAL_PROMPT"] = "0"
        backend = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "testplat_control.main:app",
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
                "npm",
                "run",
                "dev",
                "--",
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
        deadline = time.time() + 90
        _wait_http(f"http://127.0.0.1:{backend_port}/health", deadline)
        _wait_http(f"http://127.0.0.1:{frontend_port}", deadline)
        origin = f"http://127.0.0.1:{frontend_port}"
        with httpx.Client(timeout=15) as client:
            direct = client.post(
                f"http://127.0.0.1:{backend_port}/auth/register",
                json={"username": DIRECT_USER, "password": DIRECT_PASS},
            )
            report["direct_register"] = direct.status_code
            proxied = client.post(
                f"{origin}/api/auth/login",
                json={"username": DIRECT_USER, "password": DIRECT_PASS},
                headers={"Origin": origin},
            )
            report["default_vite_login"] = proxied.status_code
            mismatched = client.post(
                f"{origin}/api/auth/login",
                json={"username": DIRECT_USER, "password": DIRECT_PASS},
                headers={"Origin": "http://127.0.0.1:1"},
            )
            report["mismatched_origin"] = mismatched.status_code
        browser_out = work / "browser.json"
        shooter_script = ROOT / "frontend" / "scripts" / "e2e-vite-login-check.mjs"
        shooter = subprocess.run(
            ["pnpm", "exec", "node", str(shooter_script)],
            cwd=str(ROOT / "frontend"),
            env={
                **front_env,
                "E2E_BASE_URL": origin,
                "E2E_OUT": str(browser_out),
                "E2E_USERNAME": BROWSER_USER,
                "E2E_PASSWORD": BROWSER_PASS,
                "E2E_REPO": "main",
                "E2E_PROJECT": "demo",
            },
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        browser: dict[str, object] = {}
        if browser_out.is_file():
            browser = json.loads(browser_out.read_text(encoding="utf-8"))
        for key in (
            "browser_register",
            "browser_login",
            "browser_config_save",
            "browser_logout",
        ):
            report[key] = browser.get(key)
        if shooter.returncode != 0:
            detail = browser.get("error") or _redact(
                (shooter.stderr or shooter.stdout)[-400:], secrets
            )
            report["browser_error"] = _redact(str(detail), secrets)
        expected = {
            "direct_register": 200,
            "default_vite_login": 200,
            "mismatched_origin": 403,
            "browser_register": 200,
            "browser_login": 200,
            "browser_config_save": 201,
            "browser_logout": 204,
        }
        report["ok"] = shooter.returncode == 0 and all(
            report.get(key) == status for key, status in expected.items()
        )
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ok": report["ok"], "out": str(OUT)}, ensure_ascii=False))
        return 0 if report["ok"] else 1
    except Exception as exc:  # noqa: BLE001
        report["error"] = _redact(f"{type(exc).__name__}: {exc}", secrets)[:300]
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ok": False, "error": report["error"]}, ensure_ascii=False))
        return 1
    finally:
        _stop(frontend)
        _stop(backend)


if __name__ == "__main__":
    raise SystemExit(main())
