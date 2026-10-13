#!/usr/bin/env bash
# 启动本地 target + 真实 Engine Control + 前端，跑真实 Engine 矩阵；不访问公网。
#
# Phase 3.3b 扩展（在 3.3a 四段之上）：
#   0. 以本地 path 安装假登录插件（不发布）
#   1. 3.3a 鉴权 HTTP 矩阵（§6 1–10）
#   2. 3.3b 登录 HTTP 矩阵（§6 11–21 + 旧 profile + E1）
#   3. 3.3a 身份展示截图 → phase3_3-real-engine/
#   4. 3.3b 登录身份展示截图 → phase3_3b-real-engine/（真实 Engine）
#   5. Phase 3 回归（无 auth）
#   6. 泄密全文搜索（含登录秘密）
#
# 不变量：配置/资产/SQLite 均在临时目录；假秘密只进进程环境；旧截图目录不被改写。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TARGET_PORT="${TARGET_PORT:-18099}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
AUTH_OUT_DIR="${AUTH_OUT_DIR:-$ROOT/frontend/screenshots/phase3_3-real-engine}"
LOGIN_OUT_DIR="${LOGIN_OUT_DIR:-$ROOT/frontend/screenshots/phase3_3b-real-engine}"
mkdir -p "$AUTH_OUT_DIR" "$LOGIN_OUT_DIR"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/phase3_3b-matrix.XXXXXX")"
OUT_DIR="${E2E_OUT_DIR:-$WORK/phase3-regression}"
mkdir -p "$OUT_DIR"

# 0) 假插件：本地 path 安装到当前 uv 环境（不发布、不写入 pyproject）
echo "[0/6] install fake login plugin (local path)"
uv pip install --python "$(uv run python -c 'import sys; print(sys.executable)')" \
  "$ROOT/tests/plugins/testplat_login_fake" >/dev/null
uv run python -c 'from importlib.metadata import entry_points
eps=entry_points(group="testplat_engine.login_strategies")
names=sorted(e.name for e in eps)
assert "fake_login" in names, names
print("fake_login entry point ok:", names)'

write_env() {
  mkdir -p "$1/envs"
  cat >"$1/envs/test.yaml" <<YAML
# 由 run_real_engine_matrix.sh 生成（临时目录）；local 指向本机 target
api_hosts:
  test_server: http://127.0.0.1:9
  local: http://127.0.0.1:$TARGET_PORT
  dead: http://127.0.0.1:1
timeout:
  default: 30
YAML
}

E2E_CONFIG_ROOT="$WORK/cfg-phase3"
mkdir -p "$E2E_CONFIG_ROOT"
cp -R "$ROOT/tests/fixtures/config/." "$E2E_CONFIG_ROOT/"
write_env "$E2E_CONFIG_ROOT"
export E2E_CONFIG_ROOT

# 3.3a 鉴权资产
AUTH_ASSETS_ROOT="$WORK/assets"
mkdir -p "$AUTH_ASSETS_ROOT"
cp -R "$ROOT/tests/fixtures/assets/." "$AUTH_ASSETS_ROOT/"
cp -R "$ROOT/tests/fixtures/auth_matrix/assets/." "$AUTH_ASSETS_ROOT/"

# 3.3b 登录资产（与 demo/auth_matrix 合并，便于同项目复用）
LOGIN_ASSETS_ROOT="$WORK/login-assets"
mkdir -p "$LOGIN_ASSETS_ROOT"
cp -R "$ROOT/tests/fixtures/assets/." "$LOGIN_ASSETS_ROOT/"
cp -R "$ROOT/tests/fixtures/login_matrix/assets/." "$LOGIN_ASSETS_ROOT/"

make_root() {
  local dir="$WORK/cfg-$1"
  write_env "$dir"
  if [[ -n "$2" ]]; then
    mkdir -p "$dir/auth"
    cp "$ROOT/tests/fixtures/auth_matrix/auth/$2" "$dir/auth/test.yaml"
  fi
  echo "$dir"
}

