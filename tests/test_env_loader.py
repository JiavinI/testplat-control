"""环境配置加载测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from testplat_engine import InvalidEnvironmentError

from testplat_control.services.env_loader import load_project_environment


def test_load_env_from_envs_subdir(tmp_path: Path) -> None:
    """优先读取 config_root/envs/{env}.yaml。"""
    path = tmp_path / "envs" / "test.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("api_hosts:\n  main: http://127.0.0.1\n", encoding="utf-8")

    env = load_project_environment(tmp_path, "test")
    assert env["api_hosts"]["main"] == "http://127.0.0.1"


def test_load_env_fallback_to_root_file(tmp_path: Path) -> None:
    """无 envs 子目录时回退到 config_root/{env}.yaml。"""
    (tmp_path / "staging.yaml").write_text("base_url: http://example\n", encoding="utf-8")
    env = load_project_environment(tmp_path, "staging")
    assert env["base_url"] == "http://example"


def test_load_env_missing_raises_invalid_environment(tmp_path: Path) -> None:
    """缺失文件抛出 preflight InvalidEnvironmentError。"""
    with pytest.raises(InvalidEnvironmentError) as exc_info:
        load_project_environment(tmp_path, "test")
    assert exc_info.value.stage == "preflight"
    assert exc_info.value.kind == "invalid_environment"


def test_load_env_rejects_non_mapping(tmp_path: Path) -> None:
    """根节点不是对象时视为无效环境。"""
    (tmp_path / "test.yaml").write_text("- just a list\n", encoding="utf-8")
    with pytest.raises(InvalidEnvironmentError, match="必须是对象"):
        load_project_environment(tmp_path, "test")
