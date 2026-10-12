"""Phase 3.3a：从 ``{config_root}/auth/{env}.yaml`` 与进程环境变量构造 Engine ``AuthTable``。

边界与不变量
------------
- auth 配置文件入 git、**不含秘密**；秘密只来自 Control 进程的环境变量（D2），
  变量名必须匹配 ``^TESTPLAT_[A-Z0-9_]+$``，防止借模板读取任意进程环境。
- 文件不存在 → 返回 ``None``（不是空表），Engine 行为与 Phase 3 / v0.2.0 一致（Q2）。
- 配置本身有错（YAML 非法、schema 不符、``none`` 身份、大小写重复头名、无占位符的模板、
  ``default_identity`` 指向不存在的身份）→ 直接抛 ``InvalidEnvironmentError``（preflight 422）。
- 秘密层面的问题（变量缺失/为空/过短/不在白名单）→ 该身份降级为 ``UnavailableAuth``，
  只在资产真正用到它时由 Engine 报 422；未用到的身份不影响执行（设计稿 §5.3）。
- 秘密值只在本模块内短暂以 ``str`` 存在，立即包进 ``SecretStr``；任何异常消息、
  ``public_reason``、``log_reason``、日志都只含身份名 / header 名 / 变量名，绝不含值或模板原文。
- 日志只记身份名、变量名、kind 与异常类型名；不用 ``logger.exception`` / ``exc_info``。
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from testplat_engine import (
    AuthMaterial,
    AuthTable,
    InvalidEnvironmentError,
    SecretStr,
    StaticHeaderAuth,
    UnavailableAuth,
)

logger = logging.getLogger(__name__)

# 秘密最小长度：与 Engine MIN_SECRET_LENGTH 一致；Control 先拦截，绝不触发 Engine 构造期拒绝。
MIN_SECRET_LENGTH = 8
# 身份名：小写字母开头，便于在资产 `auth:` 中书写；`none` 是保留名（Q6），单独拒绝。
IDENTITY_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
RESERVED_IDENTITY = "none"
# header 名：RFC 7230 token。
HEADER_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
# 变量名白名单（D2）。
SECRET_NAME_RE = re.compile(r"^TESTPLAT_[A-Z0-9_]+$")
# 模板占位符：`${secret:NAME}`。NAME 先按宽松字符集截取，再单独做白名单判定，
# 这样 `${secret:HOME}` 会落到“不在白名单”（UnavailableAuth），而不是 schema 错误。
_PLACEHOLDER_RE = re.compile(r"\$\{secret:([A-Za-z0-9_]+)\}")
_ROOT_KEYS = frozenset({"identities", "default_identity"})
_IDENTITY_KEYS = frozenset({"headers"})


@dataclass(frozen=True, slots=True)
class _HeaderTemplate:
    """单个凭证头模板拆分后的结构：字面量片段与变量名交替出现。"""

    literals: tuple[str, ...]  # 长度 = len(variables) + 1
    variables: tuple[str, ...]


def auth_config_path(config_root: str | Path, env: str) -> Path:
    """auth 配置的唯一位置：``{config_root}/auth/{env}.yaml``。"""
    return Path(config_root) / "auth" / f"{env}.yaml"


def _schema_error(env: str, detail: str) -> InvalidEnvironmentError:
    """配置 schema 错误；``detail`` 只允许含身份名 / header 名 / 字段名。"""
    return InvalidEnvironmentError(
        public_message=f"鉴权配置无效 ({env}): {detail}",
        log_reason=f"auth 配置 schema 错误: {detail}",
    )


def _parse_template(env: str, identity: str, header: str, template: object) -> _HeaderTemplate:
    """拆分 header 模板。

    只允许 ``${secret:NAME}`` 占位与字面量拼接；出现其它 ``${`` 写法、或一个占位都没有（A2）
    均为 schema 错误。错误消息不回显模板原文（模板虽不含秘密，也避免误填值外泄）。
    """
    where = f"身份 {identity} 的 header {header}"
    if not isinstance(template, str):
        raise _schema_error(env, f"{where} 的值必须是字符串模板")
    literals: list[str] = []
    variables: list[str] = []
    cursor = 0
    for match in _PLACEHOLDER_RE.finditer(template):
        literals.append(template[cursor : match.start()])
        variables.append(match.group(1))
        cursor = match.end()
    literals.append(template[cursor:])
    if not variables:
        raise _schema_error(env, f"{where} 必须至少包含一个 ${{secret:NAME}} 占位符")
    if any("${" in piece for piece in literals):
        raise _schema_error(env, f"{where} 只允许 ${{secret:NAME}} 形式的占位符")
    if any(ch in piece for piece in literals for ch in "\r\n\x00"):
        raise _schema_error(env, f"{where} 含非法控制字符")
    return _HeaderTemplate(literals=tuple(literals), variables=tuple(variables))


def _check_variable(name: str, environ: Mapping[str, str]) -> tuple[str | None, str | None]:
    """检查单个变量（Q5：每个变量单独检查白名单与长度）。

    Returns:
        ``(原始值, None)`` 或 ``(None, 只含变量名的不可用原因)``。
    """
    if not SECRET_NAME_RE.fullmatch(name):
        return None, f"环境变量 {name} 不在 TESTPLAT_ 白名单内"
    raw = environ.get(name)
    if raw is None:
        return None, f"环境变量 {name} 未设置"
    if raw == "":
        return None, f"环境变量 {name} 为空"
    if len(raw) < MIN_SECRET_LENGTH:
        return None, f"环境变量 {name} 长度不足 {MIN_SECRET_LENGTH}"
    if any(ch in raw for ch in "\r\n\x00"):
        # 含换行/NUL 的值无法作为合法 header 值发出（且可能导致 header 注入）。
        return None, f"环境变量 {name} 含非法控制字符"
    return raw, None


def _build_identity(
    env: str,
    identity: str,
    templates: dict[str, _HeaderTemplate],
    environ: Mapping[str, str],
) -> AuthMaterial:
    """渲染一个身份；任一变量不可用 → 整个身份为 ``UnavailableAuth``。

    ``secret_values``（A1）= 该身份全部模板引用变量的原始值，按首次出现顺序去重；
    每个都已在 ``_check_variable`` 中保证 ≥ 8，绝不依赖 Engine 的“整段头值即秘密”兜底。
    """
    reasons: list[str] = []
    values: dict[str, str] = {}
    checked: set[str] = set()
    for template in templates.values():
        for name in template.variables:
            # 同一变量在多个模板/位置出现时只检查一次、只计一份原始值。
            if name in checked:
                continue
            checked.add(name)
            raw, reason = _check_variable(name, environ)
            if reason is not None:
                reasons.append(reason)
            else:
                values[name] = raw  # type: ignore[assignment]
    if reasons:
        # 日志只含身份名与原因（原因只含变量名）。
        logger.warning(
            "鉴权身份不可用 env=%s identity=%s kind=unavailable reasons=%s",
            env,
            identity,
            "; ".join(reasons),
        )
        return UnavailableAuth(public_reason="; ".join(reasons))

    headers: dict[str, SecretStr] = {}
    for header, template in templates.items():
        parts: list[str] = [template.literals[0]]
        for name, literal in zip(template.variables, template.literals[1:], strict=True):
            parts.append(values[name])
            parts.append(literal)
        headers[header] = SecretStr("".join(parts))
    # 按值去重：不同变量恰好同值时只传一份（替换集合是值集合）。
    unique_raw = list(dict.fromkeys(values.values()))
    secret_values = tuple(SecretStr(raw) for raw in unique_raw)
    try:
        material: AuthMaterial = StaticHeaderAuth(headers=headers, secret_values=secret_values)
    except (TypeError, ValueError) as exc:
        # 理论上不可达（名字与长度均已校验）；M1：绝不使用 str(exc)，只记类型名。
        logger.error(
            "构造凭证材料失败 env=%s identity=%s exc_type=%s", env, identity, type(exc).__name__
        )
        raise InvalidEnvironmentError(
            public_message=f"鉴权配置无效 ({env}): 身份 {identity} 的凭证材料无法构造",
            log_reason=f"StaticHeaderAuth 构造失败: identity={identity} {type(exc).__name__}",
        ) from None
    logger.info(
        "鉴权身份就绪 env=%s identity=%s kind=static_headers headers=%s variables=%s",
        env,
        identity,
        list(headers),
        list(values),
    )
    return material


def _parse_identities(env: str, raw: object) -> dict[str, dict[str, _HeaderTemplate]]:
    """校验 ``identities`` 结构，返回 身份名 → header 名 → 模板。"""
    if not isinstance(raw, dict):
        raise _schema_error(env, "identities 必须是对象")
    parsed: dict[str, dict[str, _HeaderTemplate]] = {}
    for identity, body in raw.items():
        if not isinstance(identity, str) or not IDENTITY_NAME_RE.fullmatch(identity):
            raise _schema_error(env, "身份名必须匹配 ^[a-z][a-z0-9_]*$")
        if identity == RESERVED_IDENTITY:
            raise _schema_error(env, "none 是保留名，不能作为身份名")
        if not isinstance(body, dict):
            raise _schema_error(env, f"身份 {identity} 必须是对象")
        unknown = sorted(str(key) for key in set(body) - _IDENTITY_KEYS)
        if unknown:
            raise _schema_error(env, f"身份 {identity} 含未知字段: {', '.join(unknown)}")
        headers = body.get("headers")
        if not isinstance(headers, dict) or not headers:
            raise _schema_error(env, f"身份 {identity} 的 headers 必须是非空对象")
        templates: dict[str, _HeaderTemplate] = {}
        seen_lower: dict[str, str] = {}
        for header, template in headers.items():
            if not isinstance(header, str) or not HEADER_NAME_RE.fullmatch(header):
                # 非法名字可能是误填的值，不回显。
                raise _schema_error(env, f"身份 {identity} 含非法 header 名")
            lower = header.lower()
            if lower in seen_lower:
                # Q3：同一身份内仅大小写不同的头名会让“只发一份”的语义不确定。
                raise _schema_error(
                    env,
                    f"身份 {identity} 的 header {seen_lower[lower]} 与 {header} 仅大小写不同",
                )
            seen_lower[lower] = header
            templates[header] = _parse_template(env, identity, header, template)
        parsed[identity] = templates
    return parsed


def load_auth_table(
    config_root: str | Path,
    env: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> AuthTable | None:
    """加载项目环境的身份表。

    Args:
        config_root: 项目配置根目录。
        env: 环境名（调用方已由 ``load_project_environment`` 校验非空）。
        environ: 秘密来源；缺省为 ``os.environ``（测试注入假值）。

    Returns:
        ``AuthTable``；配置文件不存在时返回 ``None``（Q2，不是空表）。

    Raises:
        InvalidEnvironmentError: YAML 非法、schema 错误、``default_identity`` 不存在（Q7）。
    """
    source: Mapping[str, str] = os.environ if environ is None else environ
    path = auth_config_path(config_root, env)
    if not path.is_file():
        return None

    try:
        loaded: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        # YAML 异常原文含出错行片段，只记类型名。
        raise InvalidEnvironmentError(
            public_message=f"鉴权配置 YAML 无效: {env}",
            log_reason=f"{path}: {type(exc).__name__}",
        ) from None
    except (OSError, UnicodeDecodeError) as exc:
        logger.error("读取鉴权配置失败 env=%s exc_type=%s", env, type(exc).__name__)
        raise InvalidEnvironmentError(
            public_message=f"无法读取鉴权配置: {env}",
            log_reason=f"{path}: {type(exc).__name__}",
        ) from None

    if not isinstance(loaded, dict):
        raise _schema_error(env, "根节点必须是对象")
    unknown = sorted(str(key) for key in set(loaded) - _ROOT_KEYS)
    if unknown:
        raise _schema_error(env, f"含未知字段: {', '.join(unknown)}")
    if "identities" not in loaded:
        raise _schema_error(env, "缺少 identities")
    identities = _parse_identities(env, loaded["identities"])

    default_identity = loaded.get("default_identity")
    if default_identity is not None:
        if not isinstance(default_identity, str) or not IDENTITY_NAME_RE.fullmatch(
            default_identity
        ):
            raise _schema_error(env, "default_identity 必须是合法身份名")
        if default_identity not in identities:
            # Q7：指向不存在的身份是配置错误，加载即 422；指向不可用身份则留给 Engine。
            raise _schema_error(env, f"default_identity 指向不存在的身份: {default_identity}")

    materials = {
        name: _build_identity(env, name, templates, source)
        for name, templates in identities.items()
    }
    try:
        return AuthTable(identities=materials, default_identity=default_identity)
    except (TypeError, ValueError) as exc:
        # 结构已在上面校验，理论上不可达；同样不外显 str(exc)（M1）。
        logger.error("构造身份表失败 env=%s exc_type=%s", env, type(exc).__name__)
        raise InvalidEnvironmentError(
            public_message=f"鉴权配置无效 ({env}): 身份表无法构造",
            log_reason=f"AuthTable 构造失败: {type(exc).__name__}",
        ) from None
