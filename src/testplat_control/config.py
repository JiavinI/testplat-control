"""配置管理"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置"""

    app_name: str = "testplat-control"
    app_version: str = "0.1.0"
    debug: bool = False
    database_url: str = "sqlite:///:memory:"

    class Config:
        env_file = ".env"


settings = Settings()
