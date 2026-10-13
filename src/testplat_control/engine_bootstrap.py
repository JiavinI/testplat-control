"""启动期 Engine 依赖诊断与登录插件发现（Phase 3.3b）。

缺包、版本不兼容或 runtime 入口无效时 fail-fast，避免用户点击「执行」才遇到模糊 500/503。

插件注册（E1 / L1）
-----------------
- 发现：``importlib.metadata.entry_points(group="testplat_engine.login_strategies")``
- 白名单：auth 配置顶层 ``login_plugins``；二者交集才传给 ``create_engine(login_strategies=...)``
- 白名单列出但未安装 → ``EngineBootstrapError``（消息只含策略名）
- 安装但未列入白名单 → 不注册，记一条 info
- ``ensure_engine_compatible`` 与 ``PackageEngineAdapter`` 两处 ``create_engine`` 共用
  :func:`resolve_login_strategies`（L1）；生产路径不得注入共享 ``http_client``（A9）
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, entry_points, version
from typing import Any

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

logger = logging.getLogger(__name__)

# Phase 3.3b 兼容范围：与 pyproject 中 testplat-engine 约束一致。
ENGINE_VERSION_SPEC = SpecifierSet(">=0.4.0,<0.5")
ENGINE_DISTRIBUTION = "testplat-engine"
LOGIN_STRATEGY_GROUP = "testplat_engine.login_strategies"
_REQUIRED_EXPORTS = (
    "ApiExecutionRequest",
    "ApiExecutionOutcome",
    "CaseExecutionRequest",
    "CaseExecutionOutcome",
    "StepOutcome",
    "EngineError",
    "InvalidInputError",
    # Phase 3.3a 鉴权 DTO
    "AuthTable",
    "StaticHeaderAuth",
    "UnavailableAuth",
    "SecretStr",
    # Phase 3.3b 登录鉴权 DTO
    "LoginAuth",
    "LoginFlow",
    "LoginStep",
    "ExtractRule",
    "ProbeSpec",
    "Validity",
    "LoginStrategy",
    "LoginContext",
    "LoginResult",
    "EnginePort",
    "__version__",
)


class EngineBootstrapError(RuntimeError):
    """启动期 Engine 依赖不可用；消息可直接展示给运维。"""


def discover_installed_login_strategies() -> dict[str, Any]:
    """发现已安装的登录策略 entry point；返回策略名 → 已加载实例。

    加载失败（工厂抛错）时跳过该入口并记 error（只含策略名与异常类型），
    不让单个坏插件阻断整个发现过程；白名单若点名到它，由
    :func:`resolve_login_strategies` 再报「未安装」。
    """
    try:
        selected = entry_points(group=LOGIN_STRATEGY_GROUP)
    except TypeError:
        # 极旧 importlib.metadata：回退。
        selected = entry_points().get(LOGIN_STRATEGY_GROUP, [])  # type: ignore[index]
    found: dict[str, Any] = {}
    for ep in selected:
        name = getattr(ep, "name", None)
        if not isinstance(name, str) or not name:
            logger.error("登录策略 entry point 缺少 name，已忽略")
            continue
        try:
            factory = ep.load()
            strategy = factory() if callable(factory) else factory
        except Exception as exc:  # noqa: BLE001 — 启动发现必须吞掉插件构造异常
            logger.error(
                "加载登录策略失败 strategy=%s exc_type=%s",
                name,
                type(exc).__name__,
            )
            continue
        strategy_name = getattr(strategy, "name", None)
        if not isinstance(strategy_name, str) or not strategy_name:
            logger.error("登录策略实例缺少 name strategy=%s", name)
            continue
        if strategy_name in found:
            logger.error("登录策略 entry point 重名 strategy=%s，保留先发现的", strategy_name)
            continue
        found[strategy_name] = strategy
    return found


def resolve_login_strategies(whitelist: Sequence[str]) -> list[Any]:
    """取 entry point ∩ 白名单；供两处 ``create_engine`` 共用（L1/E1）。

    Args:
        whitelist: auth 配置 ``login_plugins``；空则不注册任何插件（仅内置 generic_flow）。

    Returns:
        策略实例列表（顺序与白名单一致）。

    Raises:
        EngineBootstrapError: 白名单列出但未安装（或加载失败）的策略名。
    """
    installed = discover_installed_login_strategies()
    missing = [name for name in whitelist if name not in installed]
    if missing:
        # 消息只含策略名。
        raise EngineBootstrapError("登录策略未安装或不符协议: " + ", ".join(missing))
    skipped = sorted(name for name in installed if name not in set(whitelist))
    for name in skipped:
        logger.info("登录策略已安装但未列入白名单，跳过注册 strategy=%s", name)
    return [installed[name] for name in whitelist]


def create_engine_with_plugins(whitelist: Sequence[str] = ()) -> Any:
    """两处调用共用的 ``create_engine(login_strategies=...)`` 入口（L1/A9）。

    不注入共享 ``http_client``；只用 ``login_strategies``。
    """
    import testplat_engine as eng

    factory = getattr(eng, "create_engine", None)
    if not callable(factory):
        raise EngineBootstrapError("testplat-engine 缺少公开 runtime 入口 create_engine()。")
    strategies = resolve_login_strategies(whitelist)
    try:
        return factory(login_strategies=strategies)
    except EngineBootstrapError:
        raise
    except Exception as exc:
        raise EngineBootstrapError(
            "testplat-engine.create_engine() 调用失败，无法在启动期构造执行引擎："
            f"异常类型 {type(exc).__name__}"
        ) from exc


def ensure_engine_compatible(login_plugins: Sequence[str] = ()) -> str:
    """校验 testplat-engine 已安装、版本兼容，并实际调用公开 ``create_engine()``。

    启动期会：
    1. 确认发行版与 Interface 符号齐全；
    2. 解析且调用唯一官方入口 ``create_engine(login_strategies=...)``；
    3. 验证返回对象具备 async ``execute``。

    Args:
        login_plugins: 可选白名单；启动 lifespan 默认空（仅验证内置路径）。
            项目执行时由 PackageEngineAdapter 按 auth 配置再创建带插件的引擎。

    Returns:
        已解析的 Engine 版本字符串。

    Raises:
        EngineBootstrapError: 缺包、版本不兼容、入口缺失、runtime 无效或白名单策略未安装。
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
        raise EngineBootstrapError(f"无法解析 testplat-engine 版本号: {check_version!r}") from exc

    if parsed not in ENGINE_VERSION_SPEC:
        raise EngineBootstrapError(
            f"testplat-engine 版本不兼容: 当前 {check_version}，"
            f"需要满足 {ENGINE_VERSION_SPEC}（Phase 3.3b 锁定 0.4.x）。"
        )

    missing = [name for name in _REQUIRED_EXPORTS if not hasattr(eng, name)]
    if missing:
        raise EngineBootstrapError(
            "testplat-engine Interface 不兼容，缺少公开符号: "
            + ", ".join(missing)
            + f"。当前版本 {check_version}。"
        )

    runtime = create_engine_with_plugins(login_plugins)

    execute = getattr(runtime, "execute", None)
    if execute is None or not callable(execute):
        raise EngineBootstrapError(
            "testplat-engine.create_engine() 返回值缺少可调用的 execute；无法作为 EnginePort 使用。"
        )
    if not inspect.iscoroutinefunction(execute):
        raise EngineBootstrapError(
            "testplat-engine.create_engine() 返回值的 execute 不是 async 协程函数；"
            "无法作为 EnginePort 使用。"
        )

    logger.info(
        "Engine 依赖就绪: %s==%s（create_engine 已验证，plugins=%s）",
        ENGINE_DISTRIBUTION,
        check_version,
        list(login_plugins),
    )
    return check_version
