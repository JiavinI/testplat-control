"""显式本地开发入口：确认 Engine 来源后执行命令，不读取预览配置。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import testplat_engine

from testplat_control.engine_bootstrap import EngineBootstrapError, ensure_engine_compatible


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(
            "Usage: python -m testplat_control.local_dev ENGINE_SOURCE COMMAND [ARGS...]"
        )
    source_root = Path(sys.argv[1]).resolve()
    imported = Path(testplat_engine.__file__).resolve()
    if imported != source_root / "src/testplat_engine/__init__.py":
        raise SystemExit("Engine 来源与指定本地源码不一致，已停止")
    try:
        version = ensure_engine_compatible()
    except EngineBootstrapError as exc:
        raise SystemExit(str(exc)) from None
    print(f"本地 Engine {version} 已校验：{source_root}", flush=True)
    command = sys.argv[2:]
    if command == ["check"]:
        return
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
