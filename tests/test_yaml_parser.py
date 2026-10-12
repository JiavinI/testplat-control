"""YAML 解析器测试"""

from pathlib import Path

import pytest
import yaml

from testplat_control.parsers import YamlParser

# 获取测试 fixtures 目录
FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestYamlParserApiYaml:
    """API YAML 解析测试"""

    def test_parse_api_yaml_simple(self):
        """测试: 解析简单的 API YAML 文件"""
        api_file = FIXTURES_DIR / "api_simple.yaml"
        result = YamlParser.parse_api_yaml(api_file)

        assert result["id"] == "api.test.simple"
        assert result["name"] == "简单测试"
        assert result["desc"] == "测试 API 解析"
        assert result["method"] == "GET"
        assert result["url"] == "/status/200"
        assert result["host"] == "test_server"

    def test_parse_api_yaml_extracts_inputs(self):
        """测试: 提取 inputs 字段"""
        api_file = FIXTURES_DIR / "api_simple.yaml"
        result = YamlParser.parse_api_yaml(api_file)

        assert "inputs" in result
        assert isinstance(result["inputs"], dict)
        assert "username" in result["inputs"]
        assert "password" in result["inputs"]

    def test_parse_api_yaml_extracts_success(self):
        """测试: 提取 success 条件"""
        api_file = FIXTURES_DIR / "api_simple.yaml"
        result = YamlParser.parse_api_yaml(api_file)

        assert "success" in result
        assert result["success"]["status_code"] == 200

    def test_parse_api_yaml_empty_inputs(self):
        """测试: 处理空 inputs"""
        # 仓库 fixture 是回归契约的一部分；缺失必须失败，不能把资源遗漏伪装成绿灯。
        api_file = FIXTURES_DIR / "assets" / "api" / "common" / "get_status.yaml"
        assert api_file.is_file(), f"required test fixture not found: {api_file}"
        result = YamlParser.parse_api_yaml(api_file)
        assert "inputs" in result
        assert isinstance(result["inputs"], dict)


class TestYamlParserAutoDetect:
    """自动检测资产类型测试"""

    def test_parse_yaml_detects_api_type(self):
        """测试: 自动检测 API 类型"""
        api_file = FIXTURES_DIR / "api_simple.yaml"
        result = YamlParser.parse_yaml(api_file)

        assert "type" in result
        assert result["type"] == "api"

    def test_parse_yaml_detects_case_type(self):
        """测试: 自动检测 Case 类型"""
        case_file = FIXTURES_DIR / "case_login.yaml"
        result = YamlParser.parse_yaml(case_file)

        assert "type" in result
        assert result["type"] == "case"

    def test_parse_yaml_includes_all_data(self):
        """测试: parse_yaml 包含所有原始数据"""
        api_file = FIXTURES_DIR / "api_simple.yaml"
        result = YamlParser.parse_yaml(api_file)

        # 验证包含所有原始字段
        assert "id" in result
        assert "name" in result
        assert "method" in result


class TestYamlParserErrorHandling:
    """异常处理测试"""

    def test_parse_api_yaml_file_not_found(self):
        """测试: 处理不存在的文件"""
        nonexistent = FIXTURES_DIR / "nonexistent.yaml"
        with pytest.raises(FileNotFoundError):
            YamlParser.parse_api_yaml(nonexistent)

    def test_parse_yaml_file_not_found(self):
        """测试: 处理不存在的文件"""
        nonexistent = FIXTURES_DIR / "nonexistent.yaml"
        with pytest.raises(FileNotFoundError):
            YamlParser.parse_yaml(nonexistent)

    def test_parse_api_yaml_invalid_yaml(self):
        """测试: 处理无效的 YAML"""
        invalid_file = FIXTURES_DIR / "invalid.yaml"
        with pytest.raises(yaml.YAMLError):
            YamlParser.parse_api_yaml(invalid_file)

    def test_parse_yaml_invalid_yaml(self):
        """测试: 处理无效的 YAML"""
        invalid_file = FIXTURES_DIR / "invalid.yaml"
        with pytest.raises(yaml.YAMLError):
            YamlParser.parse_yaml(invalid_file)


class TestYamlParserRealFiles:
    """使用仓库内 fixtures/assets 中的真实 YAML 文件测试"""

    def test_parse_real_api_get_status(self):
        """测试: 解析真实的 get_status.yaml"""
        api_file = FIXTURES_DIR / "assets" / "api" / "common" / "get_status.yaml"
        assert api_file.is_file(), f"required test fixture not found: {api_file}"

        result = YamlParser.parse_api_yaml(api_file)

        assert result["id"] == "api.common.get_status"
        assert result["name"] == "获取状态码"
        assert result["method"] == "GET"
        assert "inputs" in result

    def test_parse_real_api_post_json(self):
        """测试: 解析真实的 post_json.yaml"""
        api_file = FIXTURES_DIR / "assets" / "api" / "common" / "post_json.yaml"
        assert api_file.is_file(), f"required test fixture not found: {api_file}"

        result = YamlParser.parse_api_yaml(api_file)

        assert result["id"] == "api.common.post_json"
        assert result["name"] == "POST JSON 数据"
        assert result["method"] == "POST"
        assert "inputs" in result
        assert "username" in result["inputs"]
        assert "email" in result["inputs"]

    def test_auto_detect_real_api_file(self):
        """测试: 自动检测真实 API 文件类型"""
        api_file = FIXTURES_DIR / "assets" / "api" / "common" / "get_status.yaml"
        assert api_file.is_file(), f"required test fixture not found: {api_file}"

        result = YamlParser.parse_yaml(api_file)

        assert result["type"] == "api"
