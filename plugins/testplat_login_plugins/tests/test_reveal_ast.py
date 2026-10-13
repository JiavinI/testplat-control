"""AST：SecretStr.reveal() 只允许出现在 _secrets.py。"""

from __future__ import annotations

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "testplat_login_plugins"


def test_reveal_only_in_secrets_module() -> None:
    callers: list[str] = []
    for path in SRC_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "reveal"
            ):
                callers.append(path.relative_to(SRC_ROOT).as_posix())
    assert callers, "未找到 reveal 调用，注入点缺失"
    assert set(callers) == {"_secrets.py"}
