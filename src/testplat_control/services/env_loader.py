"""从项目 config_root 加载并校验环境配置。

Control 拥有配置目录布局；Engine 只接收已解析的 environment 映射，
不再从 assets_root 猜测 config 路径。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from testplat_engine import InvalidEnvironmentError
from testplat_engine.interface import JsonValue

logger = logging.getLogger(__name__)


def load_project_environment(config_root: str | Path, env: str) -> dict[str, JsonValue]:
    """加载并校验指定环境的 YAML 配置。

    查找顺序：

    1. ``{config_root}/envs/{env}.yaml``
    2. ``{config_root}/{env}.yaml``

    Args:
        config_root: 项目配置根目录。
        env: 环境名，如 ``test`` / ``staging``。

    Returns:
        可 JSON 序列化的环境配置对象，交给 ``ApiExecutionRequest.environment``。

    Raises:
        InvalidEnvironmentError: 文件缺失、YAML 非法或根节点不是对象。
            stage=preflight，Control 映射为 422 且不写执行记录。
    """
    if not env or not str(env).strip():
        raise InvalidEnvironmentError(
            public_message="环境名称无效",
            log_reason="project.env 为空",
        )

    root = Path(config_root)
    candidates = [
        root / "envs" / f"{env}.yaml",
        root / f"{env}.yaml",
    ]
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        tried = ", ".join(str(item) for item in candidates)
        raise InvalidEnvironmentError(
            public_message=f"环境配置不存在: {env}",
            log_reason=f"未找到环境文件，已尝试: {tried}",
        )

    try:
        raw = path.read_text(encoding="utf-8")
        loaded: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise InvalidEnvironmentError(
            public_message=f"环境配置 YAML 无效: {env}",
            log_reason=f"{path}: {exc}",
        ) from exc
    except OSError as exc:
        logger.exception("读取环境配置失败: %s", path)
        raise InvalidEnvironmentError(
            public_message=f"无法读取环境配置: {env}",
            log_reason=f"{path}: {type(exc).__name__}: {exc}",
        ) from exc

    if loaded is None:
        raise InvalidEnvironmentError(
            public_message=f"环境配置为空: {env}",
            log_reason=f"{path} 解析结果为 None",
        )
    if not isinstance(loaded, dict):
        raise InvalidEnvironmentError(
            public_message=f"环境配置必须是对象: {env}",
            log_reason=f"{path} 根节点类型为 {type(loaded).__name__}",
        )

    # ApiExecutionRequest 会再次做 JSON 可序列化校验；此处先保证键为 str。
    result: dict[str, JsonValue] = {}
    for key, value in loaded.items():
        if not isinstance(key, str):
            raise InvalidEnvironmentError(
                public_message=f"环境配置键必须是字符串: {env}",
                log_reason=f"{path} 含非字符串键 {key!r}",
            )
        result[key] = value  # type: ignore[assignment]
    return result
