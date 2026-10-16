#!/usr/bin/env bash
# 本地发布候选校验：构建 wheel，并在隔离环境使用它；不读取预览启动脚本。
set -euo pipefail
control_root="$(cd "$(dirname "$0")/.." && pwd)"
engine_root="${TESTPLAT_ENGINE_SOURCE:-$control_root/../testplat-engine}"
engine_root="$(cd "$engine_root" && pwd)"
repro_dir="$(mktemp -d "${TMPDIR:-/tmp}/testplat-engine-repro.XXXXXX")"
trap 'rm -rf "$repro_dir"' EXIT
export DATABASE_URL='sqlite:///:memory:'
uv build --project "$engine_root" --wheel --out-dir "$repro_dir"
wheel_files=("$repro_dir"/*.whl)
if [ "${#wheel_files[@]}" -ne 1 ] || [ ! -f "${wheel_files[0]}" ]; then
  echo 'Expected exactly one Engine wheel' >&2
  exit 1
fi
cd "$control_root"
uv run --isolated --locked --extra dev --with "${wheel_files[0]}" python - <<'CHECK'
from dataclasses import fields
from pathlib import Path
import testplat_engine
from testplat_engine import ApiExecutionRequest
from testplat_control.engine_bootstrap import ensure_engine_compatible
assert 'request_override' in {field.name for field in fields(ApiExecutionRequest)}
source = Path(testplat_engine.__file__).resolve()
assert 'site-packages' in source.parts, 'Engine must come from the built wheel'
print(f'Engine wheel {ensure_engine_compatible()} installed; request_override contract available')
CHECK
uv run --isolated --locked --extra dev --with "${wheel_files[0]}" pytest -q \
  tests/test_phase4_1a_fake_target.py tests/test_config_sources.py \
  tests/test_engine_provider.py tests/test_auth_cache_scope_and_compat.py
