#!/usr/bin/env bash
# 启动本地 target + 矩阵 Redis + 真实 Engine Control + 前端，跑真实 Engine 矩阵；不访问公网。
#
# Phase 3.3b 扩展（在 3.3a 四段之上）：
#   0. 以本地 path 安装假登录插件 + testplat-login-plugins[redis]
#   1. 3.3a 鉴权 HTTP 矩阵（§6 1–10）
#   2. 3.3b 登录 HTTP 矩阵（§6 11–21 + 旧 profile + E1）
#   2b. 3.3c 验证码 Redis 矩阵（§6 22–28）
#   3. 3.3a 身份展示截图 → phase3_3-real-engine/
#   4. 3.3b 登录身份展示截图 → phase3_3b-real-engine/
#   4b. 3.3c vcode 截图 → phase3_3c-real-engine/
#   5. Phase 3 回归（无 auth）
#   6. 泄密全文搜索（含登录秘密 + 动态签发值）
#
# 不变量：配置/资产/SQLite 均在临时目录；假秘密只进进程环境；旧截图目录若被改写则还原。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TARGET_PORT="${TARGET_PORT:-18099}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
AUTH_OUT_DIR="${AUTH_OUT_DIR:-$ROOT/frontend/screenshots/phase3_3-real-engine}"
LOGIN_OUT_DIR="${LOGIN_OUT_DIR:-$ROOT/frontend/screenshots/phase3_3b-real-engine}"
VCODE_OUT_DIR="${VCODE_OUT_DIR:-$ROOT/frontend/screenshots/phase3_3c-real-engine}"
mkdir -p "$AUTH_OUT_DIR" "$LOGIN_OUT_DIR" "$VCODE_OUT_DIR"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/phase3_3c-matrix.XXXXXX")"
OUT_DIR="${E2E_OUT_DIR:-$WORK/phase3-regression}"
mkdir -p "$OUT_DIR"
ISSUED_SECRETS="$WORK/issued-secrets.txt"
: >"$ISSUED_SECRETS"

# 记录旧截图目录的 git 状态，矩阵结束后若被改写则还原
RESTORE_DIRS=(
  frontend/screenshots/phase3_3
  frontend/screenshots/phase3_3b
  frontend/screenshots/phase3_3-real-engine
  frontend/screenshots/phase3_3b-real-engine
)
restore_old_screenshots() {
  local changed=0
  for d in "${RESTORE_DIRS[@]}"; do
    if ! git diff --quiet -- "$d" 2>/dev/null || ! git diff --cached --quiet -- "$d" 2>/dev/null; then
      git checkout -- "$d" 2>/dev/null || true
      echo "restored $d"
      changed=1
    fi
    # 清理未跟踪的新文件（矩阵不应往旧目录加新文件；若有则删未跟踪）
    git clean -fd -- "$d" >/dev/null 2>&1 || true
  done
  if [[ $changed -eq 0 ]]; then
    echo "old screenshot dirs unchanged"
  fi
}

# 0) 假插件 + vcode 插件：本地 path 安装到当前 uv 环境（不发布、不写入 pyproject）
echo "[0/7] install login plugins (local path)"
UV_PY="$(uv run python -c 'import sys; print(sys.executable)')"
uv pip install --python "$UV_PY" \
  "$ROOT/tests/plugins/testplat_login_fake" \
  "$ROOT/plugins/testplat_login_plugins[redis]" >/dev/null
uv run python -c 'from importlib.metadata import entry_points
eps=entry_points(group="testplat_engine.login_strategies")
names=sorted(e.name for e in eps)
assert "fake_login" in names, names
assert "vcode_redis" in names, names
print("login entry points ok:", names)'

# 临时 Redis：只绑 127.0.0.1；假密码；trap 关闭
REDIS_PORT="$(uv run python -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
# 选一个当前未监听的端口作为「Redis 不可达」夹具（连接应立即被拒绝 → transport）
DEAD_REDIS_PORT="$(uv run python -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); p=s.getsockname()[1]; s.close(); print(p)')"
REDIS_PASS="${MATRIX_REDIS_PASSWORD:-tp-fake-redis-pass-5e0d}"
export MATRIX_DEAD_REDIS_PORT="$DEAD_REDIS_PORT"
REDIS_DIR="$WORK/redis"
mkdir -p "$REDIS_DIR"
echo "[0b/7] start matrix redis on 127.0.0.1:$REDIS_PORT"
redis-server \
  --bind 127.0.0.1 \
  --port "$REDIS_PORT" \
  --save "" \
  --appendonly no \
  --requirepass "$REDIS_PASS" \
  --dir "$REDIS_DIR" \
  --daemonize no \
  --logfile "$VCODE_OUT_DIR/redis.log" \
  --protected-mode yes &
REDIS_PID=$!

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

