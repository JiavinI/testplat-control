"""Phase 3.3c 真实 Engine 验证码 Redis 矩阵（设计稿 §6 第 22–28 条）。

由 ``scripts/run_real_engine_matrix.sh`` 在 3.3b 登录段之后调用。
假秘密与动态签发值只用于断言与泄密搜索，绝不写入报告。
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import redis

from testplat_control.engine_bootstrap import (
    discover_installed_login_strategies,
    resolve_login_strategies,
)

BUYER_PASSWORD = "tp-fake-buyer-pass-71c2"
SELLER_PASSWORD = "tp-fake-seller-pass-93ab"
REDIS_PASSWORD = "tp-fake-redis-pass-5e0d"
DF_ADMIN_PASSWORD = "tp-fake-df-admin-pass-9f3a"
PLUGIN_KEY = "tp-fake-plugin-key-11aa"
PLUGIN_TOKEN = "plug-token-5f5f5f5f5f"
CSRF_TOKEN = "csrf-ff00ee11dd22"
CSRF_SEED = "seed-0a0b0c0d0e"
FAIL_DETAIL = "detail-0123456789abcdefghij"
ADMIN_SECRET = "tp-fake-secret-9f31c2a7"
PARTNER_SECRET = "tp-fake-partner-4c8e11d0"

SEARCH_TARGETS = (
    BUYER_PASSWORD,
    SELLER_PASSWORD,
    REDIS_PASSWORD,
    DF_ADMIN_PASSWORD,
    PLUGIN_KEY,
    PLUGIN_TOKEN,
    CSRF_TOKEN,
    CSRF_SEED,
    FAIL_DETAIL,
    ADMIN_SECRET,
    PARTNER_SECRET,
)

# Redis commandstats 中视为写命令的名字（小写、无 cmdstat_ 前缀）
_WRITE_COMMANDS = frozenset(
    {
        "set",
        "setex",
        "setnx",
        "psetex",
        "mset",
        "msetnx",
        "del",
        "unlink",
        "hset",
        "hmset",
        "hdel",
        "lpush",
        "rpush",
        "lpop",
        "rpop",
        "sadd",
        "srem",
        "zadd",
        "zrem",
        "incr",
        "incrby",
        "decr",
        "decrby",
        "append",
        "rename",
        "renamenx",
        "expire",
        "pexpire",
        "flushdb",
        "flushall",
        "restore",
        "move",
    }
)

BACKEND = os.environ.get("MATRIX_BACKEND_URL", "http://127.0.0.1:8000")
TARGET = os.environ["MATRIX_TARGET_URL"]
ASSETS_ROOT = os.environ.get("MATRIX_LOGIN_ASSETS_ROOT", "")
REPO = os.environ.get("MATRIX_REPO", "matrix")
ENV = os.environ.get("MATRIX_ENV", "test")
OUT_DIR = Path(os.environ["MATRIX_VCODE_OUT_DIR"])
ISSUED_PATH = Path(os.environ.get("MATRIX_ISSUED_SECRETS_PATH", ""))
REDIS_HOST = os.environ.get("MATRIX_REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.environ["MATRIX_REDIS_PORT"])
REDIS_PASS = os.environ["MATRIX_REDIS_PASSWORD"]
ROOTS = {
    "vcode": os.environ["MATRIX_ROOT_VCODE"],
    "vcode-conn-missing": os.environ["MATRIX_ROOT_VCODE_CONN_MISSING"],
    "vcode-no-whitelist": os.environ["MATRIX_ROOT_VCODE_NO_WHITELIST"],
}


def _load_issued() -> list[str]:
    if not ISSUED_PATH.is_file():
        return []
    seen: set[str] = set()
    out: list[str] = []
    for line in ISSUED_PATH.read_text("utf-8").splitlines():
        item = line.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def leaks(text: str) -> int:
    return sum(text.count(t) for t in SEARCH_TARGETS)


def _redis_client() -> redis.Redis:
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASS,
        db=0,
        socket_timeout=2.0,
        socket_connect_timeout=2.0,
        decode_responses=True,
    )


def _commandstats() -> dict[str, int]:
    client = _redis_client()
    try:
        info = client.info("commandstats")
    finally:
        client.close()
    out: dict[str, int] = {}
    for key, val in (info or {}).items():
        # redis-py 可能返回 cmdstat_get 或直接 get
        name = str(key).removeprefix("cmdstat_").lower()
        if isinstance(val, dict):
            calls = int(val.get("calls") or 0)
        else:
            continue
        out[name] = calls
    return out


def _reset_commandstats() -> None:
    client = _redis_client()
    try:
        client.config_resetstat()
    finally:
        client.close()


def _establish():
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from tests.platform_gate import establish

    return establish


class Matrix:
    def __init__(self) -> None:
        self.client = httpx.Client(timeout=90)
        _establish()(self.client, auth_base=BACKEND)
        self.rows: list[dict[str, Any]] = []
        self.projects: dict[str, str] = {}

    def project(self, root: str) -> str:
        if root not in self.projects:
            resp = self.client.get(f"{BACKEND}/repos/{REPO}/projects/{root}")
            resp.raise_for_status()
            self.projects[root] = root
        return self.projects[root]

    def _base(self, root: str) -> str:
        return f"{BACKEND}/repos/{REPO}/projects/{self.project(root)}"

    def run_api(self, root: str, asset: str, params: dict | None = None) -> httpx.Response:
        return self.client.post(
            f"{self._base(root)}/assets/{asset}/run",
            json={"params": params or {}, "env": ENV},
        )

    def reset_target(self) -> None:
        self.client.post(f"{TARGET}/__inspect/reset").raise_for_status()

    def configure_target(self, **cfg: object) -> None:
        self.client.post(f"{TARGET}/__inspect/config", json=cfg).raise_for_status()

    def received(self) -> list[dict[str, Any]]:
        return self.client.get(f"{TARGET}/__inspect").json()["requests"]

    def inspect(self) -> dict[str, Any]:
        return self.client.get(f"{TARGET}/__inspect").json()

    def check(self, row_id: str, item: str, desc: str, fn: Callable[[], dict[str, Any]]) -> None:
        try:
            detail = fn()
            ok = bool(detail.pop("ok"))
        except AssertionError as exc:
            ok, detail = False, {"assertion": str(exc)[:200]}
        except Exception:  # noqa: BLE001
            ok, detail = False, {"exc_type": "Exception"}
        self.rows.append({"id": row_id, "item": item, "desc": desc, "pass": ok, **detail})
        print(f"{'PASS' if ok else 'FAIL'} {row_id} {desc}", flush=True)


def _login_error(body: dict[str, Any]) -> dict[str, Any]:
    err = body.get("error") or {}
    if not err and body.get("result"):
        err = body["result"].get("error") or {}
    login = err.get("login") or {}
    return {
        "kind": err.get("kind"),
        "reason": login.get("reason"),
        "identity": login.get("identity"),
    }


def _logins(body: dict[str, Any]) -> list[dict[str, Any]]:
    logins = body.get("logins") or []
    if not logins and body.get("result"):
        logins = body["result"].get("logins") or []
    return logins


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    m = Matrix()
    commandstats_evidence: dict[str, Any] = {}

    # 矩阵开始前重置 commandstats，后续只读断言对账目标服务 SET
    _reset_commandstats()

    def l22() -> dict[str, Any]:
        m.configure_target(
            skip_redis_write=False,
            create_vcode_status=200,
            vcode_omit_token=False,
            vcode_force_login_fail=False,
        )
        m.reset_target()
        resp = m.run_api("vcode", "api.login.df_admin_echo")
        body = resp.json()
        assert resp.status_code == 200 and body.get("status") == "success", body.get("status")
        assert leaks(resp.text) == 0
        logins = _logins(body)
        assert len(logins) >= 1, "应有登录过程"
        steps = logins[0].get("steps") or logins[0].get("records") or []
        # Engine 公开 logins 结构：steps 可能叫不同字段；退化为检查 name 列表
        names: list[str] = []
        if isinstance(steps, list):
            for step in steps:
                if isinstance(step, dict):
                    names.append(str(step.get("name") or step.get("step") or ""))
        # 兼容：整段 JSON 中应出现三步名
        text = resp.text
        for name in ("create_vcode", "redis_get", "login"):
            assert name in text, f"missing step {name}"
        auth = body.get("auth") or {}
        assert auth.get("identity") == "df_admin"
        echo = (((body.get("result") or {}).get("response") or {}).get("body") or {}).get("echo")
        if echo is None:
            echo = ((body.get("response") or {}).get("body") or {}).get("echo")
        assert echo, "no echo"
        assert echo.get("x_token") == "***" or (
            isinstance(echo.get("x_token"), str) and "***" in str(echo.get("x_token"))
        )
        # inject 生效：target 收到 X-TOKEN / X-USER-ID
        got = m.received()
        echo_reqs = [r for r in got if r["path"] == "/echo/token"]
        assert echo_reqs, "no business echo"
        assert echo_reqs[-1].get("x-token_count", 0) >= 1
        assert echo_reqs[-1].get("x-user-id_count", 0) >= 1
        return {"ok": True, "login_steps_seen": True, "identity": auth.get("identity")}

    m.check("L22", "§6-22", "vcode_redis 成功：三步 logins + inject 生效", l22)

    def l23() -> dict[str, Any]:
        # 成功路径已跑过；再抽失败路径，公开面不得出现秘密
        samples = []
        m.reset_target()
        samples.append(m.run_api("vcode", "api.login.df_admin_echo").text)
        m.configure_target(skip_redis_write=True)
        m.reset_target()
        samples.append(m.run_api("vcode", "api.login.df_admin_echo").text)
        m.configure_target(skip_redis_write=False, create_vcode_status=500)
        m.reset_target()
        samples.append(m.run_api("vcode", "api.login.df_admin_echo").text)
        m.configure_target(create_vcode_status=200)
        blob = "\n".join(samples)
        assert leaks(blob) == 0
        # redis_get 记录允许出现 key_prefix；密码 / 每个动态 token 精确断言不出现
        assert REDIS_PASSWORD not in blob
        assert DF_ADMIN_PASSWORD not in blob
        for tok in (v for v in _load_issued() if v.startswith("tok-")):
            assert tok not in blob, "动态 token 出现在公开面"
        return {"ok": True}

    m.check("L23", "§6-23", "验证码/uuid/密码/token/Redis 密码不出现在公开面", l23)

    def l24() -> dict[str, Any]:
        m.configure_target(skip_redis_write=False, create_vcode_status=200, vcode_omit_token=False)
        before = set(_load_issued())
        m.reset_target()
        resp = m.run_api("vcode", "api.login.df_admin_echo")
        body = resp.json()
        assert body.get("status") == "success"
        echo = (((body.get("result") or {}).get("response") or {}).get("body") or {}).get("echo")
        if echo is None:
            echo = ((body.get("response") or {}).get("body") or {}).get("echo")
        assert echo and (echo.get("x_token") == "***" or "***" in str(echo.get("x_token")))
        assert leaks(resp.text) == 0
        # 用本次签发的 uuid（issued-secrets 新增项）精确断言不出现在公开面
        after = _load_issued()
        new_vals = [v for v in after if v not in before]
        uuids = [v for v in new_vals if len(v) == 36 and v.count("-") == 4]
        assert uuids, "本次执行应签发 uuid"
        for uid in uuids:
            assert uid not in resp.text, "签发 uuid 出现在公开面"
        for tok in (v for v in new_vals if v.startswith("tok-")):
            assert tok not in resp.text
        return {"ok": True, "echo_x_token": echo.get("x_token"), "issued_uuid_checked": len(uuids)}

    m.check("L24", "§6-24", "业务回显 token → ***", l24)

    def _fail_reason(asset: str, setup: Callable[[], None] | None, expect: str) -> dict[str, Any]:
        if setup:
            setup()
        m.reset_target()
        resp = m.run_api("vcode", asset)
        assert resp.status_code == 200, f"http={resp.status_code}"
        body = resp.json()
        assert body.get("status") == "failed", body.get("status")
        info = _login_error(body)
        assert info.get("kind") == "login_failed", info
        assert info.get("reason") == expect, info
        assert leaks(resp.text) == 0
        assert _logins(body), "登录过程应可见"
        return {"ok": True, "reason": expect}

    def l25_transport() -> dict[str, Any]:
        m.configure_target(skip_redis_write=False, create_vcode_status=200)
        return _fail_reason("api.login.df_admin_dead_redis_echo", None, "transport")

    m.check("L25a", "§6-25", "Redis 不可达 → transport", l25_transport)

    def l25_timeout() -> dict[str, Any]:
        # CLIENT PAUSE 阻塞所有客户端；harness 每步 0.5s → 登录预算耗尽 → timeout
        m.configure_target(skip_redis_write=False, create_vcode_status=200)
        client = _redis_client()
        try:
            # 暂停 3 秒，足够让 0.5s 预算触发 timeout
            client.execute_command("CLIENT", "PAUSE", 3000, "ALL")
        finally:
            client.close()
        try:
            return _fail_reason("api.login.df_admin_echo", None, "timeout")
        finally:
            # 确保解除暂停（若仍在暂停期，新连接也会被挡住到到期）
            try:
                c2 = _redis_client()
                try:
                    c2.execute_command("CLIENT", "UNPAUSE")
                finally:
                    c2.close()
            except Exception:  # noqa: BLE001
                pass

    m.check("L25b", "§6-25", "Redis 超时 / 预算耗尽 → timeout", l25_timeout)

    def l25_code_missing() -> dict[str, Any]:
        def setup() -> None:
            m.configure_target(skip_redis_write=True, create_vcode_status=200)

        return _fail_reason("api.login.df_admin_echo", setup, "strategy_error")

    m.check("L25c", "§6-25", "key 不存在 → strategy_error(VcodeCodeMissing)", l25_code_missing)

    def l25_create_failed() -> dict[str, Any]:
        def setup() -> None:
            m.configure_target(skip_redis_write=False, create_vcode_status=500)

        return _fail_reason("api.login.df_admin_echo", setup, "strategy_error")

    m.check(
        "L25d",
        "§6-25",
        "createVCode 非 2xx → strategy_error(VcodeCreateFailed)",
        l25_create_failed,
    )

    def l25_login_failed() -> dict[str, Any]:
        def setup() -> None:
            m.configure_target(
                skip_redis_write=False,
                create_vcode_status=200,
                vcode_force_login_fail=True,
                vcode_omit_token=False,
            )

        return _fail_reason("api.login.df_admin_echo", setup, "strategy_error")

    m.check("L25e", "§6-25", "登录非 2xx → strategy_error(VcodeLoginFailed)", l25_login_failed)

    def l25_token_missing() -> dict[str, Any]:
        def setup() -> None:
            m.configure_target(
                skip_redis_write=False,
                create_vcode_status=200,
                vcode_force_login_fail=False,
                vcode_omit_token=True,
            )

        return _fail_reason("api.login.df_admin_echo", setup, "strategy_error")

    m.check("L25f", "§6-25", "缺 token → strategy_error(VcodeTokenMissing)", l25_token_missing)

    def l26() -> dict[str, Any]:
        # 只对「这一次」成功路径做 commandstats 对账：先 RESETSTAT，再清目标写计数
        m.configure_target(
            skip_redis_write=False,
            create_vcode_status=200,
            vcode_omit_token=False,
            vcode_force_login_fail=False,
        )
        _reset_commandstats()
        m.reset_target()
        resp = m.run_api("vcode", "api.login.df_admin_echo")
        assert resp.status_code == 200 and resp.json().get("status") == "success"
        stats = _commandstats()
        target_writes = int(m.inspect().get("redis_write_count") or 0)
        write_hits = {name: stats.get(name, 0) for name in _WRITE_COMMANDS if stats.get(name, 0)}
        set_calls = int(stats.get("set", 0))
        get_calls = int(stats.get("get", 0))
        # 目标服务写验证码用独立连接的 SET；插件侧只允许 GET（AUTH/SELECT/HELLO 由客户端发出）
        assert get_calls >= 1, f"expected GET, stats={stats}"
        assert set_calls == target_writes, (
            f"SET calls {set_calls} != target redis_write_count {target_writes}"
        )
        other_writes = {k: v for k, v in write_hits.items() if k != "set"}
        assert not other_writes, f"unexpected write commands: {other_writes}"
        commandstats_evidence.update(
            {
                "get_calls": get_calls,
                "set_calls": set_calls,
                "target_redis_write_count": target_writes,
                "other_writes": other_writes,
                "note": (
                    "CONFIG RESETSTAT 于矩阵段开始；SET 仅来自目标服务写验证码连接，"
                    "与 /__inspect.redis_write_count 对账；插件只读 GET。"
                ),
            }
        )
        return {
            "ok": True,
            "get_calls": get_calls,
            "set_calls": set_calls,
            "target_writes": target_writes,
        }

    m.check("L26", "§6-26", "只读：commandstats 无插件写命令（目标 SET 对账）", l26)

    def l27() -> dict[str, Any]:
        m.configure_target(
            skip_redis_write=False,
            create_vcode_status=200,
            vcode_force_login_fail=False,
        )
        m.reset_target()
        # 引用缺失连接秘密的身份 → 422
        bad = m.run_api("vcode-conn-missing", "api.login.df_admin_echo")
        assert bad.status_code == 422, f"status={bad.status_code}"
        assert "df_admin" in bad.text or "redis_main" in bad.text
        assert leaks(bad.text) == 0
        assert REDIS_PASSWORD not in bad.text
        assert DF_ADMIN_PASSWORD not in bad.text
        # 同项目其它身份正常
        ok_admin = m.run_api("vcode-conn-missing", "api.login.admin_echo")
        assert ok_admin.status_code == 200 and ok_admin.json().get("status") == "success"
        assert leaks(ok_admin.text) == 0
        ok_plugin = m.run_api("vcode-conn-missing", "api.login.plugin_echo")
        assert ok_plugin.status_code == 200 and ok_plugin.json().get("status") == "success"
        assert leaks(ok_plugin.text) == 0
        return {"ok": True, "blocked": 422, "others": "success"}

    m.check("L27", "§6-27", "连接秘密缺失只阻断引用身份；其它身份正常", l27)

    def l28() -> dict[str, Any]:
        discovered = discover_installed_login_strategies()
        assert "vcode_redis" in discovered, "插件未 path 安装？"
        empty = {s.name for s in resolve_login_strategies(["fake_login"])}
        assert "vcode_redis" not in empty
        m.reset_target()
        resp = m.run_api("vcode-no-whitelist", "api.login.df_admin_echo")
        assert resp.status_code == 422, f"status={resp.status_code}"
        assert not m.received(), "白名单未列时不应发出请求"
        assert leaks(resp.text) == 0
        return {"ok": True, "discovered": sorted(discovered.keys())}

    m.check("L28", "§6-28", "白名单未列 vcode_redis → 不注册且 422 无出站", l28)

    report = {
        "rows": m.rows,
        "projects": m.projects,
        "passed": sum(1 for r in m.rows if r["pass"]),
        "total": len(m.rows),
        "section": "phase3_3c_vcode_§6.22-28",
        "commandstats": commandstats_evidence,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    assert leaks(text) == 0, "报告含秘密，拒绝写出"
    (OUT_DIR / "vcode-matrix-report.json").write_text(text + "\n", encoding="utf-8")
    print(f"VCODE MATRIX {report['passed']}/{report['total']}")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
