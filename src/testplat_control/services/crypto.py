"""被测凭据的认证加密与平台密码哈希。

- 平台用户密码只用 Argon2 哈希，不可逆。
- 被测凭据用 Fernet（AES-128-CBC + HMAC）加密，以便登录流程解密。
- ``TESTPLAT_MASTER_KEY`` 缺失或不是合法 Fernet 密钥时明确失败，不生成新密钥。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from testplat_control.config import settings

logger = logging.getLogger(__name__)

_hasher = PasswordHasher()
# 用户不存在时仍走一次校验，避免用耗时差区分「无此用户」。
_DUMMY_HASH = _hasher.hash("dummy-password-not-a-login")

MISSING_KEY = "服务配置错误：TESTPLAT_MASTER_KEY 未配置"
INVALID_KEY = "服务配置错误：TESTPLAT_MASTER_KEY 无效"
DECRYPT_FAILED = "服务配置错误：TESTPLAT_MASTER_KEY 无法解密已保存的凭据"


class MasterKeyError(Exception):
    """主密钥配置错误。``message`` 是可回客户端的固定文案，不含密钥或密文。"""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def hash_password(password: str) -> str:
    """返回 Argon2 编码字符串。调用方不得再保留明文。"""
    return _hasher.hash(password)


def password_matches(stored_hash: str | None, password: str) -> bool:
    """校验密码。无用户时对照哑哈希，返回 False，不抛校验异常。"""
    target = stored_hash if stored_hash else _DUMMY_HASH
    try:
        return _hasher.verify(target, password) and stored_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _fernet() -> Fernet:
    raw = settings.testplat_master_key
    if raw is None or not str(raw).strip():
        raise MasterKeyError(MISSING_KEY)
    try:
        return Fernet(str(raw).strip().encode("ascii"))
    except (ValueError, TypeError):
        # 不记录密钥内容。
        logger.error("TESTPLAT_MASTER_KEY 无法构造 Fernet")
        raise MasterKeyError(INVALID_KEY) from None


def encrypt_credentials(credentials: dict[str, str]) -> str:
    """把凭据字典加密为单行 token。明文不写入返回值以外的地方。"""
    payload = json.dumps(credentials, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    try:
        token = _fernet().encrypt(payload)
    except MasterKeyError:
        raise
    except Exception as exc:
        logger.error("凭据加密失败 exc_type=%s", type(exc).__name__)
        raise MasterKeyError(INVALID_KEY) from None
    return token.decode("ascii")


def decrypt_credentials(token: str) -> dict[str, str]:
    """解密凭据。失败时不把密文或异常原文向外抛。"""
    try:
        raw = _fernet().decrypt(token.encode("ascii"))
        loaded: Any = json.loads(raw.decode("utf-8"))
    except MasterKeyError:
        raise
    except (InvalidToken, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        logger.error("凭据解密失败 exc_type=%s", type(exc).__name__)
        raise MasterKeyError(DECRYPT_FAILED) from None
    if not isinstance(loaded, dict) or any(not isinstance(k, str) for k in loaded):
        logger.error("凭据解密结果不是对象")
        raise MasterKeyError(DECRYPT_FAILED)
    out: dict[str, str] = {}
    for key, value in loaded.items():
        if not isinstance(value, str):
            logger.error("凭据解密结果含非字符串字段")
            raise MasterKeyError(DECRYPT_FAILED)
        out[key] = value
    return out
