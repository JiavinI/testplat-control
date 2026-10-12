"""Case 资产定位：只回答“这个 Case 对应的文件在哪、多大、何时改过”。

所有权说明
----------
- **本模块不读取、不解析 Case YAML 内容。** Case 的 schema、id 一致性、步骤与引用
  校验的权威是 Engine（运行时在 preflight 里完成）；Control 若在这里理解 YAML 语义，
  就等于维护第二套 Case 解析器。
- 路径规则取自 Case 契约 v0.2 §2：
  ``case.demo.login`` ↔ ``{assets_root}/scenarios/demo/login.case.yaml``，
  只认 ``.case.yaml``。这里**反向**使用该规则：遍历 ``scenarios`` 下真实存在的文件，
  由文件路径推导 id，再与请求 id 做精确字符串比较——请求 id 永远不会被拼成路径，
  因此不存在 ``..`` / 分隔符 / 符号链接逃逸问题。
- 文件内 ``id`` 是否与路径一致由 Engine 在运行时校验，这里不检查。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SCENARIOS_DIR = "scenarios"
CASE_SUFFIX = ".case.yaml"
CASE_ID_PREFIX = "case."


@dataclass(frozen=True)
class CaseFileInfo:
    """Case 文件的非语义元信息。"""

    case_id: str
    path: str  # 相对 assets_root，POSIX 分隔符
    file_name: str
    size_bytes: int
    modified_at: datetime  # UTC


def case_id_for_relative_path(relative: Path) -> str | None:
    """由相对 ``assets_root`` 的文件路径推导 Case id；不属于 Case 文件时返回 None。

    ``scenarios/demo/login.case.yaml`` → ``case.demo.login``。
    """
    parts = relative.parts
    if len(parts) < 2 or parts[0] != SCENARIOS_DIR:
        return None
    name = parts[-1]
    if not name.endswith(CASE_SUFFIX) or name == CASE_SUFFIX:
        return None
    segments = [*parts[1:-1], name[: -len(CASE_SUFFIX)]]
    return CASE_ID_PREFIX + ".".join(segments)


def find_case_file(assets_root: Path, case_id: str) -> CaseFileInfo | None:
    """在 ``scenarios`` 下查找 id 精确匹配的 ``.case.yaml`` 文件；找不到返回 None。

    - 不跟随目录符号链接；指向 ``scenarios`` 之外的文件符号链接视为不存在。
    - 只看文件系统元信息（stat），不打开文件。
    """
    root = Path(assets_root)
    scenarios = root / SCENARIOS_DIR
    if not scenarios.is_dir():
        return None
    scenarios_real = scenarios.resolve()

    for dirpath, dirnames, filenames in os.walk(scenarios, followlinks=False):
        dirnames.sort()
        for filename in sorted(filenames):
            if not filename.endswith(CASE_SUFFIX):
                continue
            file_path = Path(dirpath) / filename
            relative = file_path.relative_to(root)
            if case_id_for_relative_path(relative) != case_id:
                continue
            resolved = file_path.resolve()
            if not resolved.is_file() or not resolved.is_relative_to(scenarios_real):
                return None
            stat = resolved.stat()
            return CaseFileInfo(
                case_id=case_id,
                path=relative.as_posix(),
                file_name=filename,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            )
    return None
