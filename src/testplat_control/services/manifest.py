"""解析资产仓库清单 ``testplat.yaml`` 与路径安全校验。

设计稿 §3：项目键规则、相对路径、拒绝绝对路径 / ``..`` / 符号链接逃逸；
可选环境 = ``config/envs/*.yaml`` 文件名（忽略 ``_`` 开头）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# 仓库键与项目键共用：小写字母、数字、下划线、短横线，1–64 字符。
KEY_PATTERN = re.compile(r"^[a-z0-9_-]{1,64}$")


class ManifestError(Exception):
    """清单非法；对外只映射为 ``invalid_manifest``，消息不含路径原文中的敏感段。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ManifestProject:
    """清单中的单个项目。"""

    key: str
    name: str
    assets: str  # 相对仓库根
    config: str
    default_env: str | None


@dataclass(frozen=True)
class Manifest:
    """已校验的仓库清单。"""

    schema_version: str
    projects: dict[str, ManifestProject]


def is_valid_key(value: str) -> bool:
    """仓库键 / 项目键是否符合 ``[a-z0-9_-]{1,64}``。"""
    return bool(KEY_PATTERN.fullmatch(value))


def assert_relative_safe(path_str: str) -> None:
    """拒绝绝对路径与含 ``..`` 的相对路径（纯字符串检查，不访问磁盘）。"""
    if not path_str or not str(path_str).strip():
        raise ManifestError("empty_path")
    text = str(path_str).strip().replace("\\", "/")
    if text.startswith("/") or text.startswith("~"):
        raise ManifestError("absolute_path")
    # Windows 盘符
    if len(text) >= 2 and text[1] == ":":
        raise ManifestError("absolute_path")
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ManifestError("path_escape")


def safe_resolve(root: Path, relative: str) -> Path:
    """``resolve()`` 后校验仍在 ``root`` 前缀内；拒绝指向 root 外的符号链接。

    Args:
        root: 快照根目录（已 resolve）。
        relative: 清单中的相对路径。

    Returns:
        解析后的绝对路径。

    Raises:
        ManifestError: 路径逃逸或落在 root 外。
    """
    assert_relative_safe(relative)
    root_resolved = root.resolve()
    candidate = (root_resolved / relative).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ManifestError("path_escape") from exc
    return candidate


def list_env_names(config_dir: Path) -> list[str]:
    """列出 ``config/envs/*.yaml`` 环境名，忽略 ``_`` 开头的共享文件。"""
    envs_dir = config_dir / "envs"
    if not envs_dir.is_dir():
        return []
    names: list[str] = []
    for path in sorted(envs_dir.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".yaml", ".yml"}:
            continue
        stem = path.stem
        if stem.startswith("_"):
            continue
        names.append(stem)
    return names


def parse_manifest_dict(data: Any) -> Manifest:
    """从已加载的 YAML 对象解析清单。"""
    if not isinstance(data, dict):
        raise ManifestError("root_not_object")
    version = data.get("schema_version")
    if version is None or str(version).strip() == "":
        raise ManifestError("missing_schema_version")
    projects_raw = data.get("projects")
    if not isinstance(projects_raw, dict) or not projects_raw:
        raise ManifestError("missing_projects")

    projects: dict[str, ManifestProject] = {}
    for key, spec in projects_raw.items():
        if not isinstance(key, str) or not is_valid_key(key):
            raise ManifestError("invalid_project_key")
        if not isinstance(spec, dict):
            raise ManifestError("invalid_project_spec")
        name = spec.get("name")
        assets = spec.get("assets")
        config = spec.get("config")
        if not isinstance(name, str) or not name.strip():
            raise ManifestError("invalid_project_name")
        if not isinstance(assets, str) or not isinstance(config, str):
            raise ManifestError("invalid_project_paths")
        assert_relative_safe(assets)
        assert_relative_safe(config)
        default_env = spec.get("default_env")
        if default_env is not None and (
            not isinstance(default_env, str) or not default_env.strip()
        ):
            raise ManifestError("invalid_default_env")
        projects[key] = ManifestProject(
            key=key,
            name=name.strip(),
            assets=assets.strip().replace("\\", "/"),
            config=config.strip().replace("\\", "/"),
            default_env=None if default_env is None else default_env.strip(),
        )
    return Manifest(schema_version=str(version), projects=projects)


def load_manifest(snapshot_root: Path) -> Manifest:
    """从快照根读取并校验 ``testplat.yaml``，并校验各项目路径落在快照内。"""
    manifest_path = snapshot_root / "testplat.yaml"
    if not manifest_path.is_file():
        raise ManifestError("missing_manifest")
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ManifestError("invalid_yaml") from exc
    except OSError as exc:
        raise ManifestError("unreadable_manifest") from exc

    manifest = parse_manifest_dict(raw)
    root = snapshot_root.resolve()
    for project in manifest.projects.values():
        assets_path = safe_resolve(root, project.assets)
        config_path = safe_resolve(root, project.config)
        if not assets_path.exists():
            raise ManifestError("assets_missing")
        if not config_path.exists():
            raise ManifestError("config_missing")
        # 若为符号链接，resolve 已跟随；再确认仍在 root 内（safe_resolve 已做）
        _ = assets_path, config_path
    return manifest


def envs_for_project(snapshot_root: Path, project: ManifestProject) -> list[str]:
    """读取项目配置目录下的环境列表。"""
    config_dir = safe_resolve(snapshot_root.resolve(), project.config)
    return list_env_names(config_dir)