make_login_root() {
  local dir="$WORK/cfg-$1"
  write_env "$dir"
  mkdir -p "$dir/auth"
  cp "$ROOT/tests/fixtures/login_matrix/auth/$2" "$dir/auth/test.yaml"
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

export MATRIX_ROOT_LOGIN="$(make_login_root login main.yaml)"
export MATRIX_ROOT_LEGACY="$(make_login_root legacy legacy-profiles.yaml)"
export MATRIX_ROOT_STATIC="$(make_login_root static static-only.yaml)"
export MATRIX_ROOT_NO_PLUGIN="$(make_login_root no-plugin no-plugin-whitelist.yaml)"
export MATRIX_ROOT_UNKNOWN="$(make_login_root unknown unknown-strategy.yaml)"
export MATRIX_LOGIN_ASSETS_ROOT="$LOGIN_ASSETS_ROOT"
export MATRIX_LOGIN_OUT_DIR="$LOGIN_OUT_DIR"

DB_PATH="$WORK/control.db"
cat >"$WORK/log.json" <<'JSON'
{
  "version": 1,
  "disable_existing_loggers": false,
  "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
  "handlers": {"stderr": {"class": "logging.StreamHandler", "formatter": "plain", "stream": "ext://sys.stderr"}},
  "root": {"level": "DEBUG", "handlers": ["stderr"]},
  "loggers": {
    "httpx": {"level": "WARNING", "handlers": ["stderr"], "propagate": false},
    "httpcore": {"level": "WARNING", "handlers": ["stderr"], "propagate": false},
    "h11": {"level": "WARNING", "handlers": ["stderr"], "propagate": false}
  }
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

uv run python scripts/local_target_server.py --port "$TARGET_PORT" >"$LOGIN_OUT_DIR/target.log" 2>&1 &
PIDS+=($!)

# 假秘密：3.3a + 3.3b 登录；不 echo、不写入文件
env \
  -u TESTPLAT_MISSING_TOKEN \
  MATRIX_SQLITE_PATH="$DB_PATH" \
  TESTPLAT_ADMIN_TOKEN="tp-fake-secret-9f31c2a7" \
  TESTPLAT_PARTNER_KEY="tp-fake-partner-4c8e11d0" \
  TESTPLAT_EMPTY_TOKEN="" \
  TESTPLAT_SHORT_TOKEN="abc1234" \
  TESTPLAT_CRLF_TOKEN=$'tp-fake-secret-9f31c2a7\r\nX-Injected: yes' \
  TESTPLAT_LF_TOKEN=$'tp-fake-secret-9f31c2a7\nX-Injected: yes' \
  TESTPLAT_BUYER_PASSWORD="tp-fake-buyer-pass-71c2" \
  TESTPLAT_SELLER_PASSWORD="tp-fake-seller-pass-93ab" \
  TESTPLAT_REDIS_MAIN_PASSWORD="tp-fake-redis-pass-5e0d" \
  TESTPLAT_PLUGIN_KEY="tp-fake-plugin-key-11aa" \
  AWS_SECRET_ACCESS_KEY="tp-fake-aws-7d2e9b10" \
  uv run uvicorn testplat_control.harness_real_matrix:app --host 127.0.0.1 --port "$BACKEND_PORT" \
  --log-config "$WORK/log.json" >"$LOGIN_OUT_DIR/backend.log" 2>&1 &
PIDS+=($!)
(
  cd frontend
  VITE_DEV_PROXY_TARGET="http://127.0.0.1:$BACKEND_PORT"   pnpm exec vite --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort
) >"$LOGIN_OUT_DIR/frontend.log" 2>&1 &
PIDS+=($!)

for i in $(seq 1 90); do
  if curl -sf "http://127.0.0.1:$BACKEND_PORT/health" >/dev/null \
    && curl -sf "http://127.0.0.1:$FRONTEND_PORT" >/dev/null \
    && curl -sf "http://127.0.0.1:$TARGET_PORT/status/200" >/dev/null; then
    break
  fi
  sleep 0.5
  if [[ $i -eq 90 ]]; then
    echo "服务启动超时" >&2
    tail -n 60 "$LOGIN_OUT_DIR"/*.log >&2 || true
    exit 1
  fi
done
if grep -q "address already in use" "$LOGIN_OUT_DIR/backend.log" 2>/dev/null; then
  echo "后端端口 $BACKEND_PORT 被占用，拒绝继续（避免打到旧进程）" >&2
  exit 1
fi

STATUS=0
echo "services ready; [1/6] auth HTTP matrix (3.3a)"
# 3.3a 报告仍写 AUTH_OUT_DIR；后端日志在 LOGIN_OUT_DIR — 复制一份 backend/target 链到 AUTH 供 3.3a 泄密段兼容
cp "$LOGIN_OUT_DIR/backend.log" "$AUTH_OUT_DIR/backend.log" 2>/dev/null || true
cp "$LOGIN_OUT_DIR/target.log" "$AUTH_OUT_DIR/target.log" 2>/dev/null || true
uv run python scripts/auth_real_engine_matrix.py || STATUS=1

echo "[2/6] login HTTP matrix (3.3b §6.11-21)"
uv run python scripts/login_real_engine_matrix.py || STATUS=1

echo "[3/6] auth browser screenshots (3.3a real Engine)"
(
  cd frontend
  E2E_BASE_URL="http://127.0.0.1:$FRONTEND_PORT" \
  E2E_OUT_DIR="$AUTH_OUT_DIR" \
  E2E_AUTH_ASSETS_ROOT="$AUTH_ASSETS_ROOT" \
  E2E_AUTH_CONFIG_ROOT="$MATRIX_ROOT_AUTH" \
  pnpm exec node scripts/e2e-auth-real-engine.mjs
) || STATUS=1

echo "[4/6] login browser screenshots (3.3b real Engine)"
(
  cd frontend
  E2E_BASE_URL="http://127.0.0.1:$FRONTEND_PORT" \
  E2E_OUT_DIR="$LOGIN_OUT_DIR" \
  E2E_LOGIN_ASSETS_ROOT="$LOGIN_ASSETS_ROOT" \
  E2E_LOGIN_CONFIG_ROOT="$MATRIX_ROOT_LOGIN" \
  pnpm exec node scripts/e2e-login-real-engine.mjs
) || STATUS=1

echo "[5/6] Phase 3 regression (no auth config)"
(
  cd frontend
  E2E_BASE_URL="http://127.0.0.1:$FRONTEND_PORT" \
  E2E_OUT_DIR="$OUT_DIR" \
  E2E_CONFIG_ROOT="$E2E_CONFIG_ROOT" \
  pnpm exec node scripts/e2e-real-engine-matrix.mjs
) || STATUS=1
cp "$OUT_DIR/real-engine-matrix-report.json" "$LOGIN_OUT_DIR/phase3-regression-report.json" 2>/dev/null || true
cp "$OUT_DIR/real-engine-matrix-report.json" "$AUTH_OUT_DIR/phase3-regression-report.json" 2>/dev/null || true

for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null || true; done
wait 2>/dev/null || true
PIDS=()

# 合并日志到 LOGIN_OUT_DIR 供统一泄密搜索（后端日志在进程存活期已写入）
echo "[6/6] leak search"
# 将 3.3a 报告也拷到 LOGIN_OUT_DIR 一并搜索
cp "$AUTH_OUT_DIR"/auth-matrix-report.json "$LOGIN_OUT_DIR/" 2>/dev/null || true
cp "$AUTH_OUT_DIR"/dom-secret-search.json "$LOGIN_OUT_DIR/dom-secret-search-auth.json" 2>/dev/null || true
LEAK_OUT_DIR="$LOGIN_OUT_DIR" LEAK_DB_PATH="$DB_PATH" LEAK_LOG_DIR="$LOGIN_OUT_DIR" \
  uv run python scripts/auth_leak_search.py || STATUS=1

if [[ $STATUS -ne 0 ]]; then
  echo "真实 Engine 矩阵失败" >&2
fi
exit $STATUS
