"""本地 HTTP target：只听 127.0.0.1，供真实 Engine 矩阵使用，不访问公网。

Phase 3.3a 回显端点保留；Phase 3.3b 新增登录相关端点（对齐 Engine FakeTarget）：
JSON/表单/query 登录、CSRF 预取 + Cookie 登录 + probe、短 TTL、回显 token/Cookie、
401、raw/form/query/json 回显、慢/挂端点。

本服务自身绝不打印凭证原值：/__inspect 只暴露摘要与路径。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

SECRET = "srv-secret-token-matrix-9f31"

# 3.3a 静态凭证头
CREDENTIAL_HEADERS = ("authorization", "x-api-key", "x-tenant-token")
# 3.3b 登录假秘密（与矩阵环境变量渲染结果一致；同时是泄密搜索目标）
BUYER_PASSWORD = "tp-fake-buyer-pass-71c2"
SELLER_PASSWORD = "tp-fake-seller-pass-93ab"
REDIS_PASSWORD = "tp-fake-redis-pass-5e0d"
PLUGIN_KEY = "tp-fake-plugin-key-11aa"
PLUGIN_TOKEN = "plug-token-5f5f5f5f5f"
CSRF_TOKEN = "csrf-ff00ee11dd22"
CSRF_SEED = "seed-0a0b0c0d0e"
FAIL_DETAIL = "detail-0123456789abcdefghij"

_RECEIVED: list[dict[str, object]] = []
_RECEIVED_LOCK = threading.Lock()
_STATE_LOCK = threading.Lock()
_ISSUED: list[str] = []
_SESSIONS: set[str] = set()
_COUNTER = 0
_EXPIRES_IN = 3600
_SESSION_MAX_AGE: int | None = None


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _record(path: str, method: str, headers) -> None:  # noqa: ANN001
    """记录一次请求摘要：凭证头只存 sha256 与次数；登录相关头亦摘要。"""
    entry: dict[str, object] = {"path": path, "method": method}
    for name in CREDENTIAL_HEADERS:
        values = headers.get_all(name) or []
        entry[f"{name}_count"] = len(values)
        entry[f"{name}_sha256"] = [_digest(v) for v in values]
    for name in ("x-token", "x-csrf-token", "x-user-id", "x-uid", "x-source", "cookie"):
        if name == "cookie":
            raw = headers.get("Cookie")
            values = [raw] if raw else []
        else:
            values = headers.get_all(name) or []
        entry[f"{name}_count"] = len(values)
        entry[f"{name}_sha256"] = [_digest(v) for v in values if v]
    entry["x-resource-id"] = headers.get("X-Resource-Id")
    entry["x-injected_count"] = len(headers.get_all("X-Injected") or [])
    with _RECEIVED_LOCK:
        _RECEIVED.append(entry)


def _next_token(user: str) -> str:
    global _COUNTER
    with _STATE_LOCK:
        _COUNTER += 1
        token = f"tok-{user}-{_COUNTER:04d}-a8f3e2c1d0"
        _ISSUED.append(token)
        return token


def _next_session() -> str:
    global _COUNTER
    with _STATE_LOCK:
        _COUNTER += 1
        session = f"sess-{_COUNTER:04d}-7b7b7b7b"
        _ISSUED.append(session)
        _SESSIONS.add(session)
        return session


class Handler(BaseHTTPRequestHandler):
    """本地 demo 目标：3.3a 回显 + 3.3b 登录端点。"""

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _json(
        self,
        status: int,
        payload: object,
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in extra_headers or []:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _text(
        self,
        status: int,
        body: str,
        content_type: str = "text/html",
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for k, v in extra_headers or []:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location: str, extra_headers: list[tuple[str, str]] | None = None) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        for k, v in extra_headers or []:
            self.send_header(k, v)
        self.end_headers()

    def _login_ok(
        self,
        user: str,
        password: str | None,
        *,
        csrf: bool = False,
        expires_in: int | None = None,
    ) -> None:
        if password not in (BUYER_PASSWORD, SELLER_PASSWORD):
            self._json(200, {"code": 1, "msg": "bad password"})
            return
        token = _next_token(user)
        data: dict[str, object] = {
            "token": token,
            "hash": token,
            "userId": "10001",
            "expiresIn": expires_in if expires_in is not None else _EXPIRES_IN,
        }
        if csrf:
            data["csrfToken"] = CSRF_TOKEN
        self._json(200, {"code": 0, "data": data})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_body()
        text = body.decode("utf-8", errors="replace")

        if path == "/__inspect/reset":
            with _RECEIVED_LOCK:
                _RECEIVED.clear()
            with _STATE_LOCK:
                _ISSUED.clear()
                _SESSIONS.clear()
            self._json(200, {"reset": True})
            return
        if path == "/__inspect/config":
            # 矩阵可调短 TTL / Cookie Max-Age；仅接受 JSON 数字，不回显秘密
            try:
                cfg = json.loads(text or "{}")
            except json.JSONDecodeError:
                self._json(400, {"error": "bad json"})
                return
            global _EXPIRES_IN, _SESSION_MAX_AGE
            with _STATE_LOCK:
                if "expires_in" in cfg:
                    _EXPIRES_IN = int(cfg["expires_in"])
                if "session_max_age" in cfg:
                    val = cfg["session_max_age"]
                    _SESSION_MAX_AGE = None if val is None else int(val)
            self._json(200, {"ok": True})
            return

        _record(path, "POST", self.headers)

        if path == "/demo/resources":
            self._json(201, {"id": "res-42", "access_token": SECRET})
            return
        if path == "/login/json":
            data = json.loads(text or "{}")
            self._login_ok(str(data.get("username", "?")), data.get("password"))
            return
        if path == "/login/form":
            form = {k: v[0] for k, v in parse_qs(text).items()}
            self._login_ok(form.get("username", "?"), form.get("password"))
            return
        if path == "/login/short":
            # 故意返回过短 token（<8），验证命名值下限
            self._json(200, {"code": 0, "data": {"token": "abc"}})
            return
        if path == "/login/short-ttl":
            data = json.loads(text or "{}")
            self._login_ok(str(data.get("username", "?")), data.get("password"), expires_in=1)
            return
        if path == "/login/fail":
            self._json(200, {"code": 2, "msg": "locked", "trace": FAIL_DETAIL})
            return
        if path == "/csrf/login":
            form = {k: v[0] for k, v in parse_qs(text).items()}
            csrf = form.get("_csrf")
            password = form.get("password") or form.get("LoginForm[password]")
            cookie = self.headers.get("Cookie") or ""
            if csrf != CSRF_TOKEN or password != SELLER_PASSWORD or CSRF_SEED not in cookie:
                self._redirect("/login")
                return
            session = _next_session()
            cookie_hdr = f"SESSION={session}; Path=/"
            if _SESSION_MAX_AGE is not None:
                cookie_hdr += f"; Max-Age={_SESSION_MAX_AGE}"
            self._redirect("/home", [("Set-Cookie", cookie_hdr)])
            return
        if path == "/echo/raw":
            self._json(200, {"raw": text, "content_type": self.headers.get("Content-Type")})
            return
        if path == "/echo/form":
            form = {k: v[0] for k, v in parse_qs(text).items()}
            self._json(200, {"form": form, "content_type": self.headers.get("Content-Type")})
            return
        if path == "/echo/json":
            self._json(200, json.loads(text or "null"))
            return
        if path == "/plugin/login":
            # 假插件可选真实 HTTP；矩阵默认走插件内部 record，此端点作备用
            self._json(200, {"issued": PLUGIN_TOKEN})
            return
        self.send_error(404)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        qs = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        if path == "/__inspect":
            with _RECEIVED_LOCK:
                payload = {
                    "requests": list(_RECEIVED),
                    "issued_count": len(_ISSUED),
                    "session_count": len(_SESSIONS),
                }
            self._json(200, payload)
            return

        _record(path, "GET", self.headers)

        if path == "/echo/headers":
            self._json(
                200,
                {
                    "id": "echo-1",
                    "echo": {
                        "seen_a": self.headers.get("Authorization"),
                        "seen_k": self.headers.get("X-Api-Key"),
                        "seen_t": self.headers.get("X-Tenant-Token"),
                        "credential_count": len(self.headers.get_all("Authorization") or []),
                        "resource": self.headers.get("X-Resource-Id"),
                    },
                },
            )
            return
        if path == "/echo/error":
            seen = (
                self.headers.get("Authorization")
                or self.headers.get("X-Api-Key")
                or self.headers.get("X-Tenant-Token")
            )
            self._json(401, {"message": f"rejected credential: {seen}", "hint": seen})
            return
        if path in ("/demo/resources/item", "/status/200"):
            self._json(200, {"ok": True, "id": "item-1"})
            return
        if path == "/demo/slow":
            time.sleep(1.5)
            self._json(200, {"slow": True})
            return
        if path in ("/login/query", "/login/query-csrf"):
            self._login_ok(qs.get("username", "?"), qs.get("password"), csrf=path.endswith("csrf"))
            return
        if path == "/login/slow":
            time.sleep(2.0)
            self._json(200, {"code": 0, "data": {"token": "too-late"}})
            return
        if path == "/csrf/login":
            html = f'<html><head><meta name="csrf-token" content="{CSRF_TOKEN}"></head></html>'
            self._text(
                200,
                html,
                extra_headers=[
                    ("Set-Cookie", f"_csrf={CSRF_SEED}; Path=/"),
                    ("Set-Cookie", "lang=zh-CN; Path=/"),
                ],
            )
            return
        if path == "/csrf/protected":
            cookie = self.headers.get("Cookie") or ""
            with _STATE_LOCK:
                ok = any(f"SESSION={s}" in cookie for s in _SESSIONS)
            if ok:
                self._text(200, "<html>ok</html>", extra_headers=[("x-uid", "777")])
            else:
                self._text(200, '<form id="loginFrom"></form>')
            return
        if path == "/echo/token":
            self._json(
                200,
                {
                    "echo": {
                        "x_token": self.headers.get("X-TOKEN") or self.headers.get("X-Token"),
                        "cookie": self.headers.get("Cookie"),
                        "csrf": self.headers.get("X-CSRF-Token"),
                        "authz": self.headers.get("Authorization"),
                        "x_uid": self.headers.get("X-UID") or self.headers.get("X-User-Id"),
                        "x_source": self.headers.get("X-SOURCE") or self.headers.get("X-Source"),
                    }
                },
            )
            return
        if path == "/echo/query":
            self._json(200, {"query": qs})
            return
        if path == "/protected/401":
            self._json(401, {"msg": "unauthorized"})
            return
        if path == "/business/slow":
            time.sleep(2.0)
            self._json(200, {"slow": True})
            return
        self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="本地 Engine target（3.3a+3.3b）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18099)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"TARGET_READY http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
