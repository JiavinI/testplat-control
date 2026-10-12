#!/usr/bin/env bash
# 启动本地 target + 真实 Engine Control + 前端，跑真实 Engine 矩阵；不访问公网。
#
# Phase 3.3a 起包含四段（全部基于真实 Engine，不用 route mock）：
#   1. 鉴权 HTTP 矩阵（scripts/auth_real_engine_matrix.py，设计稿 §6 全部 10 条 + B2 + Q2/Q3/Q7）
#   2. 身份展示截图（frontend/scripts/e2e-auth-real-engine.mjs，390/1440，逐张 DOM 秘密搜索）
#   3. Phase 3 回归：无 auth 配置的项目跑原有浏览器矩阵（结果须不变）
#   4. 泄密全文搜索（scripts/auth_leak_search.py：日志、SQLite、报告、DOM 证据、docs）
#
# 不变量：
#   - 所有配置、资产副本、SQLite 都写在临时目录；已跟踪的 tests/fixtures 从不被改写。
#   - 假秘密只以环境变量注入 Control 进程，本脚本不 echo、不写入任何文件。
#   - 新截图与证据写入 frontend/screenshots/phase3_3-real-engine/；Phase 3 回归段的截图写临时目录，
#     不会重新生成已跟踪的 phase3-real-engine/ 截图。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TARGET_PORT="${TARGET_PORT:-18099}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
AUTH_OUT_DIR="${AUTH_OUT_DIR:-$ROOT/frontend/screenshots/phase3_3-real-engine}"
mkdir -p "$AUTH_OUT_DIR"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/phase3_3-matrix.XXXXXX")"
# Phase 3 回归段的截图输出：默认临时目录（不改写已跟踪截图）
OUT_DIR="${E2E_OUT_DIR:-$WORK/phase3-regression}"
mkdir -p "$OUT_DIR"

write_env() {
  # $1 = config root；local 指向本机 target，不访问公网。
  mkdir -p "$1/envs"
  cat >"$1/envs/test.yaml" <<YAML
# 由 run_real_engine_matrix.sh 生成（临时目录）；local 指向本机 target，不访问公网。
api_hosts:
  test_server: http://127.0.0.1:9
  local: http://127.0.0.1:$TARGET_PORT
  dead: http://127.0.0.1:1
timeout:
  default: 30
YAML
}

# Phase 3 回归用的 config root（无 auth/ 目录 → auth=None，与 Phase 3 一致）
E2E_CONFIG_ROOT="$WORK/cfg-phase3"
mkdir -p "$E2E_CONFIG_ROOT"
cp -R "$ROOT/tests/fixtures/config/." "$E2E_CONFIG_ROOT/"
write_env "$E2E_CONFIG_ROOT"
export E2E_CONFIG_ROOT

# 鉴权矩阵资产：原 fixtures + auth_matrix 资产合并到临时目录
AUTH_ASSETS_ROOT="$WORK/assets"
mkdir -p "$AUTH_ASSETS_ROOT"
cp -R "$ROOT/tests/fixtures/assets/." "$AUTH_ASSETS_ROOT/"
cp -R "$ROOT/tests/fixtures/auth_matrix/assets/." "$AUTH_ASSETS_ROOT/"

# 每种 auth 配置一个 config root；配置文件只含 ${secret:} 占位
make_root() {
  # $1 = 名称，$2 = auth fixture 文件名（空表示无 auth 配置）
  local dir="$WORK/cfg-$1"
  write_env "$dir"
  if [[ -n "$2" ]]; then
    mkdir -p "$dir/auth"
    cp "$ROOT/tests/fixtures/auth_matrix/auth/$2" "$dir/auth/test.yaml"
  fi
  echo "$dir"
}
export MATRIX_ROOT_AUTH="$(make_root auth main.yaml)"
export MATRIX_ROOT_NOAUTH="$(make_root noauth "")"
export MATRIX_ROOT_BAD_YAML="$(make_root bad-yaml bad-yaml.yaml)"
export MATRIX_ROOT_LITERAL_CR="$(make_root literal-cr literal-cr.yaml)"
export MATRIX_ROOT_LITERAL_LF="$(make_root literal-lf literal-lf.yaml)"
export MATRIX_ROOT_LITERAL_NUL="$(make_root literal-nul literal-nul.yaml)"
export MATRIX_ROOT_DEFAULT_MISSING="$(make_root default-missing default-missing.yaml)"
export MATRIX_ROOT_HEADER_CASE_DUP="$(make_root header-case-dup header-case-dup.yaml)"
export MATRIX_ASSETS_ROOT="$AUTH_ASSETS_ROOT"
export MATRIX_TARGET_URL="http://127.0.0.1:$TARGET_PORT"
export MATRIX_BACKEND_URL="http://127.0.0.1:$BACKEND_PORT"
export MATRIX_OUT_DIR="$AUTH_OUT_DIR"

