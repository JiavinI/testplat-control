"""YAML 文件解析器。

只解析 API 资产（以及供资产树/类型判别使用的通用解析）。**不解析 Case 语义**：
Case 契约 v0.2 的语法校验与规范化模型归 Engine；旧的 ``parse_case_yaml`` 已删除，
避免 Control 维护第二套 Case 解析器（它还接受已废弃的 ``${steps.0...}`` 语法）。
"""

from pathlib import Path
from typing import Any

import yaml


class YamlParser:
    """YAML 文件解析器"""

    @staticmethod
    def parse_api_yaml(file_path: Path) -> dict[str, Any]:
        """
        解析 API YAML 文件，提取元数据。

        Args:
            file_path: YAML 文件路径

        Returns:
            dict: 包含以下字段
            {
                "id": "api.common.health_check",
                "name": "健康检查",
                "desc": "...",
                "method": "GET",
                "inputs": {
                    "username": "用户名",
                    "password": "密码"
                },
                "success_condition": {...}
            }

        Raises:
            FileNotFoundError: 文件不存在
            yaml.YAMLError: YAML 解析错误
        """
        with open(file_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if data is None:
            data = {}

        # 提取 inputs (参数表单)
        inputs = {}
        if "request" in data and "inputs" in data["request"]:
            inputs = data["request"]["inputs"]

        return {
            "id": data.get("id"),
            "name": data.get("name"),
            "desc": data.get("desc"),
            "method": data.get("method"),
            "url": data.get("url"),
            "host": data.get("host"),
            "inputs": inputs,
            "success": data.get("success"),
        }

    @staticmethod
    def parse_yaml(file_path: Path) -> dict[str, Any]:
        """
        通用 YAML 解析，自动检测类型。

        Args:
            file_path: YAML 文件路径

        Returns:
            dict: 原始 YAML 数据加上 'type' 字段 ('api' 或 'case')

        Raises:
            FileNotFoundError: 文件不存在
            yaml.YAMLError: YAML 解析错误
        """
        with open(file_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if data is None:
            data = {}

        # 根据字段判断类型
        asset_type = "case" if "steps" in data else "api"
        data["type"] = asset_type

        return data