subst_redis_port() {
  # 把夹具中的端口占位符换成临时 Redis / 不可达端口
  local src="$1" dst="$2"
  sed -e "s/__MATRIX_REDIS_PORT__/${REDIS_PORT}/g"       -e "s/__MATRIX_DEAD_REDIS_PORT__/${DEAD_REDIS_PORT}/g"       "$src" >"$dst"
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

# 3.3b/3.3c 登录资产（与 demo/auth_matrix 合并）
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

make_vcode_root() {
  local dir="$WORK/cfg-$1"
  write_env "$dir"
  mkdir -p "$dir/auth"
  subst_redis_port "$ROOT/tests/fixtures/login_matrix/auth/$2" "$dir/auth/test.yaml"
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

export MATRIX_ROOT_VCODE="$(make_vcode_root vcode vcode-main.yaml)"
export MATRIX_ROOT_VCODE_CONN_MISSING="$(make_vcode_root vcode-conn-missing vcode-conn-missing.yaml)"
export MATRIX_ROOT_VCODE_NO_WHITELIST="$(make_vcode_root vcode-no-whitelist vcode-no-whitelist.yaml)"
export MATRIX_VCODE_OUT_DIR="$VCODE_OUT_DIR"
export MATRIX_REDIS_HOST="127.0.0.1"
export MATRIX_REDIS_PORT="$REDIS_PORT"
export MATRIX_REDIS_PASSWORD="$REDIS_PASS"

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

PIDS=("$REDIS_PID")
cleanup() {
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  if [[ -n "${REDIS_PID:-}" ]]; then
    kill "$REDIS_PID" 2>/dev/null || true
    wait "$REDIS_PID" 2>/dev/null || true
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

# 等 Redis 就绪
for i in $(seq 1 50); do
  if redis-cli -h 127.0.0.1 -p "$REDIS_PORT" -a "$REDIS_PASS" --no-auth-warning ping 2>/dev/null | grep -q PONG; then
    break
  fi
  sleep 0.1
  if [[ $i -eq 50 ]]; then
    echo "矩阵 Redis 启动超时" >&2
    exit 1
  fi
done

uv run python scripts/local_target_server.py \
  --port "$TARGET_PORT" \
  --redis-host 127.0.0.1 \
  --redis-port "$REDIS_PORT" \
  --redis-password "$REDIS_PASS" \
  --issued-secrets "$ISSUED_SECRETS" \
  >"$VCODE_OUT_DIR/target.log" 2>&1 &
PIDS+=($!)

# 假秘密：3.3a + 3.3b + 3.3c；不 echo、不写入文件
env \
  -u TESTPLAT_MISSING_TOKEN \
  -u TESTPLAT_MISSING_REDIS_PASSWORD \
  MATRIX_SQLITE_PATH="$DB_PATH" \
  TESTPLAT_ADMIN_TOKEN="tp-fake-secret-9f31c2a7" \
  TESTPLAT_PARTNER_KEY="tp-fake-partner-4c8e11d0" \
  TESTPLAT_EMPTY_TOKEN="" \
  TESTPLAT_SHORT_TOKEN="abc1234" \
  TESTPLAT_CRLF_TOKEN=$'tp-fake-secret-9f31c2a7\r\nX-Injected: yes' \
  TESTPLAT_LF_TOKEN=$'tp-fake-secret-9f31c2a7\nX-Injected: yes' \
  TESTPLAT_BUYER_PASSWORD="tp-fake-buyer-pass-71c2" \
  TESTPLAT_SELLER_PASSWORD="tp-fake-seller-pass-93ab" \
  TESTPLAT_REDIS_MAIN_PASSWORD="$REDIS_PASS" \
  TESTPLAT_DF_ADMIN_PASSWORD="tp-fake-df-admin-pass-9f3a" \
  TESTPLAT_PLUGIN_KEY="tp-fake-plugin-key-11aa" \
  AWS_SECRET_ACCESS_KEY="tp-fake-aws-7d2e9b10" \
  uv run uvicorn testplat_control.harness_real_matrix:app --host 127.0.0.1 --port "$BACKEND_PORT" \
  --log-config "$WORK/log.json" >"$VCODE_OUT_DIR/backend.log" 2>&1 &
PIDS+=($!)
(
  cd frontend
  VITE_DEV_PROXY_TARGET="http://127.0.0.1:$BACKEND_PORT"   pnpm exec vite --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort
) >"$VCODE_OUT_DIR/frontend.log" 2>&1 &
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
    tail -n 60 "$VCODE_OUT_DIR"/*.log >&2 || true
    exit 1
  fi
done
if grep -q "address already in use" "$VCODE_OUT_DIR/backend.log" 2>/dev/null; then
  echo "后端端口 $BACKEND_PORT 被占用，拒绝继续（避免打到旧进程）" >&2
  exit 1
fi

# 兼容 3.3a/3.3b 脚本期望的日志位置
cp "$VCODE_OUT_DIR/backend.log" "$LOGIN_OUT_DIR/backend.log" 2>/dev/null || true
cp "$VCODE_OUT_DIR/target.log" "$LOGIN_OUT_DIR/target.log" 2>/dev/null || true
cp "$VCODE_OUT_DIR/backend.log" "$AUTH_OUT_DIR/backend.log" 2>/dev/null || true
cp "$VCODE_OUT_DIR/target.log" "$AUTH_OUT_DIR/target.log" 2>/dev/null || true

STATUS=0
echo "services ready; [1/7] auth HTTP matrix (3.3a)"
uv run python scripts/auth_real_engine_matrix.py || STATUS=1

echo "[2/7] login HTTP matrix (3.3b §6.11-21)"
uv run python scripts/login_real_engine_matrix.py || STATUS=1

echo "[2b/7] vcode HTTP matrix (3.3c §6.22-28)"
uv run python scripts/login_vcode_real_engine_matrix.py || STATUS=1

echo "[3/7] auth browser screenshots (3.3a real Engine)"
(
  cd frontend
  E2E_BASE_URL="http://127.0.0.1:$FRONTEND_PORT" \
  E2E_OUT_DIR="$AUTH_OUT_DIR" \
  E2E_AUTH_ASSETS_ROOT="$AUTH_ASSETS_ROOT" \
  E2E_AUTH_CONFIG_ROOT="$MATRIX_ROOT_AUTH" \
  pnpm exec node scripts/e2e-auth-real-engine.mjs
) || STATUS=1

echo "[4/7] login browser screenshots (3.3b real Engine)"
(
  cd frontend
  E2E_BASE_URL="http://127.0.0.1:$FRONTEND_PORT" \
  E2E_OUT_DIR="$LOGIN_OUT_DIR" \
  E2E_LOGIN_ASSETS_ROOT="$LOGIN_ASSETS_ROOT" \
  E2E_LOGIN_CONFIG_ROOT="$MATRIX_ROOT_LOGIN" \
  pnpm exec node scripts/e2e-login-real-engine.mjs
) || STATUS=1

echo "[4b/7] vcode browser screenshots (3.3c real Engine)"
(
  cd frontend
  E2E_BASE_URL="http://127.0.0.1:$FRONTEND_PORT" \
  E2E_OUT_DIR="$VCODE_OUT_DIR" \
  E2E_LOGIN_ASSETS_ROOT="$LOGIN_ASSETS_ROOT" \
  E2E_LOGIN_CONFIG_ROOT="$MATRIX_ROOT_VCODE" \
  E2E_ISSUED_SECRETS_PATH="$ISSUED_SECRETS" \
  pnpm exec node scripts/e2e-login-vcode-real-engine.mjs
) || STATUS=1

echo "[5/7] Phase 3 regression (no auth config)"
(
  cd frontend
  E2E_BASE_URL="http://127.0.0.1:$FRONTEND_PORT" \
  E2E_OUT_DIR="$OUT_DIR" \
  E2E_CONFIG_ROOT="$E2E_CONFIG_ROOT" \
  pnpm exec node scripts/e2e-real-engine-matrix.mjs
) || STATUS=1
cp "$OUT_DIR/real-engine-matrix-report.json" "$LOGIN_OUT_DIR/phase3-regression-report.json" 2>/dev/null || true
cp "$OUT_DIR/real-engine-matrix-report.json" "$AUTH_OUT_DIR/phase3-regression-report.json" 2>/dev/null || true
cp "$OUT_DIR/real-engine-matrix-report.json" "$VCODE_OUT_DIR/phase3-regression-report.json" 2>/dev/null || true

for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null || true; done
wait 2>/dev/null || true
PIDS=()
REDIS_PID=""

# 泄密搜索须在 trap 清理 WORK 之前（issued-secrets 与 SQLite 仍在）
echo "[6/7] leak search"
# 保留 SQLite 副本供泄密命中归类排查（不含到 git；目录可被 clean）
cp "$DB_PATH" "$VCODE_OUT_DIR/control.db.leakdbg" 2>/dev/null || true

cp "$AUTH_OUT_DIR"/auth-matrix-report.json "$LOGIN_OUT_DIR/" 2>/dev/null || true
cp "$AUTH_OUT_DIR"/dom-secret-search.json "$LOGIN_OUT_DIR/dom-secret-search-auth.json" 2>/dev/null || true
# 把最新后端日志拷到搜索目录（进程已停，文件已完整）
cp "$VCODE_OUT_DIR/backend.log" "$LOGIN_OUT_DIR/backend.log" 2>/dev/null || true
cp "$VCODE_OUT_DIR/target.log" "$LOGIN_OUT_DIR/target.log" 2>/dev/null || true
cp "$VCODE_OUT_DIR/backend.log" "$VCODE_OUT_DIR/backend.log" 2>/dev/null || true
LEAK_OUT_DIR="$VCODE_OUT_DIR" \
LEAK_EXTRA_OUT_DIR="$LOGIN_OUT_DIR" \
LEAK_DB_PATH="$DB_PATH" \
LEAK_LOG_DIR="$VCODE_OUT_DIR" \
LEAK_EXTRA_LOG_DIR="$LOGIN_OUT_DIR" \
LEAK_ISSUED_SECRETS_PATH="$ISSUED_SECRETS" \
  uv run python scripts/auth_leak_search.py || STATUS=1

echo "[7/7] restore old screenshot dirs if rewritten"
restore_old_screenshots

if [[ $STATUS -ne 0 ]]; then
  echo "真实 Engine 矩阵失败" >&2
fi
exit $STATUS
