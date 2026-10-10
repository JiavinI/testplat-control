"""资产服务测试"""

import unittest
from pathlib import Path

from testplat_control.services import AssetNode, AssetService


class TestAssetService(unittest.TestCase):
    """资产服务测试"""

    @classmethod
    def setUpClass(cls):
        """设置测试环境"""
        cls.test_assets_path = Path(__file__).parent.parent.parent / "test_assets"
        cls.asset_service = AssetService(cls.test_assets_path)

    def test_01_scan_root_directory_structure(self):
        """测试: 扫描根目录结构"""
        tree = self.asset_service.scan_assets()

        self.assertEqual(tree.id, "assets")
        self.assertEqual(tree.name, "assets")
        self.assertEqual(tree.type, "directory")
        self.assertIsNotNone(tree.children)
        self.assertGreater(len(tree.children), 0)

    def test_02_scan_api_subdirectory(self):
        """测试: 扫描 api/ 子目录"""
        tree = self.asset_service.scan_assets()

        # 找到 api 节点
        api_node = None
        for child in tree.children:
            if child.name == "api":
                api_node = child
                break

        self.assertIsNotNone(api_node)
        self.assertEqual(api_node.id, "api")
        self.assertEqual(api_node.type, "directory")
        self.assertIsNotNone(api_node.children)

    def test_03_detect_yaml_files(self):
        """测试: 检测 .yaml 文件"""
        tree = self.asset_service.scan_assets()

        # 收集所有文件
        def collect_files(node: AssetNode) -> list[AssetNode]:
            files = []
            if node.type == "file":
                files.append(node)
            if node.children:
                for child in node.children:
                    files.extend(collect_files(child))
            return files

        files = collect_files(tree)
        yaml_files = [f for f in files if f.name.endswith(".yaml")]

        self.assertGreater(len(yaml_files), 0)
        # 验证找到了特定的 YAML 文件
        yaml_names = [f.name for f in yaml_files]
        self.assertIn("get_status.yaml", yaml_names)
        self.assertIn("post_json.yaml", yaml_names)

    def test_04_get_single_asset(self):
        """测试: 获取单个资产"""
        # 先扫描获取树
        tree = self.asset_service.scan_assets()

        # 获取 API 节点
        api_asset = self.asset_service.get_asset("api")
        self.assertIsNotNone(api_asset)
        self.assertEqual(api_asset.type, "directory")
        self.assertEqual(api_asset.name, "api")

        # 获取 api.common 节点
        api_common = self.asset_service.get_asset("api.common")
        self.assertIsNotNone(api_common)
        self.assertEqual(api_common.type, "directory")

    def test_05_get_nonexistent_asset_returns_none(self):
        """测试: 不存在的资产返回 None"""
        tree = self.asset_service.scan_assets()

        nonexistent = self.asset_service.get_asset("nonexistent.asset")
        self.assertIsNone(nonexistent)

    def test_06_tree_structure_correctness(self):
        """测试: 树形结构正确性"""
        tree = self.asset_service.scan_assets()

        # 验证树的深度和结构
        self.assertEqual(tree.type, "directory")
        self.assertIsNotNone(tree.children)

        # 检查是否所有目录节点都有 children 属性
        def validate_structure(node: AssetNode):
            if node.type == "directory":
                self.assertIsNotNone(node.children, f"Directory {node.name} should have children")
            elif node.type == "file":
                self.assertIsNone(node.children, f"File {node.name} should not have children")
                # 文件应该有元数据
                self.assertIsNotNone(node.metadata)

            if node.children:
                for child in node.children:
                    validate_structure(child)

        validate_structure(tree)

    def test_07_asset_id_generation(self):
        """测试: 资产 ID 生成正确"""
        tree = self.asset_service.scan_assets()

        # 验证 api.common.get_status ID
        get_status_asset = self.asset_service.get_asset("api.common.get_status")
        self.assertIsNotNone(get_status_asset)
        self.assertEqual(get_status_asset.name, "get_status.yaml")
        self.assertEqual(get_status_asset.type, "file")

    def test_08_file_path_is_relative(self):
        """测试: 文件路径相对于根目录"""
        tree = self.asset_service.scan_assets()

        # 获取一个文件
        get_status = self.asset_service.get_asset("api.common.get_status")
        self.assertIsNotNone(get_status)
        self.assertEqual(get_status.path, "api/common/get_status.yaml")

    def test_09_metadata_present_for_files(self):
        """测试: 文件有元数据"""
        tree = self.asset_service.scan_assets()

        # 获取一个文件
        get_status = self.asset_service.get_asset("api.common.get_status")
        self.assertIsNotNone(get_status)
        self.assertIsNotNone(get_status.metadata)
        self.assertIsInstance(get_status.metadata, dict)
        self.assertIn("api_id", get_status.metadata)


if __name__ == "__main__":
    unittest.main()
