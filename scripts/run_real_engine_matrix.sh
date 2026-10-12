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

# 生成运行时配置到临时目录（不改写已跟踪的 tests/fixtures/config/envs/test.yaml）：
# local 指向本机 target，不访问公网。
E2E_CONFIG_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/phase3-matrix-config.XXXXXX")"
mkdir -p "$E2E_CONFIG_ROOT/envs"
cp -R "$ROOT/tests/fixtures/config/." "$E2E_CONFIG_ROOT/"
cat >"$E2E_CONFIG_ROOT/envs/test.yaml" <<YAML
# 由 run_real_engine_matrix.sh 生成（临时目录）；local 指向本机 target，不访问公网。
api_hosts:
  test_server: http://127.0.0.1:9
  local: http://127.0.0.1:$TARGET_PORT
  dead: http://127.0.0.1:1
timeout:
  default: 30
YAML
echo "wrote $E2E_CONFIG_ROOT/envs/test.yaml"
export E2E_CONFIG_ROOT

PIDS=()
cleanup() {
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  rm -rf "$E2E_CONFIG_ROOT"
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
  E2E_CONFIG_ROOT="$E2E_CONFIG_ROOT" \
  pnpm exec node scripts/e2e-real-engine-matrix.mjs
)
