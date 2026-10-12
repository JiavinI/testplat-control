#!/usr/bin/env bash
# 启动本地 target + 真实 Engine Control + 前端，跑浏览器矩阵；不访问公网。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TARGET_PORT="${TARGET_PORT:-18099}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
OUT_DIR="${E2E_OUT_DIR:-$ROOT/frontend/screenshots/phase3-real-engine}"
mkdir -p "$OUT_DIR"
# 保证后续日志/报告目录存在

# 写入运行时 env：local 指向本机 target
python3 - <<PY
from pathlib import Path
path = Path("$ROOT/tests/fixtures/config/envs/test.yaml")
path.write_text(
    "# 由 run_real_engine_matrix.sh 生成；local 指向本机 target，不访问公网。\n"
    "api_hosts:\n"
    "  test_server: http://127.0.0.1:9\n"
    "  local: http://127.0.0.1:$TARGET_PORT\n"
    "  dead: http://127.0.0.1:1\n"
    "timeout:\n"
    "  default: 30\n",
    encoding="utf-8",
)
print("wrote", path)
PY

PIDS=()
cleanup() {
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT

uv run python scripts/local_target_server.py --port "$TARGET_PORT" >"$OUT_DIR/target.log" 2>&1 &
PIDS+=($!)
uv run uvicorn testplat_control.harness_real_matrix:app --host 127.0.0.1 --port "$BACKEND_PORT" >"$OUT_DIR/backend.log" 2>&1 &
PIDS+=($!)
(
  cd frontend
  pnpm exec vite --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort
) >"$OUT_DIR/frontend.log" 2>&1 &
PIDS+=($!)

# 等待就绪
for i in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:$BACKEND_PORT/health" >/dev/null \
    && curl -sf "http://127.0.0.1:$FRONTEND_PORT" >/dev/null \
    && curl -sf "http://127.0.0.1:$TARGET_PORT/status/200" >/dev/null; then
    break
  fi
  sleep 0.5
  if [[ $i -eq 60 ]]; then
    echo "服务启动超时" >&2
    tail -n 40 "$OUT_DIR"/*.log >&2 || true
    exit 1
  fi
done

echo "services ready; running matrix"
(
  cd frontend
  E2E_BASE_URL="http://127.0.0.1:$FRONTEND_PORT" \
  E2E_OUT_DIR="$OUT_DIR" \
  pnpm exec node scripts/e2e-real-engine-matrix.mjs
)
