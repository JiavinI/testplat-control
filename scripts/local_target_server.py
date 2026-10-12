"""本地 HTTP target：只听 127.0.0.1，供真实 Engine 矩阵使用，不访问公网。"""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SECRET = "srv-secret-token-matrix-9f31"


class Handler(BaseHTTPRequestHandler):
    """最小 demo 目标：create / get / status / slow。"""

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
        if self.path == "/demo/resources":
            self._json(201, {"id": "res-42", "access_token": SECRET})
        else:
            self.send_error(404)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/demo/resources/item", "/status/200"):
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
