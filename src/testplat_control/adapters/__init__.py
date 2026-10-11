"""适配器模块：Engine 等外部系统的集成实现。"""

from testplat_control.adapters.fake_engine import FakeEngineAdapter
from testplat_control.adapters.package_engine import PackageEngineAdapter

__all__ = ["FakeEngineAdapter", "PackageEngineAdapter"]
