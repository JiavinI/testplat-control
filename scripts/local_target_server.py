"""本地 HTTP target：只听 127.0.0.1，供真实 Engine 矩阵使用，不访问公网。

Phase 3.3a 回显端点保留；Phase 3.3b 新增登录相关端点（对齐 Engine FakeTarget）：
JSON/表单/query 登录、CSRF 预取 + Cookie 登录 + probe、短 TTL、回显 token/Cookie、
401、raw/form/query/json 回显、慢/挂端点。
Phase 3.3c：POST /createVCode、POST /vcode/login；验证码写入矩阵 Redis；签发秘密追加到临时文件。
Phase 3.3d：按用户名的登录计数、吊销已签发 token、always_401、登录失败开关；
业务端点对失效 / always_401 返回 401。

本服务自身绝不打印凭证原值：/__inspect 只暴露摘要、计数与路径。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

SECRET = "srv-secret-token-matrix-9f31"

# 3.3a 静态凭证头
CREDENTIAL_HEADERS = ("authorization", "x-api-key", "x-tenant-token")
# 3.3b 登录假秘密（与矩阵环境变量渲染结果一致；同时是泄密搜索目标）
BUYER_PASSWORD = "tp-fake-buyer-pass-71c2"
BUYER_PASSWORD_ALT = "tp-fake-buyer-pass-ALT99"
SELLER_PASSWORD = "tp-fake-seller-pass-93ab"
REDIS_PASSWORD = "tp-fake-redis-pass-5e0d"
PLUGIN_KEY = "tp-fake-plugin-key-11aa"
PLUGIN_TOKEN = "plug-token-5f5f5f5f5f"
CSRF_TOKEN = "csrf-ff00ee11dd22"
CSRF_SEED = "seed-0a0b0c0d0e"
FAIL_DETAIL = "detail-0123456789abcdefghij"
# Phase 3.3c：验证码登录假秘密（与矩阵环境变量一致；亦为泄密搜索目标）
DF_ADMIN_PASSWORD = "tp-fake-df-admin-pass-9f3a"
VCODE_KEY_PREFIX = "gsb:vcode:prefix:"

_RECEIVED: list[dict[str, object]] = []
_RECEIVED_LOCK = threading.Lock()
_STATE_LOCK = threading.Lock()
_ISSUED: list[str] = []
_SESSIONS: set[str] = set()
_COUNTER = 0
_EXPIRES_IN = 3600
_SESSION_MAX_AGE: int | None = None
# 3.3c 矩阵 Redis（目标服务写验证码用独立连接；插件只读 GET）
_REDIS_HOST = "127.0.0.1"
_REDIS_PORT = 0
_REDIS_PASSWORD: str | None = None
_REDIS_KEY_PREFIX = VCODE_KEY_PREFIX
_SKIP_REDIS_WRITE = False
_CREATE_VCODE_STATUS = 200
_VCODE_OMIT_TOKEN = False
_VCODE_FORCE_LOGIN_FAIL = False
_ISSUED_SECRETS_PATH: str | None = None
_REDIS_WRITE_COUNT = 0
# 3.3d：登录计数（按登录用户名，与矩阵身份 1:1）、吊销集合、401/登录失败开关
_LOGIN_COUNTS: dict[str, int] = {}
_REVOKED: set[str] = set()
_ALWAYS_401 = False
_FORCE_LOGIN_FAIL = False


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


def _append_issued_secret_unlocked(value: str) -> None:
    """调用方已持有 ``_STATE_LOCK`` 时写入签发秘密（锁不可重入，禁止再抢）。"""
    if not value or not _ISSUED_SECRETS_PATH:
        return
    with open(_ISSUED_SECRETS_PATH, "a", encoding="utf-8") as fh:
        fh.write(value + "\n")


def _append_issued_secret(value: str) -> None:
    """把签发的秘密追加到临时文件（不进证据目录）；供泄密搜索作动态目标。"""
    if not value or not _ISSUED_SECRETS_PATH:
        return
    with _STATE_LOCK:
        _append_issued_secret_unlocked(value)


def _bump_login_count(user: str) -> None:
    """登录成功后按用户名 +1（调用方已持锁或不需与签发同事务时由 _login_ok 路径调用）。"""
    with _STATE_LOCK:
        _LOGIN_COUNTS[user] = _LOGIN_COUNTS.get(user, 0) + 1


def _extract_bearer_or_xtoken(headers) -> str | None:  # noqa: ANN001
    xt = headers.get("X-TOKEN") or headers.get("X-Token")
    if xt:
        return xt
    authz = headers.get("Authorization") or ""
    if authz.lower().startswith("bearer "):
        return authz[7:].strip()
    return None


def _business_unauthorized(headers) -> bool:  # noqa: ANN001
    """业务端点：always_401 或 token 已被吊销 → 401。"""
    if _ALWAYS_401:
        return True
    token = _extract_bearer_or_xtoken(headers)
    if token and token in _REVOKED:
        return True
    return False


def _redis_write_code(uuid_value: str, code: str) -> None:
    """目标服务独立连接写入验证码；计入写次数供 commandstats 对账。"""
    global _REDIS_WRITE_COUNT
    if _SKIP_REDIS_WRITE or _REDIS_PORT <= 0:
        return
    import redis  # 仅矩阵目标服务使用；不进入 Control 运行时依赖

    client = redis.Redis(
        host=_REDIS_HOST,
        port=_REDIS_PORT,
        password=_REDIS_PASSWORD,
        db=0,
        socket_timeout=2.0,
        socket_connect_timeout=2.0,
        decode_responses=True,
    )
    try:
        client.set(f"{_REDIS_KEY_PREFIX}{uuid_value}", code)
        with _STATE_LOCK:
            _REDIS_WRITE_COUNT += 1
    finally:
        client.close()


def _next_token(user: str) -> str:
    global _COUNTER
    with _STATE_LOCK:
        _COUNTER += 1
        token = f"tok-{user}-{_COUNTER:04d}-a8f3e2c1d0"
        _ISSUED.append(token)
        _append_issued_secret_unlocked(token)
        return token


def _next_session() -> str:
    global _COUNTER
    with _STATE_LOCK:
        _COUNTER += 1
        session = f"sess-{_COUNTER:04d}-7b7b7b7b"
        _ISSUED.append(session)
        _SESSIONS.add(session)
        _append_issued_secret_unlocked(session)
        return session


class Handler(BaseHTTPRequestHandler):
    """本地 demo 目标：3.3a 回显 + 3.3b 登录 + 3.3c 验证码 + 3.3d 吊销/计数。"""

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
        if _FORCE_LOGIN_FAIL:
            self._json(200, {"code": 1, "msg": "forced login fail"})
            return
        if password not in (BUYER_PASSWORD, BUYER_PASSWORD_ALT, SELLER_PASSWORD):
            self._json(200, {"code": 1, "msg": "bad password"})
            return
        token = _next_token(user)
        _bump_login_count(user)
        data: dict[str, object] = {
            "token": token,
            # hash 不得镜像 token 原值：登录快照按键脱敏只覆盖 token 键，镜像字段会进 SQLite。
            "hash": _digest(token),
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
            global _REDIS_WRITE_COUNT
            with _RECEIVED_LOCK:
                _RECEIVED.clear()
            with _STATE_LOCK:
                _ISSUED.clear()
                _SESSIONS.clear()
                _REDIS_WRITE_COUNT = 0
                _LOGIN_COUNTS.clear()
                # 吊销集合保留：已写入 issued-secrets 的旧 token 仍可被业务拒绝与泄密搜索覆盖
            self._json(200, {"reset": True})
            return
        if path == "/__inspect/config":
            # 矩阵可调短 TTL / Cookie Max-Age / 3.3c 验证码行为；仅接受 JSON，不回显秘密
            try:
                cfg = json.loads(text or "{}")
            except json.JSONDecodeError:
                self._json(400, {"error": "bad json"})
                return
            global _EXPIRES_IN, _SESSION_MAX_AGE, _SKIP_REDIS_WRITE
            global _CREATE_VCODE_STATUS, _VCODE_OMIT_TOKEN, _VCODE_FORCE_LOGIN_FAIL
            global _ALWAYS_401, _FORCE_LOGIN_FAIL
            with _STATE_LOCK:
                if "expires_in" in cfg:
                    _EXPIRES_IN = int(cfg["expires_in"])
                if "session_max_age" in cfg:
                    val = cfg["session_max_age"]
                    _SESSION_MAX_AGE = None if val is None else int(val)
                if "skip_redis_write" in cfg:
                    _SKIP_REDIS_WRITE = bool(cfg["skip_redis_write"])
                if "create_vcode_status" in cfg:
                    _CREATE_VCODE_STATUS = int(cfg["create_vcode_status"])
                if "vcode_omit_token" in cfg:
                    _VCODE_OMIT_TOKEN = bool(cfg["vcode_omit_token"])
                if "vcode_force_login_fail" in cfg:
                    _VCODE_FORCE_LOGIN_FAIL = bool(cfg["vcode_force_login_fail"])
                # 3.3d：吊销当前已签发 token；always_401；强制登录失败
                if cfg.get("revoke_current_token") is True:
                    # 内存已签发 + issued-secrets 文件（reset 清空 _ISSUED；缓存可能仍持旧 token）
                    for tok in list(_ISSUED):
                        if tok.startswith("tok-") or tok.startswith("sess-"):
                            _REVOKED.add(tok)
                    if _ISSUED_SECRETS_PATH:
                        try:
                            with open(_ISSUED_SECRETS_PATH, encoding="utf-8") as fh:
                                for line in fh:
                                    item = line.strip()
                                    if item.startswith("tok-") or item.startswith("sess-"):
                                        _REVOKED.add(item)
                        except OSError:
                            pass
                if "always_401" in cfg:
                    _ALWAYS_401 = bool(cfg["always_401"])
                if "force_login_fail" in cfg:
                    _FORCE_LOGIN_FAIL = bool(cfg["force_login_fail"])
                if "clear_revoked" in cfg and cfg["clear_revoked"]:
                    _REVOKED.clear()
            self._json(200, {"ok": True})
            return

        _record(path, "POST", self.headers)

        if path == "/demo/resources":
            self._json(201, {"id": "res-42", "access_token": SECRET})
            return
        if path in ("/login/json", "/login/json-alt"):
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
            if _FORCE_LOGIN_FAIL:
                self._redirect("/login")
                return
            form = {k: v[0] for k, v in parse_qs(text).items()}
            csrf = form.get("_csrf")
            password = form.get("password") or form.get("LoginForm[password]")
            cookie = self.headers.get("Cookie") or ""
            if csrf != CSRF_TOKEN or password != SELLER_PASSWORD or CSRF_SEED not in cookie:
                self._redirect("/login")
                return
            session = _next_session()
            user = form.get("username") or form.get("LoginForm[username]") or "seller001"
            _bump_login_count(user)
            cookie_hdr = f"SESSION={session}; Path=/"
            if _SESSION_MAX_AGE is not None:
                cookie_hdr += f"; Max-Age={_SESSION_MAX_AGE}"
            self._redirect("/home", [("Set-Cookie", cookie_hdr)])
            return
        if path == "/echo/raw":
            if _business_unauthorized(self.headers):
                self._json(401, {"msg": "unauthorized"})
                return
            self._json(200, {"raw": text, "content_type": self.headers.get("Content-Type")})
            return
        if path == "/echo/form":
            if _business_unauthorized(self.headers):
                self._json(401, {"msg": "unauthorized"})
                return
            form = {k: v[0] for k, v in parse_qs(text).items()}
            self._json(200, {"form": form, "content_type": self.headers.get("Content-Type")})
            return
        if path == "/echo/json":
            if _business_unauthorized(self.headers):
                self._json(401, {"msg": "unauthorized"})
                return
            self._json(200, json.loads(text or "null"))
            return
        if path == "/createVCode":
            # 返回新 uuid；默认把 4 位验证码写入矩阵 Redis（可配置跳过，用于 key 不存在）
            if _CREATE_VCODE_STATUS >= 400:
                self._json(_CREATE_VCODE_STATUS, {"code": 1, "msg": "create failed"})
                return
            uid = str(uuid4())
            # 固定 4 位数字验证码；原值只进 Redis 与签发秘密文件，不进日志
            code = f"{(int(uid.replace('-', '')[:8], 16) % 9000) + 1000:04d}"
            _append_issued_secret(uid)
            _append_issued_secret(code)
            _redis_write_code(uid, code)
            self._json(200, {"code": 0, "data": {"uuid": uid}})
            return
        if path == "/vcode/login":
            # form：校验验证码与 userKey；成功返回 token 与 userId
            if _VCODE_FORCE_LOGIN_FAIL or _FORCE_LOGIN_FAIL:
                self._json(401, {"code": 1, "msg": "forced fail"})
                return
            form = {k: v[0] for k, v in parse_qs(text).items()}
            username = form.get("username") or ""
            password = form.get("password")
            code = form.get("code") or ""
            user_key = form.get("userKey") or ""
            if password != DF_ADMIN_PASSWORD or not user_key or not code:
                self._json(401, {"code": 1, "msg": "bad credentials"})
                return
            expected = None
            if _REDIS_PORT > 0 and not _SKIP_REDIS_WRITE:
                import redis

                client = redis.Redis(
                    host=_REDIS_HOST,
                    port=_REDIS_PORT,
                    password=_REDIS_PASSWORD,
                    db=0,
                    socket_timeout=2.0,
                    socket_connect_timeout=2.0,
                    decode_responses=True,
                )
                try:
                    expected = client.get(f"{_REDIS_KEY_PREFIX}{user_key}")
                finally:
                    client.close()
            if expected is None or code != expected:
                self._json(401, {"code": 1, "msg": "bad code"})
                return
            if _VCODE_OMIT_TOKEN:
                self._json(200, {"code": 0, "data": {"userId": "10001"}})
                return
            token = _next_token(username or "dfadmin")
            _bump_login_count(username or "dfadmin")
            self._json(200, {"code": 0, "data": {"token": token, "userId": "10001"}})
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
                reqs = list(_RECEIVED)
            with _STATE_LOCK:
                payload = {
                    "requests": reqs,
                    "issued_count": len(_ISSUED),
                    "session_count": len(_SESSIONS),
                    "redis_write_count": _REDIS_WRITE_COUNT,
                    "login_counts": dict(_LOGIN_COUNTS),
                    "revoked_count": len(_REVOKED),
                    "always_401": _ALWAYS_401,
                    "force_login_fail": _FORCE_LOGIN_FAIL,
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
            if _business_unauthorized(self.headers):
                self._json(401, {"msg": "unauthorized"})
                return
            self._json(
                200,
                {
                    "echo": {
                        "x_token": self.headers.get("X-TOKEN") or self.headers.get("X-Token"),
                        "cookie": self.headers.get("Cookie"),
                        "csrf": self.headers.get("X-CSRF-Token"),
                        "authz": self.headers.get("Authorization"),
                        "x_uid": self.headers.get("X-UID") or self.headers.get("X-User-Id"),
                        "x_user_id": self.headers.get("X-USER-ID") or self.headers.get("X-User-Id"),
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
    parser = argparse.ArgumentParser(description="本地 Engine target（3.3a+3.3b+3.3c+3.3d）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18099)
    parser.add_argument("--redis-host", default="127.0.0.1")
    parser.add_argument("--redis-port", type=int, default=0)
    parser.add_argument("--redis-password", default="")
    parser.add_argument("--redis-key-prefix", default=VCODE_KEY_PREFIX)
    parser.add_argument("--issued-secrets", default="")
    parser.add_argument("--skip-redis-write", action="store_true")
    args = parser.parse_args()
    global _REDIS_HOST, _REDIS_PORT, _REDIS_PASSWORD, _REDIS_KEY_PREFIX
    global _ISSUED_SECRETS_PATH, _SKIP_REDIS_WRITE
    _REDIS_HOST = args.redis_host
    _REDIS_PORT = int(args.redis_port)
    _REDIS_PASSWORD = args.redis_password or None
    _REDIS_KEY_PREFIX = args.redis_key_prefix
    _ISSUED_SECRETS_PATH = args.issued_secrets or None
    _SKIP_REDIS_WRITE = bool(args.skip_redis_write)
    # 绑定仅允许本机回环；矩阵 Redis 亦须 127.0.0.1。
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("target 只允许绑定 127.0.0.1")
    if _REDIS_HOST not in ("127.0.0.1", "localhost", "::1", ""):
        raise SystemExit("矩阵 Redis 只允许 127.0.0.1")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"TARGET_READY http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
