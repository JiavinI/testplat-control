"""配置管理。"""

from __future__ import annotations

import os


class Settings:
    """应用配置。

    ``TESTPLAT_REPOS_FILE``：服务端仓库登记 YAML（设计稿 §4.1）；未设置时仓库列表为空。
    不引入 pydantic-settings 依赖：从环境变量读取即可。
    """

    def __init__(self) -> None:
        self.app_name: str = os.environ.get("APP_NAME", "testplat-control")
        self.app_version: str = os.environ.get("APP_VERSION", "0.1.0")
        self.debug: bool = os.environ.get("DEBUG", "").lower() in {"1", "true", "yes"}
        self.database_url: str = os.environ.get("DATABASE_URL", "sqlite:///:memory:")
        raw = os.environ.get("TESTPLAT_REPOS_FILE")
        self.testplat_repos_file: str | None = (
            None if raw is None or raw.strip() == "" else raw.strip()
        )


settings = Settings()
