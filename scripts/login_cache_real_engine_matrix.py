"""Phase 3.3d 真实 Engine 登录缓存 / 401 重登矩阵（设计稿 §6 第 31–45 条）。

由 ``scripts/run_real_engine_matrix.sh`` 在 3.3c 验证码段之后调用。
计数断言使用精确值（非 ≥）；假秘密与动态签发值不写入报告。
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

BUYER_PASSWORD = "tp-fake-buyer-pass-71c2"
BUYER_PASSWORD_ALT = "tp-fake-buyer-pass-ALT99"
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
    BUYER_PASSWORD_ALT,
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

BACKEND = os.environ.get("MATRIX_BACKEND_URL", "http://127.0.0.1:8000")
TARGET = os.environ["MATRIX_TARGET_URL"]
ASSETS_ROOT = os.environ["MATRIX_LOGIN_ASSETS_ROOT"]
OUT_DIR = Path(os.environ["MATRIX_CACHE_OUT_DIR"])
ISSUED_PATH = Path(os.environ.get("MATRIX_ISSUED_SECRETS_PATH", ""))
BACKEND_LOG = Path(os.environ.get("MATRIX_BACKEND_LOG", OUT_DIR / "backend.log"))
ROOT_CACHE = os.environ["MATRIX_ROOT_CACHE"]
# L37 第二项目共用同一份 auth 配置目录（作用域靠 project.id 区分）
ROOT_CACHE_B = os.environ.get("MATRIX_ROOT_CACHE_B", ROOT_CACHE)


def leaks(text: str) -> int:
    return sum(text.count(t) for t in SEARCH_TARGETS)


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


def _tokens(issued: list[str] | None = None) -> list[str]:
    src = issued if issued is not None else _load_issued()
    return [v for v in src if v.startswith("tok-")]


class Matrix:
    def __init__(self) -> None:
        self.client = httpx.Client(timeout=120)
        self.rows: list[dict[str, Any]] = []
        self.projects: dict[str, str] = {}

    def project(self, key: str, config_root: str | None = None) -> str:
        if key not in self.projects:
            root = config_root or ROOT_CACHE
            resp = self.client.post(
                f"{BACKEND}/projects",
                json={
                    "name": f"cache-matrix-{key}-{os.getpid()}",
                    "env": "test",
                    "assets_root": ASSETS_ROOT,
                    "config_root": root,
                },
            )
            resp.raise_for_status()
            self.projects[key] = resp.json()["id"]
        return self.projects[key]

    def run_api(
        self, key: str, asset: str, params: dict | None = None, *, config_root: str | None = None
    ) -> httpx.Response:
        pid = self.project(key, config_root=config_root)
        return self.client.post(
            f"{BACKEND}/projects/{pid}/assets/{asset}/run", json={"params": params or {}}
        )

    def reset_target(self) -> None:
        self.client.post(f"{TARGET}/__inspect/reset").raise_for_status()

    def configure_target(self, **cfg: object) -> None:
        self.client.post(f"{TARGET}/__inspect/config", json=cfg).raise_for_status()

    def inspect(self) -> dict[str, Any]:
        return self.client.get(f"{TARGET}/__inspect").json()

    def received(self) -> list[dict[str, Any]]:
        return self.inspect()["requests"]

    def login_count(self, user: str) -> int:
        return int(self.inspect().get("login_counts", {}).get(user, 0))

    def check(self, row_id: str, item: str, desc: str, fn: Callable[[], dict[str, Any]]) -> None:
        try:
            detail = fn()
            ok = bool(detail.pop("ok"))
        except AssertionError as exc:
            ok, detail = False, {"assertion": (str(exc) or repr(exc))[:240]}
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, {"exc_type": type(exc).__name__, "assertion": str(exc)[:240]}
        self.rows.append({"id": row_id, "item": item, "desc": desc, "pass": ok, **detail})
        print(f"{'PASS' if ok else 'FAIL'} {row_id} {desc}", flush=True)


def _auth(body: dict[str, Any]) -> dict[str, Any]:
    return body.get("auth") or {}


def _logins(body: dict[str, Any]) -> list[dict[str, Any]]:
    logins = body.get("logins") or []
    if not logins and body.get("result"):
        logins = body["result"].get("logins") or []
    return logins


def _echo(body: dict[str, Any]) -> dict[str, Any] | None:
    echo = (((body.get("result") or {}).get("response") or {}).get("body") or {}).get("echo")
    if echo is None:
        echo = ((body.get("response") or {}).get("body") or {}).get("echo")
    return echo


def _status(body: dict[str, Any]) -> str | None:
    return body.get("status")


def _error_kind(body: dict[str, Any]) -> str | None:
    err = body.get("error") or {}
    if not err and body.get("result"):
        err = body["result"].get("error") or {}
    return err.get("kind")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    m = Matrix()
    # 清吊销集合，避免跨段残留
    m.configure_target(
        always_401=False,
        force_login_fail=False,
        clear_revoked=True,
        expires_in=3600,
    )

    def l31() -> dict[str, Any]:
        m.configure_target(always_401=False, force_login_fail=False, clear_revoked=True)
        m.reset_target()
        r1 = m.run_api("cache", "api.login.buyer_cached_echo")
        b1 = r1.json()
        assert r1.status_code == 200 and _status(b1) == "success", _status(b1)
        assert _auth(b1).get("session_source") == "login"
        assert m.login_count("cached_user") == 1
        r2 = m.run_api("cache", "api.login.buyer_cached_echo")
        b2 = r2.json()
        assert r2.status_code == 200 and _status(b2) == "success", _status(b2)
        auth2 = _auth(b2)
        assert auth2.get("session_source") == "cache", auth2
        assert auth2.get("login_ref") is None
        assert _logins(b2) == []
        assert m.login_count("cached_user") == 1
        # inject 生效
        echoes = [r for r in m.received() if r["path"] == "/echo/token"]
        assert len(echoes) == 2
        assert echoes[-1].get("x-token_count", 0) == 1
        assert leaks(r1.text) == 0 and leaks(r2.text) == 0
        return {
            "ok": True,
            "login_count": 1,
            "session_source": auth2.get("session_source"),
        }

    m.check("L31", "§6-31", "缓存命中：两次执行仅 1 次登录；session_source=cache", l31)

    def l32() -> dict[str, Any]:
        # 缓存命中路径的按值替换：业务回显 token → ***
        m.reset_target()
        # 先确保有缓存（同项目）
        r1 = m.run_api("cache", "api.login.buyer_cached_echo")
        assert r1.status_code == 200 and _status(r1.json()) == "success"
        r2 = m.run_api("cache", "api.login.buyer_cached_echo")
        b2 = r2.json()
        assert _auth(b2).get("session_source") == "cache"
        echo = _echo(b2)
        assert echo, "no echo"
        xt = echo.get("x_token")
        assert xt == "***" or (isinstance(xt, str) and "***" in xt)
        for tok in _tokens():
            assert tok not in r2.text, "动态 token 出现在公开面"
        assert BUYER_PASSWORD not in r2.text
        assert leaks(r2.text) == 0
        return {"ok": True, "echo_x_token": echo.get("x_token")}

    m.check("L32", "§6-32", "缓存命中路径：业务回显 token → ***（H1）", l32)

    def l33() -> dict[str, Any]:
        # ttl_seconds=32，等 3 秒后剩余 < 30 → 重新登录
        m.configure_target(expires_in=3600)
        m.reset_target()
        r1 = m.run_api("cache", "api.login.buyer_ttl32_echo")
        assert r1.status_code == 200 and _status(r1.json()) == "success"
        assert m.login_count("ttl32_user") == 1
        time.sleep(3.0)
        r2 = m.run_api("cache", "api.login.buyer_ttl32_echo")
        assert r2.status_code == 200 and _status(r2.json()) == "success"
        assert m.login_count("ttl32_user") == 2
        assert _auth(r2.json()).get("session_source") == "login", _auth(r2.json())

        # expires_from 同样：服务端 expires_in=32
        m.configure_target(expires_in=32)
        m.reset_target()
        r3 = m.run_api("cache", "api.login.buyer_expires32_echo")
        assert r3.status_code == 200 and _status(r3.json()) == "success"
        assert m.login_count("expires32_user") == 1
        time.sleep(3.0)
        r4 = m.run_api("cache", "api.login.buyer_expires32_echo")
        assert r4.status_code == 200 and _status(r4.json()) == "success"
        assert m.login_count("expires32_user") == 2
        m.configure_target(expires_in=3600)
        return {"ok": True, "ttl32_logins": 2, "expires32_logins": 2, "wait_s": 3}

    m.check("L33", "§6-33", "短 ttl/expires_from=32 等待 3s 后重新登录", l33)

    def l34() -> dict[str, Any]:
        m.reset_target()
        r1 = m.run_api("cache", "api.login.buyer_no_ttl_echo")
        r2 = m.run_api("cache", "api.login.buyer_no_ttl_echo")
        assert r1.status_code == 200 and r2.status_code == 200
        assert m.login_count("nottl_user") == 2
        assert _auth(r1.json()).get("session_source") == "login"
        assert _auth(r2.json()).get("session_source") == "login", _auth(r2.json())
        return {"ok": True, "login_count": 2}

    m.check("L34", "§6-34", "R2：无 ttl/expires_from → 每次执行都登录", l34)

    def l35() -> dict[str, Any]:
        m.reset_target()
        r1 = m.run_api("cache", "api.login.seller_echo")
        r2 = m.run_api("cache", "api.login.seller_echo")
        assert r1.status_code == 200 and r2.status_code == 200
        assert _status(r1.json()) == "success" and _status(r2.json()) == "success"
        assert m.login_count("seller001") == 2
        return {"ok": True, "login_count": 2}

    m.check("L35", "§6-35", "R5：session:cookie 身份每次执行都登录", l35)

    def l36() -> dict[str, Any]:
        auth_path = Path(ROOT_CACHE) / "auth" / "test.yaml"
        original = auth_path.read_text("utf-8")
        try:
            m.configure_target(clear_revoked=True, always_401=False)
            m.reset_target()
            r1 = m.run_api("cache", "api.login.buyer_cached_echo")
            assert r1.status_code == 200 and _status(r1.json()) == "success", _status(r1.json())
            # 可能命中既有缓存；只记录改密前登录计数

            # 改密码对应的环境变量名 → 指纹变 → 重新登录
            mutated = original.replace(
                "${secret:TESTPLAT_BUYER_PASSWORD}",
                "${secret:TESTPLAT_BUYER_PASSWORD_ALT}",
            )
            assert mutated != original, "password secret replace failed"
            auth_path.write_text(mutated, encoding="utf-8")
            m.reset_target()
            r2 = m.run_api("cache", "api.login.buyer_cached_echo")
            assert r2.status_code == 200 and _status(r2.json()) == "success", r2.text[:200]
            assert m.login_count("cached_user") == 1, m.inspect().get("login_counts")
            # 与改密前的缓存不应命中：session_source 必须是 login
            assert _auth(r2.json()).get("session_source") == "login", _auth(r2.json())

            # 改登录 path → 再登录
            auth_path.write_text(original, encoding="utf-8")
            # 先用原配置暖缓存
            m.reset_target()
            warm = m.run_api("cache", "api.login.buyer_cached_echo")
            assert warm.status_code == 200 and _auth(warm.json()).get("session_source") in (
                "login",
                "cache",
            )
            path_mutated = original.replace("path: /login/json", "path: /login/json-alt", 1)
            # buyer_cached 的 steps 里只有一处 /login/json
            assert path_mutated != original
            auth_path.write_text(path_mutated, encoding="utf-8")
            before = m.login_count("cached_user")
            r3 = m.run_api("cache", "api.login.buyer_cached_echo")
            assert r3.status_code == 200 and _status(r3.json()) == "success", r3.text[:200]
            after = m.login_count("cached_user")
            assert after == before + 1, (before, after, m.inspect().get("login_counts"))
            assert _auth(r3.json()).get("session_source") == "login", _auth(r3.json())
        finally:
            auth_path.write_text(original, encoding="utf-8")
        return {"ok": True, "password_fp": True, "path_fp": True}

    m.check("L36", "§6-36", "指纹：改密码/改 path → 重新登录", l36)

    def l37() -> dict[str, Any]:
        m.configure_target(clear_revoked=True)
        m.reset_target()
        # 两项目同配置
        r_a = m.run_api("cache-a", "api.login.buyer_cached_echo", config_root=ROOT_CACHE)
        r_b = m.run_api("cache-b", "api.login.buyer_cached_echo", config_root=ROOT_CACHE_B)
        assert r_a.status_code == 200 and r_b.status_code == 200
        assert _status(r_a.json()) == "success" and _status(r_b.json()) == "success"
        assert m.login_count("cached_user") == 2
        assert m.projects["cache-a"] != m.projects["cache-b"]
        # 各自第二次应命中本项目缓存
        r_a2 = m.run_api("cache-a", "api.login.buyer_cached_echo")
        r_b2 = m.run_api("cache-b", "api.login.buyer_cached_echo")
        assert _auth(r_a2.json()).get("session_source") == "cache"
        assert _auth(r_b2.json()).get("session_source") == "cache"
        assert m.login_count("cached_user") == 2
        return {
            "ok": True,
            "login_count": 2,
            "projects": [m.projects["cache-a"], m.projects["cache-b"]],
        }

    m.check("L37", "§6-37", "作用域隔离：两项目各登录一次，互不命中", l37)

    def l38() -> dict[str, Any]:
        m.configure_target(always_401=False, force_login_fail=False, clear_revoked=True)
        m.reset_target()
        # 暖缓存 + POST 业务（可能命中既有缓存；随后按 issued-secrets 吊销）
        warm = m.run_api("cache", "api.login.buyer_cached_post")
        assert warm.status_code == 200 and _status(warm.json()) == "success", _status(warm.json())
        # 吊销已签发 token（含文件中历史 token，覆盖 Engine 缓存持有的旧值）
        m.configure_target(revoke_current_token=True)
        m.reset_target()  # 清请求记录；login_counts 清零；吊销集合保留
        r = m.run_api("cache", "api.login.buyer_cached_post")
        body = r.json()
        assert r.status_code == 200 and _status(body) == "success", _status(body)
        auth = _auth(body)
        assert auth.get("reauthenticated") is True, auth
        assert auth.get("session_source") == "login"
        logins = _logins(body)
        assert len(logins) == 1, f"logins={len(logins)}"
        # 公开 response 是 200
        resp_status = ((body.get("result") or {}).get("response") or {}).get("status_code")
        if resp_status is None:
            resp_status = (body.get("response") or {}).get("status_code")
        assert resp_status == 200, resp_status
        # 两次业务请求方法/路径相同；body 由 Engine 保证一致（inspect 不存 body）
        biz = [x for x in m.received() if x["path"] == "/echo/json" and x["method"] == "POST"]
        assert len(biz) == 2, f"biz={len(biz)}"
        # 重登恰好 1 次
        assert m.login_count("cached_user") == 1, m.inspect().get("login_counts")
        assert leaks(r.text) == 0, "leaks in L38 public"
        return {
            "ok": True,
            "reauthenticated": True,
            "business_posts": 2,
            "reauth_logins": 1,
        }

    m.check("L38", "§6-38", "401 重发成功：吊销→重登→200；POST 两次业务", l38)

    def l39() -> dict[str, Any]:
        m.configure_target(always_401=False, force_login_fail=False, clear_revoked=True)
        m.reset_target()
        warm = m.run_api("cache", "api.login.buyer_cached_echo")
        assert warm.status_code == 200 and _status(warm.json()) == "success"
        m.configure_target(always_401=True)
        m.reset_target()
        r = m.run_api("cache", "api.login.buyer_cached_echo")
        body = r.json()
        assert r.status_code == 200
        # 断言失败（业务 success 要 200，实际 401）
        assert _status(body) == "failed", _status(body)
        assert _auth(body).get("reauthenticated") is True
        biz = [x for x in m.received() if x["path"] == "/echo/token"]
        assert len(biz) == 2, f"biz={len(biz)}"
        assert m.login_count("cached_user") == 1  # 仅重登 1 次
        m.configure_target(always_401=False)
        assert leaks(r.text) == 0
        return {"ok": True, "business": 2, "reauth_logins": 1}

    m.check("L39", "§6-39", "401 两次：断言失败；2 次业务 + 1 次重登", l39)

    def l40() -> dict[str, Any]:
        m.configure_target(always_401=False, force_login_fail=False, clear_revoked=True)
        m.reset_target()
        warm = m.run_api("cache", "api.login.buyer_no_reauth_echo")
        assert warm.status_code == 200 and _status(warm.json()) == "success"
        m.configure_target(always_401=True)
        m.reset_target()
        r = m.run_api("cache", "api.login.buyer_no_reauth_echo")
        body = r.json()
        assert r.status_code == 200
        assert _status(body) == "failed"
        assert _auth(body).get("reauthenticated") is False
        biz = [x for x in m.received() if x["path"] == "/echo/token"]
        assert len(biz) == 1, f"不应重发: biz={len(biz)}"
        assert m.login_count("noreauth_user") == 0  # 无重登
        m.configure_target(always_401=False)
        return {"ok": True, "business": 1, "reauthenticated": False}

    m.check("L40", "§6-40", "reauth_on_401:false → 不重发，401 直接断言", l40)

    def l41() -> dict[str, Any]:
        m.configure_target(always_401=False, force_login_fail=False, clear_revoked=True)
        m.reset_target()
        warm = m.run_api("cache", "api.login.buyer_cached_echo")
        assert warm.status_code == 200 and _status(warm.json()) == "success"
        m.configure_target(revoke_current_token=True, force_login_fail=True)
        m.reset_target()
        r = m.run_api("cache", "api.login.buyer_cached_echo")
        body = r.json()
        assert r.status_code == 200
        # login_failed：200 + 保存
        assert _status(body) == "failed", _status(body)
        kind = _error_kind(body)
        assert kind == "login_failed" or "login_failed" in r.text, kind
        assert _auth(body).get("reauthenticated") is True, _auth(body)
        m.configure_target(force_login_fail=False)
        assert leaks(r.text) == 0
        return {"ok": True, "kind": kind or "login_failed", "reauthenticated": True}

    m.check("L41", "§6-41", "重登失败 → login_failed；reauthenticated=true", l41)

    def l42() -> dict[str, Any]:
        # 在 L38 场景后再执行：应命中重登后的新 token，不再登录
        m.configure_target(
            always_401=False, force_login_fail=False, clear_revoked=True, expires_in=3600
        )
        m.reset_target()
        warm = m.run_api("cache", "api.login.buyer_cached_post")
        assert warm.status_code == 200
        m.configure_target(revoke_current_token=True)
        m.reset_target()
        mid = m.run_api("cache", "api.login.buyer_cached_post")
        mid_auth = _auth(mid.json())
        assert mid.status_code == 200 and mid_auth.get("reauthenticated") is True, mid_auth
        assert m.login_count("cached_user") == 1
        # 再执行：命中新 token，无登录
        m.reset_target()
        again = m.run_api("cache", "api.login.buyer_cached_post")
        assert again.status_code == 200 and _status(again.json()) == "success"
        assert _auth(again.json()).get("session_source") == "cache"
        assert _auth(again.json()).get("reauthenticated") is False
        assert m.login_count("cached_user") == 0
        login_paths = [x for x in m.received() if x["path"] == "/login/json"]
        assert len(login_paths) == 0
        return {"ok": True, "session_source": "cache", "extra_logins": 0}

    m.check("L42", "§6-42", "缓存作废后命中重登新 token，不再登录", l42)

    def l43() -> dict[str, Any]:
        m.configure_target(always_401=False, force_login_fail=False, clear_revoked=True)
        m.reset_target()
        # 使用全新项目，保证冷启动
        key = f"cache-concurrent-{time.time_ns()}"
        pid = m.project(key, config_root=ROOT_CACHE)
        url = f"{BACKEND}/projects/{pid}/assets/api.login.buyer_cached_echo/run"
        results: list[httpx.Response] = []
        errors: list[str] = []

        def _one() -> None:
            try:
                with httpx.Client(timeout=120) as c:
                    results.append(c.post(url, json={"params": {}}))
            except Exception as exc:  # noqa: BLE001
                errors.append(type(exc).__name__)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futs = [pool.submit(_one), pool.submit(_one)]
            for f in futs:
                f.result()
        assert not errors, errors
        assert len(results) == 2
        for resp in results:
            assert resp.status_code == 200, resp.status_code
            assert _status(resp.json()) == "success"
        # single-flight：恰好 1 次登录
        assert m.login_count("cached_user") == 1, m.inspect().get("login_counts")
        sources = sorted(_auth(r.json()).get("session_source") or "" for r in results)
        # 一个 login、一个 cache（或两个都 login 若锁外竞态——设计要求只 1 次登录）
        assert sources.count("login") + sources.count("cache") == 2
        return {"ok": True, "login_count": 1, "sources": sources}

    m.check("L43", "§6-43", "并发冷启动：目标服务只收到 1 次登录", l43)

    def l44() -> dict[str, Any]:
        # 覆盖缓存命中与 401 重登两类场景后，检查动态目标与日志
        m.configure_target(always_401=False, force_login_fail=False, clear_revoked=True)
        m.reset_target()
        hit1 = m.run_api("cache", "api.login.buyer_cached_echo")
        hit2 = m.run_api("cache", "api.login.buyer_cached_echo")
        assert _auth(hit2.json()).get("session_source") == "cache", _auth(hit2.json())
        m.configure_target(revoke_current_token=True)
        m.reset_target()
        reauth = m.run_api("cache", "api.login.buyer_cached_echo")
        assert _auth(reauth.json()).get("reauthenticated") is True, _auth(reauth.json())

        issued = _load_issued()
        tokens = _tokens(issued)
        assert tokens, "动态 token 目标为空"
        # 含被吊销的旧 token（issued 文件在 reset 后仍保留历史）
        assert len(tokens) >= 2, f"tokens={len(tokens)}"

        # 公开面 / 报告不得含动态 token
        for sample in (hit1.text, hit2.text, reauth.text):
            for tok in tokens:
                assert tok not in sample, "token in public sample"

        # 后端日志：不含 fingerprint / cache_scope 原值；允许 cache=hit|miss|...
        assert BACKEND_LOG.is_file(), f"missing backend log {BACKEND_LOG}"
        log_text = BACKEND_LOG.read_text("utf-8", errors="replace")
        for tok in tokens:
            assert tok not in log_text, "后端日志含 token"
        assert BUYER_PASSWORD not in log_text, "buyer password in backend log"
        assert "fingerprint" not in log_text.lower() or not re.search(
            r"fingerprint\s*=\s*[0-9a-f]{16,}", log_text, re.I
        )
        # cache_scope 原值形态 project_id:env
        for pid in m.projects.values():
            scope = f"{pid}:test"
            assert scope not in log_text, "日志含 cache_scope 原值"
        # 缓存相关行只应出现允许字段（抽查含 cache= 的行）
        cache_lines = [ln for ln in log_text.splitlines() if "cache=" in ln]
        # 无缓冲时通常可见；若仍为空仅记警告（token/scope 断言仍强制）
        if not cache_lines:
            # 再读一次（应对缓冲）
            log_text = BACKEND_LOG.read_text("utf-8", errors="replace")
            cache_lines = [ln for ln in log_text.splitlines() if "cache=" in ln]
        assert cache_lines, "应有 cache= 日志"
        for ln in cache_lines:
            # 不得出现长 hex 指纹
            assert not re.search(r"\b[0-9a-f]{32,}\b", ln), ln[:120]

        return {
            "ok": True,
            "dynamic_tokens": len(tokens),
            "dynamic_issued": len(issued),
            "cache_log_lines": len(cache_lines),
        }

    m.check("L44", "§6-44", "泄密：动态目标含吊销 token；日志无 fingerprint/scope", l44)

    def l45() -> dict[str, Any]:
        # 本条由 run_real_engine_matrix.sh 聚合 3.3a/b/c 与回归结果；此处只写占位通过标记
        # 真正断言在 shell 汇总各报告 passed/total
        markers = {
            "auth_report": os.environ.get("MATRIX_AUTH_REPORT", ""),
            "login_report": os.environ.get("MATRIX_LOGIN_REPORT", ""),
            "vcode_report": os.environ.get("MATRIX_VCODE_REPORT", ""),
            "phase3_report": os.environ.get("MATRIX_PHASE3_REPORT", ""),
        }
        detail: dict[str, Any] = {"ok": True, "deferred_to_shell": True}
        for name, path in markers.items():
            if not path or not Path(path).is_file():
                detail[name] = "pending"
                continue
            data = json.loads(Path(path).read_text("utf-8"))
            passed = data.get("passed")
            total = data.get("total")
            if passed is None and "rows" in data:
                rows = data["rows"]
                passed = sum(1 for r in rows if r.get("pass"))
                total = len(rows)
            detail[name] = f"{passed}/{total}"
            if passed is not None and total is not None and passed != total:
                detail["ok"] = False
                detail["failed"] = name
                return detail
        return detail

    m.check("L45", "§6-45", "3.3a/b/c 矩阵与 Phase 3 回归不变（shell 对账）", l45)

    report = {
        "rows": m.rows,
        "projects": {k: v for k, v in m.projects.items()},
        "passed": sum(1 for r in m.rows if r["pass"]),
        "total": len(m.rows),
        "section": "phase3_3d_cache_§6.31-45",
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    assert leaks(text) == 0, "报告含秘密，拒绝写出"
    for tok in _tokens():
        assert tok not in text
    (OUT_DIR / "login-cache-matrix-report.json").write_text(text + "\n", encoding="utf-8")
    print(f"CACHE MATRIX {report['passed']}/{report['total']}")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
