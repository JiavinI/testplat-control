"""服务端仓库登记配置（``TESTPLAT_REPOS_FILE`` → 设计稿 §4.1 YAML）。

未配置时启动正常、仓库列表为空。URL 仅保存在内存配置中，永不写入 API 响应。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from testplat_control.services.manifest import is_valid_key


class ReposConfigError(Exception):
    """服务端仓库配置非法（启动期或热加载时抛出）。"""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class RepoEntry:
    """单个已登记仓库（含敏感 URL，仅服务端使用）。"""

    key: str
    url: str
    branch: str


@dataclass(frozen=True)
class ReposConfig:
    """全部仓库登记。"""

    data_dir: Path
    repos: dict[str, RepoEntry]

    def get(self, key: str) -> RepoEntry | None:
        return self.repos.get(key)


def _require_str(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ReposConfigError(f"缺少或非法字段: {field}")
    return value.strip()


def parse_repos_config(data: Any) -> ReposConfig:
    """解析 §4.1 YAML 对象。"""
    if not isinstance(data, dict):
        raise ReposConfigError("仓库配置根节点必须是对象")
    data_dir_raw = _require_str(data, "data_dir")
    data_dir = Path(data_dir_raw).expanduser()
    if not data_dir.is_absolute():
        raise ReposConfigError("data_dir 必须是绝对路径")

    repos_raw = data.get("repos")
    if repos_raw is None:
        repos_raw = {}
    if not isinstance(repos_raw, dict):
        raise ReposConfigError("repos 必须是对象")

    repos: dict[str, RepoEntry] = {}
    for key, spec in repos_raw.items():
        if not isinstance(key, str) or not is_valid_key(key):
            raise ReposConfigError(f"非法仓库键: {key!r}")
        if not isinstance(spec, dict):
            raise ReposConfigError(f"仓库 {key} 配置必须是对象")
        url = _require_str(spec, "url")
        branch = _require_str(spec, "branch")
        repos[key] = RepoEntry(key=key, url=url, branch=branch)
    return ReposConfig(data_dir=data_dir, repos=repos)


def load_repos_config(path: str | Path | None) -> ReposConfig:
    """从 ``TESTPLAT_REPOS_FILE`` 路径加载；``None`` / 空 → 空配置。"""
    if path is None or str(path).strip() == "":
        # 空配置仍需要一个 data_dir 占位；实际不会写盘。
        return ReposConfig(data_dir=Path("/tmp/testplat-repos-unconfigured"), repos={})
    file_path = Path(str(path).strip()).expanduser()
    if not file_path.is_file():
        raise ReposConfigError(f"仓库配置文件不存在: {file_path}")
    try:
        raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ReposConfigError("仓库配置 YAML 无效") from exc
    except OSError as exc:
        raise ReposConfigError("无法读取仓库配置文件") from exc
    return parse_repos_config(raw)
