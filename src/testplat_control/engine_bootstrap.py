"""启动期 Engine 依赖诊断。

缺包、版本不兼容或 runtime 入口无效时 fail-fast，避免用户点击「执行」才遇到模糊 500/503。
"""

from __future__ import annotations

import inspect
import logging
from importlib.metadata import PackageNotFoundError, version

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

logger = logging.getLogger(__name__)

# Phase 3 兼容范围：与 pyproject 中 testplat-engine 约束一致。
# 0.2 在保持单 API DTO 的同时新增 Case DTO / invalid_input；0.1.x 不再受支持。
ENGINE_VERSION_SPEC = SpecifierSet(">=0.2.0,<0.3")
ENGINE_DISTRIBUTION = "testplat-engine"
_REQUIRED_EXPORTS = (
    "ApiExecutionRequest",
    "ApiExecutionOutcome",
    "CaseExecutionRequest",
    "CaseExecutionOutcome",
    "StepOutcome",
    "EngineError",
    "InvalidInputError",
    "EnginePort",
    "__version__",
)


class EngineBootstrapError(RuntimeError):
    """启动期 Engine 依赖不可用；消息可直接展示给运维。"""


def ensure_engine_compatible() -> str:
    """校验 testplat-engine 已安装、版本兼容，并实际调用公开 ``create_engine()``。

    启动期会：
    1. 确认发行版与 Interface 符号齐全；
    2. 解析且调用唯一官方入口 ``create_engine()``；
    3. 验证返回对象具备 async ``execute``。

    任一步失败则 fail-fast，不再把无效 runtime 延迟到首次执行的 503。

    Returns:
        已解析的 Engine 版本字符串。

    Raises:
        EngineBootstrapError: 缺包、版本不兼容、入口缺失或 runtime 无效。
    """
    try:
        import testplat_engine as eng
    except ImportError as exc:
        raise EngineBootstrapError(
            "未安装 testplat-engine。请按 README 安装正式依赖，"
            "或在本地开发中用 uv sources 指向已审查的 Interface/runtime commit。"
            f" 底层原因类型: {type(exc).__name__}"
        ) from exc

    try:
        dist_version = version(ENGINE_DISTRIBUTION)
    except PackageNotFoundError as exc:
        raise EngineBootstrapError(
            f"Python 环境中找不到发行版 {ENGINE_DISTRIBUTION} 的元数据；"
            "请确认已 editable/正式安装该包。"
        ) from exc

    module_version = getattr(eng, "__version__", None)
    check_version = dist_version
    if module_version and str(module_version) != dist_version:
        logger.warning(
            "testplat-engine 元数据版本 %s 与模块 __version__ %s 不一致，以元数据为准",
            dist_version,
            module_version,
        )

    try:
        parsed = Version(check_version)
    except InvalidVersion as exc:
        raise EngineBootstrapError(
            f"无法解析 testplat-engine 版本号: {check_version!r}"
        ) from exc

    if parsed not in ENGINE_VERSION_SPEC:
        raise EngineBootstrapError(
            f"testplat-engine 版本不兼容: 当前 {check_version}，"
            f"需要满足 {ENGINE_VERSION_SPEC}（Phase 3 锁定 0.2.x）。"
        )

    missing = [name for name in _REQUIRED_EXPORTS if not hasattr(eng, name)]
    if missing:
        raise EngineBootstrapError(
            "testplat-engine Interface 不兼容，缺少公开符号: "
            + ", ".join(missing)
            + f"。当前版本 {check_version}。"
        )

    factory = getattr(eng, "create_engine", None)
    if not callable(factory):
        raise EngineBootstrapError(
            "testplat-engine 缺少公开 runtime 入口 create_engine()。"
            f"当前版本 {check_version} 可能只安装了 Interface 契约；"
            "请安装含真实执行实现的 0.2.x（见 README）。"
        )

    try:
        runtime = factory()
    except Exception as exc:
        raise EngineBootstrapError(
            "testplat-engine.create_engine() 调用失败，无法在启动期构造执行引擎："
            f"异常类型 {type(exc).__name__}"
        ) from exc

    execute = getattr(runtime, "execute", None)
    if execute is None or not callable(execute):
        raise EngineBootstrapError(
            "testplat-engine.create_engine() 返回值缺少可调用的 execute；"
            "无法作为 EnginePort 使用。"
        )
    if not inspect.iscoroutinefunction(execute):
        raise EngineBootstrapError(
            "testplat-engine.create_engine() 返回值的 execute 不是 async 协程函数；"
            "无法作为 EnginePort 使用。"
        )

    logger.info(
        "Engine 依赖就绪: %s==%s（create_engine 已验证）",
        ENGINE_DISTRIBUTION,
        check_version,
    )
    return check_version
