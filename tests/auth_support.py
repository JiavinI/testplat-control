"""Phase 3.3a 鉴权测试共用：假秘密、配置写入与泄密全文搜索。

假秘密是明显的测试值，也是所有泄密断言的搜索目标（手册 §0.3-3）；绝不使用真实凭证。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

import yaml

FAKE_SECRET = "tp-fake-secret-9f31c2a7"
FAKE_PARTNER = "tp-fake-partner-4c8e11d0"
FAKE_SECRETS = (FAKE_SECRET, FAKE_PARTNER)

# 标准身份表：admin 用 Bearer 拼接，partner 用裸 key；default_identity=admin。
STANDARD_CONFIG: dict = {
    "identities": {
        "admin": {"headers": {"Authorization": "Bearer ${secret:TESTPLAT_ADMIN_TOKEN}"}},
        "partner": {"headers": {"X-Api-Key": "${secret:TESTPLAT_PARTNER_KEY}"}},
    },
    "default_identity": "admin",
}
STANDARD_ENV = {"TESTPLAT_ADMIN_TOKEN": FAKE_SECRET, "TESTPLAT_PARTNER_KEY": FAKE_PARTNER}


def write_auth(config_root: Path, content: dict | str, *, env: str = "test") -> Path:
    """写 ``{config_root}/auth/{env}.yaml``；``content`` 为字符串时原样写（用于非法 YAML）。"""
    path = config_root / "auth" / f"{env}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = content if isinstance(content, str) else yaml.safe_dump(content, allow_unicode=True)
    path.write_text(text, encoding="utf-8")
    return path


def assert_no_secret(texts: Iterable[str | None], secrets: Iterable[str] = FAKE_SECRETS) -> None:
    """在给定文本里全文搜索每个假秘密。"""
    blob = "\n".join(text for text in texts if text)
    for secret in secrets:
        assert secret not in blob, "秘密值泄露"


def log_text(records: Iterable[logging.LogRecord]) -> list[str]:
    """把捕获日志完整展开（含格式化后的消息、args 与异常信息）。"""
    out: list[str] = []
    for record in records:
        out.append(record.getMessage())
        out.append(repr(record.args))
        assert record.exc_info is None, "日志不得携带 exc_info"
        assert record.exc_text is None
    return out
