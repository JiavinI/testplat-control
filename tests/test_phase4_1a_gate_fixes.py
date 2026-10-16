"""审查打回：调用者库隔离，以及 LEAK 必须抓住业务 token 和新会话。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
KEEP_PASSWORD = "keeper-secret-1"
TABLES = (
    "platform_users",
    "projects",
    "project_environments",
    "test_accounts",
    "config_changes",
)

_SPEC = importlib.util.spec_from_file_location(
    "phase4_1a_matrix_under_test",
    ROOT / "scripts" / "phase4_1a_matrix.py",
)
assert _SPEC is not None and _SPEC.loader is not None
MATRIX = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(MATRIX)


def _assets() -> Path | None:
    configured = os.environ.get("PHASE4_ASSETS_SRC")
    if configured and Path(configured).is_dir():
        return Path(configured)
    sibling = ROOT.parent / "testplat-assets"
    home = Path.home() / "testplat-assets"
    for candidate in (sibling, home):
        if candidate.is_dir():
            return candidate
    return None


def _child_env(db_path: Path, key: str) -> dict[str, str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env["TESTPLAT_MASTER_KEY"] = key
    env.pop("TESTPLAT_REPOS_FILE", None)
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(ROOT / "src"), env.get("PYTHONPATH", "")) if part
    )
    return env


def _run_script(
    script: Path, env: dict[str, str], timeout: int
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


SEED = """
import json
from datetime import UTC, datetime

from sqlalchemy import text

from testplat_control.database.models import Project, Repo
from testplat_control.database.session import SessionLocal
from testplat_control.services.crypto import decrypt_credentials
from testplat_control.services.environment_store import create_account, create_environment
from testplat_control.services.platform_auth import register_user

