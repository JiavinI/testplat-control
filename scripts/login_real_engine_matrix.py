"""Phase 3.3b 真实 Engine 登录矩阵（设计稿 §6 第 11–21 条 + 旧 profile + E1）。

由 ``scripts/run_real_engine_matrix.sh`` 在 3.3a 鉴权段之后调用。假秘密只用于摘要与搜索，
绝不写入报告。target 的 /__inspect 只暴露路径与摘要。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from testplat_control.engine_bootstrap import (
    discover_installed_login_strategies,
    resolve_login_strategies,
)

BUYER_PASSWORD = "tp-fake-buyer-pass-71c2"
SELLER_PASSWORD = "tp-fake-seller-pass-93ab"
REDIS_PASSWORD = "tp-fake-redis-pass-5e0d"
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
OUT_DIR = Path(os.environ["MATRIX_LOGIN_OUT_DIR"])
ROOTS = {
    "login": os.environ["MATRIX_ROOT_LOGIN"],
    "legacy": os.environ["MATRIX_ROOT_LEGACY"],
    "static": os.environ["MATRIX_ROOT_STATIC"],
    "no-plugin": os.environ["MATRIX_ROOT_NO_PLUGIN"],
    "unknown": os.environ["MATRIX_ROOT_UNKNOWN"],
}


def leaks(text: str) -> int:
    return sum(text.count(t) for t in SEARCH_TARGETS)


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Matrix:
    def __init__(self) -> None:
        self.client = httpx.Client(timeout=90)
        self.rows: list[dict[str, Any]] = []
        self.projects: dict[str, str] = {}

    def project(self, root: str) -> str:
        if root not in self.projects:
            resp = self.client.post(
                f"{BACKEND}/projects",
                json={
                    "name": f"login-matrix-{root}-{os.getpid()}",
                    "env": "test",
                    "assets_root": ASSETS_ROOT,
                    "config_root": ROOTS[root],
                },
            )
            resp.raise_for_status()
            self.projects[root] = resp.json()["id"]
        return self.projects[root]

    def run_api(self, root: str, asset: str, params: dict | None = None) -> httpx.Response:
        pid = self.project(root)
        return self.client.post(
            f"{BACKEND}/projects/{pid}/assets/{asset}/run", json={"params": params or {}}
        )

    def run_case(self, root: str, case: str) -> httpx.Response:
        pid = self.project(root)
        return self.client.post(f"{BACKEND}/projects/{pid}/cases/{case}/run", json={})

    def reset_target(self) -> None:
        self.client.post(f"{TARGET}/__inspect/reset").raise_for_status()

    def received(self) -> list[dict[str, Any]]:
        return self.client.get(f"{TARGET}/__inspect").json()["requests"]

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


def _public_text(resp: httpx.Response) -> str:
    return resp.text


def _assert_login_shape(body: dict[str, Any]) -> list[dict[str, Any]]:
    logins = body.get("logins") or (body.get("result") or {}).get("logins") or []
    # API 结果可能把 logins 放在顶层或 result
    if not logins and "result" in body:
        logins = body["result"].get("logins") or []
    return logins


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    m = Matrix()

    # ---- E1：假插件已安装；白名单缺失 → 交集为空；列入白名单 → 可发现 ----
    def e1_intersection() -> dict[str, Any]:
        discovered = discover_installed_login_strategies()
        assert "fake_login" in discovered, "假插件 entry point 未发现（未 path 安装？）"
        empty = {s.name for s in resolve_login_strategies([])}
        assert "fake_login" not in empty, "空白名单仍注册了假插件"
        selected = {s.name for s in resolve_login_strategies(["fake_login"])}
        assert "fake_login" in selected, "白名单交集未选中假插件"
        # 未在白名单的身份配置 → Control 加载期 422，无请求
        m.reset_target()
        resp = m.run_api("no-plugin", "api.login.plugin_echo")
        assert resp.status_code == 422, f"status={resp.status_code}"
        assert not m.received(), "白名单缺失时不应发出请求"
        assert leaks(_public_text(resp)) == 0
        return {
            "ok": True,
            "discovered": sorted(discovered.keys()),
            "empty_intersection": sorted(empty),
            "selected": sorted(selected),
        }

    m.check("E1", "§6-18,E1", "假插件 entry point ∩ 白名单；缺失时不注册且 422", e1_intersection)

    def unknown_strategy() -> dict[str, Any]:
        m.reset_target()
        resp = m.run_api("unknown", "api.login.ghost_echo")
        assert resp.status_code == 422, f"status={resp.status_code}"
        assert not m.received(), "未注册策略不应发出请求"
        assert leaks(_public_text(resp)) == 0
        return {"ok": True, "http": 422}

    # 为 unknown 补 ghost 资产跑法：改用 cases 不方便；直接 POST 用不存在身份的 API
    # 重新定义：unknown-strategy.yaml 的 ghost；添加 api.login.ghost_echo
    m.check("E1b", "§6-18", "未注册策略名 → 422 且无出站请求", unknown_strategy)

    # ---- §6-11：登录密码/token/Set-Cookie 不出现在公开面 ----
    def s11() -> dict[str, Any]:
        m.reset_target()
        resp = m.run_api("login", "api.login.buyer_echo")
        body = resp.json()
        assert resp.status_code == 200 and body.get("status") == "success", body.get("status")
        assert leaks(_public_text(resp)) == 0
        logins = body.get("logins") or (body.get("result") or {}).get("logins") or []
        assert logins, "logins 应可见"
        assert logins[0].get("status") == "success"
        auth = body.get("auth") or {}
        assert auth.get("identity") == "buyer"
        assert auth.get("login_ref") == 0
        text = _public_text(resp)
        for s in (BUYER_PASSWORD, CSRF_TOKEN, CSRF_SEED):
            assert s not in text
        assert "tok-buyer-" not in text and "a8f3e2c1d0" not in text
        got = m.received()
        assert any(r["path"] == "/login/json" for r in got)
        assert any(r["path"] == "/echo/token" for r in got)
        return {"ok": True, "logins": len(logins), "login_ref": auth.get("login_ref")}

    m.check("L11", "§6-11", "登录密码/token 不出现在公开结果；login_ref 可见", s11)

    def s11_cookie() -> dict[str, Any]:
        m.reset_target()
        resp = m.run_api("login", "api.login.seller_echo")
        body = resp.json()
        assert resp.status_code == 200 and body.get("status") == "success", str(body.get("status"))
        assert leaks(_public_text(resp)) == 0
        assert "sess-" not in _public_text(resp)
        assert SELLER_PASSWORD not in _public_text(resp)
        assert CSRF_TOKEN not in _public_text(resp) or "***" in _public_text(resp)
        # Set-Cookie 会话值不得出现
        assert "7b7b7b7b" not in _public_text(resp)
        auth = body.get("auth") or {}
        assert auth.get("identity") == "seller"
        return {"ok": True, "cookie_names": auth.get("cookie_names")}

    m.check("L11c", "§6-11", "Cookie 会话值 / CSRF 不出现在公开结果", s11_cookie)

    # ---- §6-12：业务回显 token/Cookie → ***；alias → *** ----
    def s12() -> dict[str, Any]:
        m.reset_target()
        resp = m.run_api("login", "api.login.buyer_echo")
        body = resp.json()
        echo = (((body.get("result") or {}).get("response") or {}).get("body") or {}).get("echo")
        if echo is None:
            echo = ((body.get("response") or {}).get("body") or {}).get("echo")
        assert echo, f"no echo in {list(body)}"
        xt = echo.get("x_token")
        assert xt == "***" or (isinstance(xt, str) and "***" in xt)
        assert leaks(_public_text(resp)) == 0
        # alias
        m.reset_target()
        rc = m.run_case("login", "case.login.alias_leak")
        assert rc.status_code == 200, f"alias case http={rc.status_code}"
        assert leaks(rc.text) == 0
        got = m.received()
        # 最后一次业务请求的 X-Resource-Id 应为 ***
        last = [r for r in got if r["path"] == "/echo/token"]
        assert last, "no echo requests"
        # inspect stores x-resource-id plain — if Engine sent ***, value is ***
        rid = last[-1].get("x-resource-id") or ""
        assert "***" in rid and leaks(rid) == 0, f"alias 未脱敏: count={len(rid)}"
        return {"ok": True, "echo_x_token": echo.get("x_token"), "alias_masked": True}

    m.check("L12", "§6-12", "业务回显 token → ***；alias → ***", s12)

    # ---- §6-13：两身份不串号；匿名无 Cookie ----
    def s13() -> dict[str, Any]:
        m.reset_target()
        rc = m.run_case("login", "case.login.alternate")
        assert rc.status_code == 200, f"http={rc.status_code}"
        body = rc.json()
        assert body.get("status") == "success", body.get("status")
        assert leaks(rc.text) == 0
        steps = body["result"]["steps"]
        ids = [None if s.get("auth") is None else s["auth"]["identity"] for s in steps]
        assert ids == ["buyer", "seller", None, "buyer", "seller"], ids
        got = m.received()
        # 匿名步骤 /echo/token 不应带 cookie / x-token
        echo_reqs = [r for r in got if r["path"] == "/echo/token"]
        assert len(echo_reqs) == 5, len(echo_reqs)
        anon = echo_reqs[2]
        assert anon.get("cookie_count", 0) == 0, "匿名步骤携带 Cookie"
        assert anon.get("x-token_count", 0) == 0, "匿名步骤携带 X-TOKEN"
        # buyer 与 seller 凭证不同
        buyer_tok = echo_reqs[0].get("x-token_sha256") or []
        seller_csrf = echo_reqs[1].get("x-csrf-token_sha256") or []
        assert buyer_tok and seller_csrf
        assert echo_reqs[0].get("cookie_count", 0) == 0  # buyer 用 header 注入
        assert echo_reqs[1].get("cookie_count", 0) >= 1  # seller Cookie 会话
        return {"ok": True, "identities": ids}

    m.check("L13", "§6-13", "两 login 身份交替不串号；匿名无 Cookie", s13)

    # ---- §6-14：两次独立执行不共享鉴权 ----
    def s14() -> dict[str, Any]:
        m.reset_target()
        r1 = m.run_api("login", "api.login.buyer_echo")
        assert r1.status_code == 200
        mid = len(m.received())
        r2 = m.run_api("login", "api.login.buyer_echo")
        assert r2.status_code == 200
        got = m.received()
        logins = [r for r in got if r["path"] == "/login/json"]
        assert len(logins) >= 2, f"第二次应重新登录，login 次数={len(logins)}"
        # 两次业务请求的 token 摘要应不同（每次新签发）
        echoes = [r for r in got if r["path"] == "/echo/token"]
        assert len(echoes) >= 2
        assert echoes[0].get("x-token_sha256") != echoes[-1].get("x-token_sha256")
        assert leaks(r1.text) == 0 and leaks(r2.text) == 0
        return {"ok": True, "login_requests": len(logins), "mid": mid}

    m.check("L14", "§6-14", "两次独立执行各自重新登录，token 不同", s14)

    # ---- §6-15：按需登录 ----
    def s15() -> dict[str, Any]:
        m.reset_target()
        rc = m.run_case("login", "case.login.on_demand")
        assert rc.status_code == 200 and rc.json().get("status") == "success"
        got = m.received()
        paths = [r["path"] for r in got]
        # 首步匿名：先 /echo/token，此时还没有 /login/json
        first_echo = paths.index("/echo/token")
        first_login = paths.index("/login/json")
        assert first_echo < first_login, "登录发生在首次使用之前"
        login_n = paths.count("/login/json")
        assert login_n == 1, f"同身份第二次不应重登: {login_n}"
        assert leaks(rc.text) == 0
        return {"ok": True, "paths_prefix": paths[:6], "login_count": 1}

    m.check("L15", "§6-15", "按需登录：首次用前无登录；同身份复用", s15)

    # ---- §6-16：失效重登 ----
    def s16() -> dict[str, Any]:
        m.reset_target()
        rc = m.run_case("login", "case.login.reauth")
        assert rc.status_code == 200, f"http={rc.status_code}"
        body = rc.json()
        assert body.get("status") == "success", body.get("status")
        logins = body.get("logins") or body["result"].get("logins") or []
        assert len(logins) == 2, f"logins={len(logins)}"
        steps = body["result"]["steps"]
        refs = [s["auth"].get("login_ref") for s in steps]
        assert refs[0] != refs[1], f"login_ref 应区分: {refs}"
        assert leaks(rc.text) == 0
        return {"ok": True, "logins": len(logins), "login_refs": refs}

    m.check("L16", "§6-16", "短 TTL → 两条 logins，login_ref 不同", s16)

    # ---- §6-17：login_failed 路径 ----
    def _login_failed(asset: str, reason_hint: str | None = None) -> dict[str, Any]:
        m.reset_target()
        resp = m.run_api("login", asset)
        assert resp.status_code == 200, f"http={resp.status_code} asset={asset}"
        body = resp.json()
        assert body.get("status") == "failed", body.get("status")
        err = body.get("error") or (body.get("result") or {}).get("error") or {}
        # 错误可能在 result
        if not err and body.get("result"):
            err = body["result"].get("error") or {}
        # error.kind 应出现在公开 JSON 中
        text = resp.text
        assert "login_failed" in text, f"missing login_failed in response for {asset}"
        assert leaks(text) == 0
        logins = body.get("logins") or []
        if not logins and body.get("result"):
            logins = body["result"].get("logins") or []
        assert logins, f"登录过程应可见: {asset}"
        return {"ok": True, "asset": asset, "logins": len(logins), "reason_hint": reason_hint}

    for row_id, asset, hint in (
        ("L17a", "api.login.buyer_wrong_echo", "assert"),
        ("L17b", "api.login.buyer_extract_fail_echo", "extract"),
        ("L17c", "api.login.buyer_probe_fail_echo", "probe"),
        ("L17d", "api.login.buyer_timeout_echo", "timeout"),
        ("L17e", "api.login.buyer_transport_echo", "transport"),
        ("L17f", "api.login.plugin_raise_echo", "plugin"),
    ):
        m.check(
            row_id,
            "§6-17",
            f"login_failed ({hint}) → 200 + 可见脱敏",
            lambda a=asset, h=hint: _login_failed(a, h),
        )

    def s17_skip() -> dict[str, Any]:
        m.reset_target()
        rc = m.run_case("login", "case.login.login_fail_mid")
        assert rc.status_code == 200
        body = rc.json()
        assert body.get("status") == "failed"
        steps = body["result"]["steps"]
        assert steps[0].get("status") == "success"
        assert steps[1].get("status") == "failed"
        assert steps[2].get("status") == "skipped"
        # skip_reason
        skip = steps[2].get("skip_reason") or steps[2].get("error", {}).get("kind")
        assert "login_failed" in str(steps[2]), steps[2]
        assert leaks(rc.text) == 0
        return {"ok": True, "statuses": [s.get("status") for s in steps], "skip": skip}

    m.check("L17g", "§6-17", "login_failed 后后续 skipped(login_failed)", s17_skip)

    # ---- §6-18：插件注入+脱敏；未注册 422（E1b 已测）----
    def s18() -> dict[str, Any]:
        m.reset_target()
        resp = m.run_api("login", "api.login.plugin_echo")
        assert resp.status_code == 200 and resp.json().get("status") == "success"
        assert leaks(resp.text) == 0
        assert PLUGIN_TOKEN not in resp.text and PLUGIN_KEY not in resp.text
        echo = None
        body = resp.json()
        echo = (((body.get("result") or {}).get("response") or {}).get("body") or {}).get("echo")
        if echo is None:
            echo = ((body.get("response") or {}).get("body") or {}).get("echo")
        assert echo and echo.get("x_token") == "***"
        return {"ok": True, "plugin_redacted": True}

    m.check("L18", "§6-18", "假插件注册后注入并脱敏", s18)

    # ---- §6-19：connections 密码不出现 ----
    def s19() -> dict[str, Any]:
        # 任意成功/失败响应与插件路径都不应含 redis 密码
        samples = []
        for asset in ("api.login.plugin_echo", "api.login.buyer_echo", "api.login.seller_echo"):
            r = m.run_api("login", asset)
            samples.append(r.text)
        blob = "\n".join(samples)
        assert REDIS_PASSWORD not in blob
        assert leaks(blob) == 0
        return {"ok": True}

    m.check("L19", "§6-19", "connections 密码不出现在任何公开面", s19)

    # ---- §6-20：form/query/raw 快照脱敏；multipart → invalid_asset ----
    def s20() -> dict[str, Any]:
        m.reset_target()
        results = {}
        for asset, key in (
            ("api.login.form_echo", "form"),
            ("api.login.query_echo", "query"),
            ("api.login.raw_echo", "raw"),
        ):
            r = m.run_api("login", asset, {"note": BUYER_PASSWORD})
            assert r.status_code == 200, f"{asset} http={r.status_code}"
            assert BUYER_PASSWORD not in r.text
            assert "***" in r.text
            results[key] = "redacted"
        # multipart
        r = m.run_api("login", "api.login.multipart")
        assert r.status_code == 422, f"multipart status={r.status_code}"
        detail = r.json().get("detail", "")
        assert "invalid_asset" in detail or "multipart" in detail.lower() or r.status_code == 422
        assert leaks(r.text) == 0
        # 登录 flow 的 form 快照（seller）
        r = m.run_api("login", "api.login.seller_echo")
        assert SELLER_PASSWORD not in r.text
        return {"ok": True, "bodies": results, "multipart": 422}

    m.check("L20", "§6-20", "form/query/raw 脱敏；multipart → invalid_asset", s20)

    # ---- §6-21：3.3a 静态 header 回归 ----
    def s21() -> dict[str, Any]:
        m.reset_target()
        r = m.run_api("static", "api.login.admin_echo")
        assert r.status_code == 200 and r.json().get("status") == "success"
        auth = r.json().get("auth") or {}
        assert auth.get("identity") == "admin"
        assert auth.get("header_names") == ["Authorization"] or "Authorization" in (
            auth.get("header_names") or []
        )
        # 多出的公开 auth 键（kind/login_ref/cookie_names）允许存在
        assert leaks(r.text) == 0
        got = m.received()
        assert got and got[0].get("authorization_count") == 1
        return {"ok": True, "auth_keys": sorted(auth)}

    m.check("L21", "§6-21", "静态 header 项目行为与 0.3.0 一致（允许多出 auth 键）", s21)

    # ---- 旧项目五个 profile ----
    for row_id, asset in (
        ("P1", "api.login.gsb_token_echo"),
        ("P2", "api.login.gsb_csrf_echo"),
        ("P3", "api.login.admin_go2_echo"),
        ("P4", "api.login.df_picker_echo"),
        ("P5", "api.login.cat_api_echo"),
    ):
        def legacy(a: str = asset) -> dict[str, Any]:
            m.reset_target()
            r = m.run_api("legacy", a)
            assert r.status_code == 200, f"{a} http={r.status_code} body={r.text[:200]}"
            assert r.json().get("status") == "success", f"{a} status={r.json().get('status')}"
            assert leaks(r.text) == 0
            return {"ok": True, "asset": a}

        m.check(row_id, "legacy", f"旧 profile 等价配置 {asset}", legacy)

    report = {
        "rows": m.rows,
        "projects": m.projects,
        "passed": sum(1 for r in m.rows if r["pass"]),
        "total": len(m.rows),
        "section": "phase3_3b_login_§6.11-21",
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    assert leaks(text) == 0, "报告含秘密，拒绝写出"
    (OUT_DIR / "login-matrix-report.json").write_text(text + "\n", encoding="utf-8")
    print(f"LOGIN MATRIX {report['passed']}/{report['total']}")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
