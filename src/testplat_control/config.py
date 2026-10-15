"""配置管理。

平台自身配置走环境变量（pydantic-settings）。被测账号密码不在这里，
主密钥 ``TESTPLAT_MASTER_KEY`` 只用于解密库中的凭据密文，缺失时不自动生成。
"""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置。环境变量名与字段名大小写不敏感。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "testplat-control"
    app_version: str = "0.1.0"
    debug: bool = False
    database_url: str = "sqlite:///:memory:"
    testplat_repos_file: str | None = None
    # Fernet 密钥（urlsafe base64）。空字符串视为未配置。
    testplat_master_key: str | None = None
    # 部署在 HTTPS 时设为 true，会话 cookie 才带 Secure。
    testplat_cookie_secure: bool = False

    @field_validator("testplat_repos_file", "testplat_master_key", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


settings = Settings()
