#!/usr/bin/env bash
# 在独立 uv 环境显式安装本地 Engine，不改远程锁定或读取预览 env.sh。
set -euo pipefail
control_root="$(cd "$(dirname "$0")/.." && pwd)"
engine_root="${TESTPLAT_ENGINE_SOURCE:-$control_root/../testplat-engine}"
if [ "$#" -eq 0 ]; then
  echo 'Usage: bash scripts/dev.sh check | pytest -q | uvicorn testplat_control.main:app --host 127.0.0.1 --port 8000' >&2
  exit 2
fi
if [ ! -f "$engine_root/pyproject.toml" ]; then
  echo 'Local Engine source missing; use a sibling testplat-engine checkout or TESTPLAT_ENGINE_SOURCE' >&2
  exit 2
fi
engine_root="$(cd "$engine_root" && pwd)"
cd "$control_root"
exec uv run --isolated --locked --extra dev --with-editable "$engine_root" \
  python -m testplat_control.local_dev "$engine_root" "$@"