now = datetime.now(UTC).replace(tzinfo=None)
with SessionLocal() as db:
    db.add(Repo(key="main", branch="main"))
    db.commit()
    db.add(
        Project(
            id="main/demo",
            repo="main",
            project_key="demo",
            name="Demo",
            envs=[],
            archived=False,
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()
    register_user(db, "keeper", "keeper-pass-1")
    create_environment(
        db,
        project_id="main/demo",
        env="test",
        api_hosts={"local": "http://127.0.0.1:9"},
        timeout_seconds=None,
        case_params={},
        enabled=True,
        operator="keeper",
    )
    create_account(
        db,
        project_id="main/demo",
        env="test",
        account_name="gsb",
        display_name="采购员",
        business_role=None,
        login_profile="gsb_login",
        credentials={"username": "buyer-keep", "password": "keeper-secret-1"},
        enabled=True,
        operator="keeper",
    )
print("seeded")
"""

SNAPSHOT = """
import json

from sqlalchemy import text

from testplat_control.database.session import SessionLocal
from testplat_control.services.crypto import decrypt_credentials

tables = (
    "platform_users",
    "projects",
    "project_environments",
    "test_accounts",
    "config_changes",
)
with SessionLocal() as db:
    counts = {
        table: db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() for table in tables
    }
    ciphers = [
        row[0]
        for row in db.execute(
            text("SELECT encrypted_credentials FROM test_accounts ORDER BY account_name")
        )
    ]
decrypt_ok = bool(ciphers) and all(
    decrypt_credentials(item).get("password") == "keeper-secret-1" for item in ciphers
)
print(json.dumps({"counts": counts, "ciphers": ciphers, "decrypt_ok": decrypt_ok}))
"""


def _snapshot(db_path: Path, key: str, tmp_path: Path) -> dict:
    script = tmp_path / "snapshot_caller_db.py"
    script.write_text(SNAPSHOT, encoding="utf-8")
    result = _run_script(script, _child_env(db_path, key), timeout=60)
    assert result.returncode == 0, result.stderr[-400:]
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert KEEP_PASSWORD not in result.stdout
    return payload


def _seed(db_path: Path, key: str, tmp_path: Path) -> dict:
    script = tmp_path / "seed_caller_db.py"
    script.write_text(SEED, encoding="utf-8")
    result = _run_script(script, _child_env(db_path, key), timeout=60)
    assert result.returncode == 0, result.stderr[-400:]
    assert KEEP_PASSWORD not in result.stdout
    return _snapshot(db_path, key, tmp_path)


@pytest.fixture
def matrix():
    MATRIX.ISSUED_BUSINESS_TOKENS.clear()
    MATRIX.SESSION_COOKIES.clear()
    MATRIX.SECRETS[:] = [
        MATRIX.PLATFORM_PASSWORD,
        MATRIX.PASS_A,
        MATRIX.PASS_B,
        MATRIX.NEW_PASS,
        MATRIX.FALLBACK,
    ]
    return MATRIX


def test_scan_rejects_business_token_and_new_session(matrix) -> None:
    token = matrix.token_for(matrix.PASS_A)
    first = "session-cookie-first"
    second = "session-cookie-after-relogin"
    matrix.note_business_token(token)
    matrix.note_session(first)
    matrix.note_session(second)
    matrix.scan_secret_carriers(logs="clean", sqlite_blob=b"clean", traffic=[])
    with pytest.raises(AssertionError, match="^log$"):
        matrix.scan_secret_carriers(logs=f"engine {token}", sqlite_blob=b"", traffic=[])
    with pytest.raises(AssertionError, match="^log$"):
        matrix.scan_secret_carriers(logs=f"engine {second}", sqlite_blob=b"", traffic=[])
    with pytest.raises(AssertionError, match="^sqlite$"):
        matrix.scan_secret_carriers(logs="", sqlite_blob=token.encode(), traffic=[])
    with pytest.raises(AssertionError, match="^response$"):
        matrix.scan_secret_carriers(
            logs="",
            sqlite_blob=b"",
            traffic=[("/repos/main/projects/demo/run", 200, token)],
        )
    matrix.scan_secret_carriers(
        logs="",
        sqlite_blob=b"",
        traffic=[("/repos/main/projects/demo/accounts/gsb/credentials", 200, matrix.PASS_A)],
    )
    with pytest.raises(AssertionError, match="^response$"):
        matrix.scan_secret_carriers(
            logs="",
            sqlite_blob=b"",
            traffic=[("/repos/main/projects/demo/accounts/gsb/credentials", 200, second)],
        )


def test_inject_hook_is_off_unless_requested(matrix, monkeypatch: pytest.MonkeyPatch) -> None:
    token = matrix.token_for(matrix.PASS_A)
    session = "session-cookie-after-relogin"
    matrix.note_business_token(token)
    matrix.note_session(session)
    monkeypatch.delenv("PHASE4_1A_INJECT_LEAK", raising=False)
    records: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    logger = logging.getLogger("testplat_engine")
    handler = Capture()
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    previous_propagate = logger.propagate
    previous_level = logger.level
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    try:
        matrix.inject_leak_markers()
        assert records == []
        monkeypatch.setenv("PHASE4_1A_INJECT_LEAK", "1")
        matrix.inject_leak_markers()
    finally:
        logger.propagate = previous_propagate
        logger.setLevel(previous_level)
        logger.removeHandler(handler)
    assert records[0] == token and records[1] == session, "inject"
    with pytest.raises(AssertionError, match="^log$"):
        matrix.scan_secret_carriers(logs="\n".join(records), sqlite_blob=b"", traffic=[])


def test_child_session_hook_is_off_unless_requested(
    matrix, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = "child-restart-session-cookie"
    matrix.note_session(session)
    monkeypatch.delenv("PHASE4_1A_INJECT_CHILD_LEAK", raising=False)
    records: list[str] = []
    handler, watched = matrix._watch_secret_loggers(records)
    try:
        matrix.inject_child_session_leak()
        assert records == []
        monkeypatch.setenv("PHASE4_1A_INJECT_CHILD_LEAK", "1")
        matrix.inject_child_session_leak()
    finally:
        for logger, propagate, level in watched:
            logger.removeHandler(handler)
            logger.propagate = propagate
            logger.setLevel(level)
    assert records == [session], "inject"
    with pytest.raises(AssertionError, match="^log$"):
        matrix.scan_secret_carriers(logs="\n".join(records), sqlite_blob=b"", traffic=[])
    rendered = matrix.redact(json.dumps({"ok": False, "carrier": "log", "sessions": 1}))
    assert session not in rendered


def test_e2e_keeps_caller_database_and_original_key(tmp_path: Path) -> None:
    assets = _assets()
    if assets is None:
        pytest.skip("资产仓不在")
    db_path = tmp_path / "configured.db"
    key = Fernet.generate_key().decode("ascii")
    before = _seed(db_path, key, tmp_path)
    env = _child_env(db_path, key)
    env["PHASE4_E2E_OUT"] = str(tmp_path / "e2e-real-assets.json")
    env["PHASE4_E2E_HOST_OVERRIDE"] = "http://127.0.0.1:1"
    env["PHASE4_ASSETS_SRC"] = str(assets)
    result = _run_script(ROOT / "scripts" / "phase4_0_e2e_real_assets.py", env, timeout=180)
    assert result.returncode == 0, result.stderr[-500:]
    after = _snapshot(db_path, key, tmp_path)
    assert after["counts"] == before["counts"]
    assert after["ciphers"] == before["ciphers"]
    assert after["decrypt_ok"] is True
    written = (tmp_path / "e2e-real-assets.json").read_text(encoding="utf-8")
    assert KEEP_PASSWORD not in written
    assert key not in written
    assert "e2e-pass-1" not in written
    assert "gsb-pass-e2e" not in written


def test_phase4_0_matrix_does_not_write_caller_database(tmp_path: Path) -> None:
    db_path = tmp_path / "configured.db"
    key = Fernet.generate_key().decode("ascii")
    before = _seed(db_path, key, tmp_path)
    env = _child_env(db_path, key)
    env["PHASE4_SKIP_SCREENSHOTS"] = "1"
    env["PHASE4_MATRIX_OUT"] = str(tmp_path / "phase4_0_out")
    result = _run_script(ROOT / "scripts" / "phase4_0_matrix.py", env, timeout=180)
    assert result.returncode == 0, result.stderr[-500:]
    after = _snapshot(db_path, key, tmp_path)
    assert after["counts"] == before["counts"]
    assert after["ciphers"] == before["ciphers"]
    assert after["decrypt_ok"] is True
    assert KEEP_PASSWORD not in result.stdout


def test_injected_business_token_fails_matrix_leak(tmp_path: Path) -> None:
    assets = _assets()
    if assets is None:
        pytest.skip("资产仓不在")
    env = os.environ.copy()
    env["PHASE4_1A_INJECT_LEAK"] = "1"
    env["PHASE4_1A_OUT"] = str(tmp_path)
    env["PHASE4_ASSETS_SRC"] = str(assets)
    env.pop("DATABASE_URL", None)
    result = _run_script(ROOT / "scripts" / "phase4_1a_matrix.py", env, timeout=180)
    assert result.returncode != 0
    report_path = tmp_path / "phase4_1a-matrix-report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    failed = [row["item"] for row in payload["results"] if row["status"] != "PASS"]
    assert failed == ["LEAK"]
    leaked = [row for row in payload["results"] if row["item"] == "LEAK"][0]
    assert leaked["status"] == "FAIL"
    text = report_path.read_text(encoding="utf-8") + result.stdout + result.stderr
    for password in ("pw-project-a-91", "pw-project-b-82", "pw-project-a-new7", "matrix-pass-1"):
        assert password not in text
        token = "tok-" + hashlib.sha256(password.encode("utf-8")).hexdigest()[:12]
        assert token not in text


def test_restart_child_session_leak_fails_matrix(tmp_path: Path) -> None:
    assets = _assets()
    if assets is None:
        pytest.skip("资产仓不在")
    env = os.environ.copy()
    env["PHASE4_1A_INJECT_CHILD_LEAK"] = "1"
    env.pop("PHASE4_1A_INJECT_LEAK", None)
    env["PHASE4_1A_OUT"] = str(tmp_path)
    env["PHASE4_ASSETS_SRC"] = str(assets)
    env.pop("DATABASE_URL", None)
    result = _run_script(ROOT / "scripts" / "phase4_1a_matrix.py", env, timeout=180)
    assert result.returncode != 0
    report_path = tmp_path / "phase4_1a-matrix-report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    failed = [row["item"] for row in payload["results"] if row["status"] != "PASS"]
    assert failed == ["A12"]
    restart = [row for row in payload["results"] if row["item"] == "A12"][0]
    assert restart["evidence"] == "AssertionError: child_exit"
    leak = [row for row in payload["results"] if row["item"] == "LEAK"][0]
    assert leak["status"] == "PASS"
    text = report_path.read_text(encoding="utf-8") + result.stdout + result.stderr
    for password in ("pw-project-a-91", "pw-project-b-82", "pw-project-a-new7", "matrix-pass-1"):
        assert password not in text
        token = "tok-" + hashlib.sha256(password.encode("utf-8")).hexdigest()[:12]
        assert token not in text
    assert "child-restart-session-cookie" not in text
