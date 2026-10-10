"""资产扫描和管理服务"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from testplat_control.parsers import YamlParser


@dataclass
class AssetNode:
    """资产树节点"""

    id: str  # 唯一标识 (如 'api' 或 'api.common.health_check')
    name: str  # 显示名称 (文件夹名 或 文件名去扩展名)
    type: str  # "directory" 或 "file"
    path: str  # 磁盘路径 (相对于 assets_root)
    children: list["AssetNode"] | None = None  # 子节点 (仅目录)
    metadata: dict[str, Any] | None = None  # 文件元数据 (仅文件)


class AssetService:
    """资产扫描和管理服务"""

    def __init__(self, assets_root: Path):
        """
        初始化资产服务。

        Args:
            assets_root: 资产根目录路径
        """
        self.assets_root = Path(assets_root)
        self._asset_cache: dict[str, AssetNode] = {}

    def scan_assets(self) -> AssetNode:
        """
        扫描所有资产，返回树形结构根节点。

        Returns:
            AssetNode: 根节点 (name='assets')

        示例输出:
            {
                "id": "assets",
                "name": "assets",
                "type": "directory",
                "path": ".",
                "children": [
                    {
                        "id": "api",
                        "name": "api",
                        "type": "directory",
                        "path": "api",
                        "children": [
                            {
                                "id": "api.common",
                                "name": "common",
                                "type": "directory",
                                "path": "api/common",
                                "children": [
                                    {
                                        "id": "api.common.health_check",
                                        "name": "health_check.yaml",
                                        "type": "file",
                                        "path": "api/common/health_check.yaml",
                                        "metadata": {...}
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        """
        self._asset_cache.clear()
        root = self._build_tree(self.assets_root, prefix="")
        root.id = "assets"
        root.name = "assets"
        return root

    def get_asset(self, asset_id: str) -> AssetNode | None:
        """
        获取某个资产的详细信息。

        Args:
            asset_id: 资产 ID (如 'api.common.health_check')

        Returns:
            AssetNode: 资产节点，或 None 如果不存在
        """
        # 如果缓存为空，先扫描一次
        if not self._asset_cache:
            self.scan_assets()

        return self._asset_cache.get(asset_id)

    def _build_tree(self, dir_path: Path, prefix: str = "") -> AssetNode:
        """
        递归构建树形结构。

        Args:
            dir_path: 目录路径
            prefix: ID 前缀 (用于生成 asset_id)

        Returns:
            AssetNode: 目录节点，包含所有子节点
        """
        # 相对于 assets_root 的路径
        rel_path = dir_path.relative_to(self.assets_root)
        rel_path_str = str(rel_path).replace("\\", "/")
        if rel_path_str == ".":
            rel_path_str = ""

        # 生成目录的 ID
        if prefix:
            dir_id = prefix
        else:
            dir_id = ""

        children = []

        # 遍历目录中的所有项
        try:
            items = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        except (PermissionError, OSError):
            items = []

        for item in items:
            # 跳过隐藏文件 (以 . 开头)
            if item.name.startswith("."):
                continue

            if item.is_dir():
                # 递归处理子目录
                if prefix:
                    child_prefix = f"{prefix}.{item.name}"
                else:
                    child_prefix = item.name

                child_rel_path = item.relative_to(self.assets_root)
                child_rel_path_str = str(child_rel_path).replace("\\", "/")

                child_node = self._build_tree(item, prefix=child_prefix)
                children.append(child_node)
                # 缓存目录节点
                self._asset_cache[child_prefix] = child_node

            elif item.is_file():
                # 处理文件
                file_stem = item.stem  # 不包含扩展名的文件名
                file_name = item.name

                if prefix:
                    file_id = f"{prefix}.{file_stem}"
                else:
                    file_id = file_stem

                child_rel_path = item.relative_to(self.assets_root)
                child_rel_path_str = str(child_rel_path).replace("\\", "/")

                metadata = self._extract_file_metadata(item)
                # 如果没有 api_id，使用生成的 file_id
                if "api_id" not in metadata:
                    metadata["api_id"] = file_id

                file_node = AssetNode(
                    id=file_id,
                    name=file_name,
                    type="file",
                    path=child_rel_path_str,
                    metadata=metadata,
                )
                children.append(file_node)
                # 缓存文件节点
                self._asset_cache[file_id] = file_node

        # 构建目录节点
        dir_rel_path_str = rel_path_str if rel_path_str else "."

        dir_node = AssetNode(
            id=dir_id or "assets",
            name=dir_path.name or "assets",
            type="directory",
            path=dir_rel_path_str,
            children=children,
        )

        return dir_node

    def _extract_file_metadata(self, file_path: Path) -> dict[str, Any]:
        """
        提取单个文件的元数据。

        Args:
            file_path: 文件路径

        Returns:
            dict: 文件元数据
        """
        metadata = {}

        # 仅处理 YAML 文件
        if file_path.suffix in [".yaml", ".yml"]:
            try:
                parsed = YamlParser.parse_yaml(file_path)
                metadata = parsed
            except Exception as e:
                # 记录解析错误但不中止
                metadata["parse_error"] = str(e)

        return metadata