# 文件型 SQLite（harness_real_matrix 读取 MATRIX_SQLITE_PATH 改绑），便于对原始行做全文搜索
DB_PATH="$WORK/control.db"
# 根 logger 设为 DEBUG 输出到 stderr：Control 与 Engine 的全部日志都进入 backend.log 供泄密搜索
cat >"$WORK/log.json" <<'JSON'
{
  "version": 1,
  "disable_existing_loggers": false,
  "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
  "handlers": {"stderr": {"class": "logging.StreamHandler", "formatter": "plain", "stream": "ext://sys.stderr"}},
  "root": {"level": "DEBUG", "handlers": ["stderr"]}
}
JSON

PIDS=()
cleanup() {
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  rm -rf "$WORK"
}
trap cleanup EXIT

uv run python scripts/local_target_server.py --port "$TARGET_PORT" >"$AUTH_OUT_DIR/target.log" 2>&1 &
PIDS+=($!)
# 假秘密（手册 §0.3-3）只进 Control 进程环境：
#   TESTPLAT_CRLF_TOKEN / TESTPLAT_LF_TOKEN 含 CR/LF（B2 → 身份不可用，请求不发出）；
#   TESTPLAT_EMPTY_TOKEN 为空、TESTPLAT_SHORT_TOKEN 短于 8、TESTPLAT_MISSING_TOKEN 不设置；
#   AWS_SECRET_ACCESS_KEY 是白名单外的假值，用来证明它不会被读取（§6-6）。
# NUL 无法放进 POSIX 环境变量值，变量值含 NUL 的情形由 Control 单测覆盖（见交付说明）。
env \
  -u TESTPLAT_MISSING_TOKEN \
  MATRIX_SQLITE_PATH="$DB_PATH" \
  TESTPLAT_ADMIN_TOKEN="tp-fake-secret-9f31c2a7" \
  TESTPLAT_PARTNER_KEY="tp-fake-partner-4c8e11d0" \
  TESTPLAT_EMPTY_TOKEN="" \
  TESTPLAT_SHORT_TOKEN="abc1234" \
  TESTPLAT_CRLF_TOKEN=$'tp-fake-secret-9f31c2a7\r\nX-Injected: yes' \
  TESTPLAT_LF_TOKEN=$'tp-fake-secret-9f31c2a7\nX-Injected: yes' \
  AWS_SECRET_ACCESS_KEY="tp-fake-aws-7d2e9b10" \
  uv run uvicorn testplat_control.harness_real_matrix:app --host 127.0.0.1 --port "$BACKEND_PORT" \
  --log-config "$WORK/log.json" >"$AUTH_OUT_DIR/backend.log" 2>&1 &
PIDS+=($!)
(
  cd frontend
  pnpm exec vite --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort
) >"$AUTH_OUT_DIR/frontend.log" 2>&1 &
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
    tail -n 40 "$AUTH_OUT_DIR"/*.log >&2 || true
    exit 1
  fi
done

STATUS=0
echo "services ready; [1/4] auth HTTP matrix"
uv run python scripts/auth_real_engine_matrix.py || STATUS=1

echo "[2/4] auth browser screenshots (real Engine)"
(
  cd frontend
  E2E_BASE_URL="http://127.0.0.1:$FRONTEND_PORT" \
  E2E_OUT_DIR="$AUTH_OUT_DIR" \
  E2E_AUTH_ASSETS_ROOT="$AUTH_ASSETS_ROOT" \
  E2E_AUTH_CONFIG_ROOT="$MATRIX_ROOT_AUTH" \
  pnpm exec node scripts/e2e-auth-real-engine.mjs
) || STATUS=1

echo "[3/4] Phase 3 regression (no auth config)"
(
  cd frontend
  E2E_BASE_URL="http://127.0.0.1:$FRONTEND_PORT" \
  E2E_OUT_DIR="$OUT_DIR" \
  E2E_CONFIG_ROOT="$E2E_CONFIG_ROOT" \
  pnpm exec node scripts/e2e-real-engine-matrix.mjs
) || STATUS=1
cp "$OUT_DIR/real-engine-matrix-report.json" "$AUTH_OUT_DIR/phase3-regression-report.json" 2>/dev/null || true

# 停服务后再搜索，确保日志与 SQLite 已落盘
for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null || true; done
wait 2>/dev/null || true
PIDS=()

echo "[4/4] leak search"
LEAK_OUT_DIR="$AUTH_OUT_DIR" LEAK_DB_PATH="$DB_PATH" LEAK_LOG_DIR="$AUTH_OUT_DIR" \
  uv run python scripts/auth_leak_search.py || STATUS=1

if [[ $STATUS -ne 0 ]]; then
  echo "真实 Engine 矩阵失败" >&2
fi
exit $STATUS
