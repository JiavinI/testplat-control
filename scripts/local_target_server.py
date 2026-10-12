"""本地 HTTP target：只听 127.0.0.1，供真实 Engine 矩阵使用，不访问公网。"""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SECRET = "srv-secret-token-matrix-9f31"

# Phase 3.3a 回显端点（手册 §0.4 L2、§7-1）：
# - /echo/headers 把凭证 header 原样回显到非敏感键（seen_*）下，
#   验证 Engine 按值脱敏（§6-2、§6-4）；
# - /echo/error 把收到的凭证放进 401 错误正文，验证失败结果按值脱敏（§6-3）。
# 本服务自身绝不打印、记录凭证原值：/__inspect 只暴露凭证头的 sha256 与出现次数，
# 供矩阵断言“确实发出了正确的凭证、且只发一份”（H2、M3）；原值只出现在回显端点的响应里。
CREDENTIAL_HEADERS = ("authorization", "x-api-key", "x-tenant-token")
_RECEIVED: list[dict[str, object]] = []
_RECEIVED_LOCK = threading.Lock()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _record(path: str, headers) -> None:  # noqa: ANN001
    """记录一次请求的头摘要：凭证头只存 sha256 与次数，其余头只存本矩阵关心的少数几个。"""
    entry: dict[str, object] = {"path": path}
    for name in CREDENTIAL_HEADERS:
        values = headers.get_all(name) or []
        entry[f"{name}_count"] = len(values)
        entry[f"{name}_sha256"] = [_digest(v) for v in values]
    entry["x-resource-id"] = headers.get("X-Resource-Id")
    entry["x-injected_count"] = len(headers.get_all("X-Injected") or [])
    with _RECEIVED_LOCK:
        _RECEIVED.append(entry)


class Handler(BaseHTTPRequestHandler):
    """最小 demo 目标：create / get / status / slow，以及 Phase 3.3a 回显端点。"""

    def _json(self, status: int, payload: object) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        if self.path == "/__inspect/reset":
            with _RECEIVED_LOCK:
                _RECEIVED.clear()
            self._json(200, {"reset": True})
            return
        _record(self.path, self.headers)
        if self.path == "/demo/resources":
            self._json(201, {"id": "res-42", "access_token": SECRET})
        else:
            self.send_error(404)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/__inspect":
            with _RECEIVED_LOCK:
                self._json(200, {"requests": list(_RECEIVED)})
            return
        _record(self.path, self.headers)
        if self.path == "/echo/headers":
            # 故意把凭证回显到非敏感键名下：按键脱敏抓不到，只能靠 Engine 按值替换
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
        elif self.path == "/echo/error":
            # 故意把凭证写进错误正文（§6-3）
            seen = (
                self.headers.get("Authorization")
                or self.headers.get("X-Api-Key")
                or self.headers.get("X-Tenant-Token")
            )
            self._json(401, {"message": f"rejected credential: {seen}", "hint": seen})
        elif self.path in ("/demo/resources/item", "/status/200"):
            self._json(200, {"ok": True, "id": "item-1"})
        elif self.path == "/demo/slow":
            time.sleep(1.5)
            self._json(200, {"slow": True})
        else:
            self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="本地 Engine target")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18099)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"TARGET_READY http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
