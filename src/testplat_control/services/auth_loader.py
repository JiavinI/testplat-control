"""Phase 3.3b：从 ``{config_root}/auth/{env}.yaml`` 与进程环境变量构造 Engine ``AuthTable``。

边界与不变量
------------
- auth 配置文件入 git、**不含秘密**；秘密只来自 Control 进程的环境变量（D2），
  变量名必须匹配 ``^TESTPLAT_[A-Z0-9_]+$``，防止借模板读取任意进程环境。
- 文件不存在 → 返回 ``None``（不是空表），Engine 行为与 Phase 3 / v0.2.0 一致（Q2）。
- 配置本身有错（YAML 非法、schema 不符、``none`` 身份、大小写重复头名、占位符非法、
  ``default_identity`` 指向不存在的身份、headers/login 互斥违反等）→ 直接抛
  ``InvalidEnvironmentError``（preflight 422）。
- 秘密层面的问题（变量缺失/为空/过短/不在白名单）→ 该身份降级为 ``UnavailableAuth``，
  只在资产真正用到它时由 Engine 报 422；未用到的身份不影响执行（设计稿 §5.3）。
- 秘密值只在本模块内短暂以 ``str`` 存在，立即包进 ``SecretStr``；任何异常消息、
  ``public_reason``、``log_reason``、日志都只含身份名 / header 名 / 变量名 / 策略名，
  绝不含值或模板原文。
- 日志只记身份名、变量名、kind、tier、策略名与异常类型名；不用 ``logger.exception`` /
  ``exc_info``。
- ``AuthTable.connections`` 始终传入映射（无连接时传空映射，绝不省略，U3）。
- 顶层 ``login_plugins`` 白名单随身份表一并返回，供 Engine 启动注册（E1）。
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from testplat_engine import (
    AuthMaterial,
    AuthTable,
    ExpiresFrom,
    ExtractRule,
    InvalidEnvironmentError,
    LoginAuth,
    LoginBody,
    LoginFlow,
    LoginStep,
    ProbeSpec,
    SecretStr,
    StaticHeaderAuth,
    UnavailableAuth,
    Validity,
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
# 命名值 / 策略名 / 连接名：与 Engine 保守标识符对齐。
LOGIN_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]{0,63}$")
# 模板占位符：`${secret:NAME}` / `${login:名字}` / `${login_host}`。
_SECRET_RE = re.compile(r"\$\{secret:([A-Za-z0-9_]+)\}")
_LOGIN_RE = re.compile(r"\$\{login:([^}]*)\}")
_LOGIN_HOST = "${login_host}"
_GENERIC_FLOW = "generic_flow"
_LOGIN_BODY_TYPES = frozenset({"json", "form", "query", "raw"})
_EXTRACT_SOURCES = frozenset({"body_json", "response_header", "cookies", "html_meta"})
_EXPIRES_UNITS = frozenset({"seconds", "epoch_ms", "epoch_s"})
_ROOT_KEYS = frozenset({"identities", "default_identity", "connections", "login_plugins"})
_IDENTITY_KEYS = frozenset({"headers", "login"})
_LOGIN_KEYS = frozenset(
    {"strategy", "host", "steps", "validity", "session", "probe", "inject", "params"}
)


@dataclass(frozen=True, slots=True)
class AuthLoadResult:
    """一次 auth 配置加载结果：身份表 + 插件白名单（E1）。"""

    table: AuthTable
    login_plugins: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _HeaderTemplate:
    """单个凭证头模板拆分后的结构：字面量片段与变量名交替出现。"""

    literals: tuple[str, ...]  # 长度 = len(variables) + 1
    variables: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _MixedTemplate:
    """登录相关模板：可含 ``${secret:}`` / ``${login:}`` / ``${login_host}`` 与字面量。"""

    literals: tuple[str, ...]
    secrets: tuple[str, ...]  # 与 literals 交错：lit0 + secret0 + lit1 + ...
    # 渲染后若仍含 ${login:} / ${login_host}，以 str 或 SecretStr 形式交给 Engine。
    has_login_ref: bool
    has_login_host: bool


def auth_config_path(config_root: str | Path, env: str) -> Path:
    """auth 配置的唯一位置：``{config_root}/auth/{env}.yaml``。"""
    return Path(config_root) / "auth" / f"{env}.yaml"


def _schema_error(env: str, detail: str) -> InvalidEnvironmentError:
    """配置 schema 错误；``detail`` 只允许含身份名 / header 名 / 字段名 / 策略名。"""
    return InvalidEnvironmentError(
        public_message=f"鉴权配置无效 ({env}): {detail}",
        log_reason=f"auth 配置 schema 错误: {detail}",
    )


def _parse_secret_only_template(
    env: str, identity: str, header: str, template: object
) -> _HeaderTemplate:
    """拆分静态 header 模板（3.3a）：只允许 ``${secret:NAME}``。"""
    where = f"身份 {identity} 的 header {header}"
    if not isinstance(template, str):
        raise _schema_error(env, f"{where} 的值必须是字符串模板")
    literals: list[str] = []
    variables: list[str] = []
    cursor = 0
    for match in _SECRET_RE.finditer(template):
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


def _parse_mixed_template(env: str, where: str, template: object) -> _MixedTemplate:
    """拆分登录相关模板：允许 secret / login / login_host；login 占位留在字面量里。"""
    if not isinstance(template, str):
        raise _schema_error(env, f"{where} 的值必须是字符串模板")
    literals: list[str] = []
    secrets: list[str] = []
    cursor = 0
    has_login_ref = False
    has_login_host = False
    while cursor < len(template):
        if template.startswith(_LOGIN_HOST, cursor):
            # 并入当前正在构建的字面量段（若尚未开始则开新段）。
            if not literals or len(literals) == len(secrets):
                literals.append(_LOGIN_HOST)
            else:
                literals[-1] += _LOGIN_HOST
            has_login_host = True
            cursor += len(_LOGIN_HOST)
            continue
        secret_match = _SECRET_RE.match(template, cursor)
        if secret_match:
            if len(literals) == len(secrets):
                literals.append("")
            secrets.append(secret_match.group(1))
            cursor = secret_match.end()
            continue
        login_match = _LOGIN_RE.match(template, cursor)
        if login_match:
            name = login_match.group(1)
            if not LOGIN_NAME_RE.fullmatch(name):
                raise _schema_error(env, f"{where} 的 ${{login:}} 引用名非法")
            piece = login_match.group(0)
            if len(literals) == len(secrets):
                literals.append(piece)
            else:
                literals[-1] += piece
            has_login_ref = True
            cursor = login_match.end()
            continue
        if template.startswith("${", cursor):
            raise _schema_error(
                env, f"{where} 只允许 ${{secret:NAME}} / ${{login:名字}} / ${{login_host}}"
            )
        # 普通字符：并入字面量。
        next_special = len(template)
        for token in ("${",):
            idx = template.find(token, cursor)
            if idx >= 0:
                next_special = min(next_special, idx)
        chunk = template[cursor:next_special]
        if any(ch in chunk for ch in "\r\n\x00"):
            raise _schema_error(env, f"{where} 含非法控制字符")
        if len(literals) == len(secrets):
            literals.append(chunk)
        else:
            literals[-1] += chunk
        cursor = next_special
    # 保证 literals 长度 = len(secrets) + 1。
    if len(literals) == len(secrets):
        literals.append("")
    if len(literals) != len(secrets) + 1:
        # 无 secret 时 literals 应恰好一段。
        if not secrets and len(literals) == 1:
            pass
        else:
            raise _schema_error(env, f"{where} 模板解析失败")
    return _MixedTemplate(
        literals=tuple(literals),
        secrets=tuple(secrets),
        has_login_ref=has_login_ref,
        has_login_host=has_login_host,
    )


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
        return None, f"环境变量 {name} 含非法控制字符"
    return raw, None


def _collect_secret_problems(
    names: Sequence[str], environ: Mapping[str, str]
) -> tuple[dict[str, str], list[str]]:
    """按首次出现顺序检查变量；返回可用值映射与不可用原因列表。"""
    reasons: list[str] = []
    values: dict[str, str] = {}
    checked: set[str] = set()
    for name in names:
        if name in checked:
            continue
        checked.add(name)
        raw, reason = _check_variable(name, environ)
        if reason is not None:
            reasons.append(reason)
        else:
            values[name] = raw  # type: ignore[assignment]
    return values, reasons


def _render_secret_only(template: _HeaderTemplate, values: Mapping[str, str]) -> str:
    parts: list[str] = [template.literals[0]]
    for name, literal in zip(template.variables, template.literals[1:], strict=True):
        parts.append(values[name])
        parts.append(literal)
    return "".join(parts)


def _render_mixed(template: _MixedTemplate, values: Mapping[str, str]) -> str | SecretStr:
    """渲染混合模板：若含 secret 则整体为 SecretStr（可仍含 ${login:} 占位）。"""
    if not template.secrets:
        return template.literals[0]
    parts: list[str] = [template.literals[0]]
    for name, literal in zip(template.secrets, template.literals[1:], strict=True):
        parts.append(values[name])
        parts.append(literal)
    return SecretStr("".join(parts))


def _build_static_identity(
    env: str,
    identity: str,
    templates: dict[str, _HeaderTemplate],
    environ: Mapping[str, str],
) -> AuthMaterial:
    """渲染静态 header 身份；任一变量不可用 → ``UnavailableAuth``。"""
    ordered: list[str] = []
    for template in templates.values():
        ordered.extend(template.variables)
    values, reasons = _collect_secret_problems(ordered, environ)
    if reasons:
        logger.warning(
            "鉴权身份不可用 env=%s identity=%s kind=unavailable reasons=%s",
            env,
            identity,
            "; ".join(reasons),
        )
        return UnavailableAuth(public_reason="; ".join(reasons))

    headers: dict[str, SecretStr] = {}
    for header, template in templates.items():
        headers[header] = SecretStr(_render_secret_only(template, values))
    unique_raw = list(dict.fromkeys(values.values()))
    secret_values = tuple(SecretStr(raw) for raw in unique_raw)
    try:
        material: AuthMaterial = StaticHeaderAuth(headers=headers, secret_values=secret_values)
    except (TypeError, ValueError) as exc:
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


def _parse_extract_rule(env: str, identity: str, step_name: str, raw: object) -> ExtractRule:
    where = f"身份 {identity} 步骤 {step_name} 的 extract"
    if not isinstance(raw, dict):
        raise _schema_error(env, f"{where} 必须是对象")
    source = raw.get("source")
    if source not in _EXTRACT_SOURCES:
        raise _schema_error(env, f"{where} 的 source 不受支持")
    as_name = raw.get("as")
    if not isinstance(as_name, str) or not LOGIN_NAME_RE.fullmatch(as_name):
        raise _schema_error(env, f"{where} 的 as 必须是合法命名值")
    optional = raw.get("optional", False)
    if not isinstance(optional, bool):
        raise _schema_error(env, f"{where} 的 optional 必须是布尔值")
    unknown = sorted(
        str(k) for k in set(raw) - {"source", "as", "path", "name", "format", "optional"}
    )
    if unknown:
        raise _schema_error(env, f"{where} 含未知字段: {', '.join(unknown)}")
    try:
        return ExtractRule(
            source=source,
            as_name=as_name,
            path=raw.get("path"),
            name=raw.get("name"),
            format=raw.get("format"),
            optional=optional,
        )
    except (TypeError, ValueError):
        raise _schema_error(env, f"{where} 字段不合法") from None


def _render_mapping_templates(
    env: str,
    where: str,
    raw: object,
    *,
    headers: bool,
    environ: Mapping[str, str],
    secret_names: list[str],
) -> tuple[dict[str, str | SecretStr] | None, list[str]]:
    """解析并（在秘密可用时）渲染 header/params 映射；秘密问题累积到 reasons。"""
    if raw is None:
        return None, []
    if not isinstance(raw, dict):
        raise _schema_error(env, f"{where} 必须是对象")
    if not raw:
        return {}, []
    parsed: dict[str, _MixedTemplate] = {}
    seen_lower: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            raise _schema_error(env, f"{where} 含非法键")
        if headers:
            if not HEADER_NAME_RE.fullmatch(key):
                raise _schema_error(env, f"{where} 含非法 header 名")
            lower = key.lower()
            if lower in seen_lower:
                raise _schema_error(env, f"{where} 的 {seen_lower[lower]} 与 {key} 仅大小写不同")
            seen_lower[lower] = key
        parsed[key] = _parse_mixed_template(env, f"{where}[{key}]", value)
        secret_names.extend(parsed[key].secrets)
    values, reasons = _collect_secret_problems(
        [n for t in parsed.values() for n in t.secrets], environ
    )
    if reasons:
        return None, reasons
    out: dict[str, str | SecretStr] = {}
    for key, template in parsed.items():
        out[key] = _render_mixed(template, values)
    return out, []


def _parse_login_body(
    env: str,
    identity: str,
    step_name: str,
    raw: object,
    environ: Mapping[str, str],
    secret_names: list[str],
) -> tuple[LoginBody | None, list[str]]:
    if raw is None:
        return None, []
    where = f"身份 {identity} 步骤 {step_name} 的 body"
    if not isinstance(raw, dict):
        raise _schema_error(env, f"{where} 必须是对象")
    unknown = sorted(str(k) for k in set(raw) - {"type", "fields", "content", "content_type"})
    if unknown:
        raise _schema_error(env, f"{where} 含未知字段: {', '.join(unknown)}")
    body_type = raw.get("type", "json")
    if body_type not in _LOGIN_BODY_TYPES:
        raise _schema_error(env, f"{where} 的 type 必须是 json/form/query/raw")
    if body_type == "raw":
        content_t = _parse_mixed_template(env, f"{where}.content", raw.get("content"))
        secret_names.extend(content_t.secrets)
        values, reasons = _collect_secret_problems(content_t.secrets, environ)
        if reasons:
            return None, reasons
        content = _render_mixed(content_t, values)
        content_type = raw.get("content_type")
        if content_type is not None and not isinstance(content_type, str):
            raise _schema_error(env, f"{where}.content_type 必须是字符串")
        try:
            return LoginBody(type="raw", content=content, content_type=content_type), []
        except (TypeError, ValueError):
            raise _schema_error(env, f"{where} 字段不合法") from None

    fields_raw = raw.get("fields", {})
    if fields_raw is None:
        fields_raw = {}
    if not isinstance(fields_raw, dict):
        raise _schema_error(env, f"{where}.fields 必须是对象")
    # 递归渲染 fields 中的字符串模板；嵌套结构保留。
    reasons: list[str] = []
    all_secret_names: list[str] = []

    def walk(node: object, path: str) -> object:
        nonlocal reasons
        if isinstance(node, str):
            mixed = _parse_mixed_template(env, f"{where}.fields{path}", node)
            all_secret_names.extend(mixed.secrets)
            return mixed
        if isinstance(node, Mapping):
            return {str(k): walk(v, f"{path}.{k}") for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, f"{path}[]") for v in node]
        if isinstance(node, (bool, int, float)) or node is None:
            return node
        raise _schema_error(env, f"{where}.fields 含非法值类型")

    walked = walk(fields_raw, "")
    secret_names.extend(all_secret_names)
    values, reasons = _collect_secret_problems(all_secret_names, environ)
    if reasons:
        return None, reasons

    def render_node(node: object) -> object:
        if isinstance(node, _MixedTemplate):
            return _render_mixed(node, values)
        if isinstance(node, Mapping):
            return {k: render_node(v) for k, v in node.items()}
        if isinstance(node, list):
            return [render_node(v) for v in node]
        return node

    fields = render_node(walked)
    content_type = raw.get("content_type")
    if content_type is not None and not isinstance(content_type, str):
        raise _schema_error(env, f"{where}.content_type 必须是字符串")
    try:
        return LoginBody(type=body_type, fields=fields, content_type=content_type), []  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise _schema_error(env, f"{where} 字段不合法") from None


def _parse_login_step(
    env: str,
    identity: str,
    raw: object,
    environ: Mapping[str, str],
    secret_names: list[str],
) -> tuple[LoginStep | None, list[str]]:
    if not isinstance(raw, dict):
        raise _schema_error(env, f"身份 {identity} 的 login.steps 元素必须是对象")
    name = raw.get("name")
    if not isinstance(name, str) or not LOGIN_NAME_RE.fullmatch(name):
        raise _schema_error(env, f"身份 {identity} 的登录步骤名非法")
    where = f"身份 {identity} 步骤 {name}"
    unknown = sorted(
        str(k)
        for k in set(raw) - {"name", "method", "path", "headers", "body", "success", "extract"}
    )
    if unknown:
        raise _schema_error(env, f"{where} 含未知字段: {', '.join(unknown)}")
    method = raw.get("method")
    path = raw.get("path")
    if not isinstance(method, str) or not method.strip():
        raise _schema_error(env, f"{where} 的 method 不能为空")
    if not isinstance(path, str) or not path:
        raise _schema_error(env, f"{where} 的 path 不能为空")
    # path 可含 ${login:} / ${login_host} / ${secret:}
    path_t = _parse_mixed_template(env, f"{where}.path", path)
    secret_names.extend(path_t.secrets)
    headers, header_reasons = _render_mapping_templates(
        env,
        f"{where}.headers",
        raw.get("headers"),
        headers=True,
        environ=environ,
        secret_names=secret_names,
    )
    body, body_reasons = _parse_login_body(
        env, identity, name, raw.get("body"), environ, secret_names
    )
    reasons = header_reasons + body_reasons
    path_values, path_reasons = _collect_secret_problems(path_t.secrets, environ)
    reasons.extend(path_reasons)
    if reasons:
        return None, reasons
    rendered_path = _render_mixed(path_t, path_values)
    if isinstance(rendered_path, SecretStr):
        # path 含秘密时仍以 SecretStr 交给 Engine（Template 允许）；LoginStep.path 要求 str。
        # Engine LoginStep.path 是 str——含 secret 的 path 需 reveal 后仍可能含 login 占位。
        # 规范：path 不应只靠 SecretStr；若含 secret，渲染为 str 会把秘密放进明文 DTO 字段。
        # 设计稿示例 path 不含 secret。若含 secret，以 schema 错误拒绝，避免明文泄漏到 path。
        raise _schema_error(env, f"{where}.path 不得包含 ${{secret:}}（请放在 body/headers）")
    extract_raw = raw.get("extract", [])
    if extract_raw is None:
        extract_raw = []
    if not isinstance(extract_raw, list):
        raise _schema_error(env, f"{where}.extract 必须是数组")
    extracts = [_parse_extract_rule(env, identity, name, item) for item in extract_raw]
    success = raw.get("success")
    if success is not None and not isinstance(success, dict):
        raise _schema_error(env, f"{where}.success 必须是对象")
    try:
        return (
            LoginStep(
                name=name,
                method=method,
                path=rendered_path,
                headers=headers,
                body=body,
                success=success,
                extract=extracts,
            ),
            [],
        )
    except (TypeError, ValueError):
        raise _schema_error(env, f"{where} 字段不合法") from None


def _parse_probe(
    env: str,
    identity: str,
    raw: object,
    environ: Mapping[str, str],
    secret_names: list[str],
) -> tuple[ProbeSpec | None, list[str]]:
    if raw is None:
        return None, []
    where = f"身份 {identity} 的 probe"
    if not isinstance(raw, dict):
        raise _schema_error(env, f"{where} 必须是对象")
    unknown = sorted(str(k) for k in set(raw) - {"method", "path", "headers", "success"})
    if unknown:
        raise _schema_error(env, f"{where} 含未知字段: {', '.join(unknown)}")
    method = raw.get("method", "GET")
    path = raw.get("path", "/")
    if not isinstance(method, str) or not method.strip():
        raise _schema_error(env, f"{where}.method 不能为空")
    if not isinstance(path, str) or not path:
        raise _schema_error(env, f"{where}.path 不能为空")
    path_t = _parse_mixed_template(env, f"{where}.path", path)
    secret_names.extend(path_t.secrets)
    headers, header_reasons = _render_mapping_templates(
        env,
        f"{where}.headers",
        raw.get("headers"),
        headers=True,
        environ=environ,
        secret_names=secret_names,
    )
    path_values, path_reasons = _collect_secret_problems(path_t.secrets, environ)
    reasons = header_reasons + path_reasons
    if reasons:
        return None, reasons
    rendered_path = _render_mixed(path_t, path_values)
    if isinstance(rendered_path, SecretStr):
        raise _schema_error(env, f"{where}.path 不得包含 ${{secret:}}")
    success = raw.get("success")
    if success is not None and not isinstance(success, dict):
        raise _schema_error(env, f"{where}.success 必须是对象")
    try:
        return ProbeSpec(method=method, path=rendered_path, headers=headers, success=success), []
    except (TypeError, ValueError):
        raise _schema_error(env, f"{where} 字段不合法") from None


def _parse_validity(env: str, identity: str, raw: object) -> Validity:
    if raw is None:
        return Validity()
    where = f"身份 {identity} 的 validity"
    if not isinstance(raw, dict):
        raise _schema_error(env, f"{where} 必须是对象")
    unknown = sorted(str(k) for k in set(raw) - {"ttl_seconds", "expires_from"})
    if unknown:
        raise _schema_error(env, f"{where} 含未知字段: {', '.join(unknown)}")
    ttl = raw.get("ttl_seconds")
    expires_raw = raw.get("expires_from")
    expires: ExpiresFrom | None = None
    if expires_raw is not None:
        if not isinstance(expires_raw, dict):
            raise _schema_error(env, f"{where}.expires_from 必须是对象")
        unk = sorted(str(k) for k in set(expires_raw) - {"path", "unit", "source", "step"})
        if unk:
            raise _schema_error(env, f"{where}.expires_from 含未知字段: {', '.join(unk)}")
        unit = expires_raw.get("unit", "seconds")
        if unit not in _EXPIRES_UNITS:
            raise _schema_error(env, f"{where}.expires_from.unit 不受支持")
        try:
            expires = ExpiresFrom(
                path=expires_raw.get("path"),  # type: ignore[arg-type]
                unit=unit,
                source=expires_raw.get("source", "body_json"),
                step=expires_raw.get("step"),
            )
        except (TypeError, ValueError):
            raise _schema_error(env, f"{where}.expires_from 字段不合法") from None
    try:
        return Validity(ttl_seconds=ttl, expires_from=expires)
    except (TypeError, ValueError):
        raise _schema_error(env, f"{where} 字段不合法") from None


def _login_refs_in_templates(values: Mapping[str, str | SecretStr] | None) -> set[str]:
    refs: set[str] = set()
    if not values:
        return refs
    for item in values.values():
        if isinstance(item, str):
            refs.update(_LOGIN_RE.findall(item))
        # SecretStr 内部可能含 ${login:}；身份级 Q1 在明文侧已检查，SecretStr 交给 Engine。
    return refs


def _determine_tier(
    *,
    strategy: str,
    flow: LoginFlow | None,
    session_cookie: bool,
    probe: ProbeSpec | None,
    inject: Mapping[str, str | SecretStr] | None,
) -> str:
    """按 §1.1 / 手册判定档位。"""
    if strategy != _GENERIC_FLOW:
        return "plugin"
    assert flow is not None
    extracts = [rule for step in flow.steps for rule in step.extract]
    inject_map = inject or {}
    # 存在 SecretStr inject 时无法在不 reveal 下证明“只引用 token”→ configured。
    if any(isinstance(v, SecretStr) for v in inject_map.values()):
        plain_only_token = False
    else:
        refs = _login_refs_in_templates(inject_map)  # type: ignore[arg-type]
        plain_only_token = refs == {"token"}
    single_step = len(flow.steps) == 1
    single_extract = len(extracts) == 1
    extract_ok = False
    if single_extract:
        rule = extracts[0]
        extract_ok = rule.source in ("body_json", "response_header") and rule.as_name == "token"
    if single_step and extract_ok and plain_only_token and not session_cookie and probe is None:
        return "generic"
    return "configured"


def _build_login_identity(
    env: str,
    identity: str,
    body: Mapping[str, Any],
    environ: Mapping[str, str],
    login_plugins: Sequence[str],
) -> AuthMaterial:
    """构造 LoginAuth；秘密不可用 → UnavailableAuth。"""
    unknown = sorted(str(k) for k in set(body) - _LOGIN_KEYS)
    if unknown:
        raise _schema_error(env, f"身份 {identity} 的 login 含未知字段: {', '.join(unknown)}")
    strategy = body.get("strategy", _GENERIC_FLOW)
    if not isinstance(strategy, str) or not LOGIN_NAME_RE.fullmatch(strategy):
        raise _schema_error(env, f"身份 {identity} 的 strategy 非法")
    if strategy != _GENERIC_FLOW and strategy not in login_plugins:
        # 插件策略必须出现在白名单（E1）；未列出即配置错误。
        raise _schema_error(env, f"身份 {identity} 的策略 {strategy} 未在 login_plugins 白名单中")
    host = body.get("host")
    if not isinstance(host, str) or not host.strip():
        raise _schema_error(env, f"身份 {identity} 的 host 必须是非空字符串")

    secret_names: list[str] = []
    all_reasons: list[str] = []

    # steps / flow
    flow: LoginFlow | None = None
    if strategy == _GENERIC_FLOW:
        steps_raw = body.get("steps")
        if not isinstance(steps_raw, list) or not steps_raw:
            raise _schema_error(env, f"身份 {identity} 的 generic_flow 必须提供非空 steps")
        steps: list[LoginStep] = []
        for item in steps_raw:
            step, reasons = _parse_login_step(env, identity, item, environ, secret_names)
            all_reasons.extend(reasons)
            if step is not None:
                steps.append(step)
        if not all_reasons:
            try:
                flow = LoginFlow(steps=steps)
            except (TypeError, ValueError):
                raise _schema_error(env, f"身份 {identity} 的 steps 不合法") from None
    else:
        # 插件策略：steps 可选；若提供则仍解析为 flow（Engine 允许插件带 flow）。
        steps_raw = body.get("steps")
        if steps_raw is not None:
            if not isinstance(steps_raw, list) or not steps_raw:
                raise _schema_error(env, f"身份 {identity} 的 steps 必须是非空数组")
            steps = []
            for item in steps_raw:
                step, reasons = _parse_login_step(env, identity, item, environ, secret_names)
                all_reasons.extend(reasons)
                if step is not None:
                    steps.append(step)
            if not all_reasons:
                try:
                    flow = LoginFlow(steps=steps)
                except (TypeError, ValueError):
                    raise _schema_error(env, f"身份 {identity} 的 steps 不合法") from None

    session = body.get("session")
    session_cookie = False
    if session is not None:
        if session != "cookie":
            raise _schema_error(env, f"身份 {identity} 的 session 只支持 cookie")
        session_cookie = True

    probe, probe_reasons = _parse_probe(env, identity, body.get("probe"), environ, secret_names)
    all_reasons.extend(probe_reasons)

    inject_raw = body.get("inject")
    inject_headers: dict[str, str | SecretStr] | None = None
    if inject_raw is None:
        if not session_cookie:
            raise _schema_error(env, f"身份 {identity} 必须提供 inject，或声明 session: cookie")
    else:
        if not isinstance(inject_raw, dict):
            raise _schema_error(env, f"身份 {identity} 的 inject 必须是对象")
        unk = sorted(str(k) for k in set(inject_raw) - {"headers"})
        if unk:
            raise _schema_error(env, f"身份 {identity} 的 inject 含未知字段: {', '.join(unk)}")
        headers_raw = inject_raw.get("headers")
        if headers_raw is None:
            headers_raw = {}
        if not isinstance(headers_raw, dict):
            raise _schema_error(env, f"身份 {identity} 的 inject.headers 必须是对象")
        # 允许空 headers 仅当 session_cookie（Q2）。
        if not headers_raw and not session_cookie:
            raise _schema_error(env, f"身份 {identity} 的 inject.headers 不能为空")
        rendered, inject_reasons = _render_mapping_templates(
            env,
            f"身份 {identity} 的 inject.headers",
            headers_raw,
            headers=True,
            environ=environ,
            secret_names=secret_names,
        )
        all_reasons.extend(inject_reasons)
        inject_headers = rendered

    params_rendered, params_reasons = _render_mapping_templates(
        env,
        f"身份 {identity} 的 params",
        body.get("params"),
        headers=False,
        environ=environ,
        secret_names=secret_names,
    )
    all_reasons.extend(params_reasons)

    validity = _parse_validity(env, identity, body.get("validity"))

    # Q1/Q2 身份级：至少一个 inject 值引用 ${login:}，或 session: cookie。
    if inject_headers is not None and not all_reasons:
        plain_refs = _login_refs_in_templates(inject_headers)
        has_secret_inject = any(isinstance(v, SecretStr) for v in inject_headers.values())
        if not session_cookie and not plain_refs and not has_secret_inject:
            raise _schema_error(
                env,
                f"身份 {identity} 至少一个 inject 值须引用 ${{login:}}，或声明 session: cookie",
            )
        # extract 覆盖：generic_flow 下明文 ${login:} 引用必须由 extract 声明。
        if strategy == _GENERIC_FLOW and flow is not None and plain_refs:
            declared = flow.extracted_names()
            missing = sorted(plain_refs - declared)
            if missing:
                raise _schema_error(
                    env,
                    f"身份 {identity} 的 inject 引用了未提取的命名值: {', '.join(missing)}",
                )

    if all_reasons:
        # 去重并保持顺序。
        uniq = list(dict.fromkeys(all_reasons))
        logger.warning(
            "鉴权身份不可用 env=%s identity=%s kind=unavailable reasons=%s",
            env,
            identity,
            "; ".join(uniq),
        )
        return UnavailableAuth(public_reason="; ".join(uniq))

    # secret_values：本身份全部 ${secret:} 原始值，按首次出现去重。
    values, _ = _collect_secret_problems(secret_names, environ)
    unique_raw = list(dict.fromkeys(values.values()))
    secret_values = tuple(SecretStr(raw) for raw in unique_raw)

    tier = _determine_tier(
        strategy=strategy,
        flow=flow,
        session_cookie=session_cookie,
        probe=probe,
        inject=inject_headers,
    )
    try:
        material = LoginAuth(
            strategy=strategy,
            host=host,
            tier=tier,
            flow=flow,
            params=params_rendered,
            secret_values=secret_values,
            validity=validity,
            session_cookie=session_cookie,
            probe=probe,
            inject_headers=inject_headers,
        )
    except (TypeError, ValueError) as exc:
        logger.error(
            "构造登录凭证失败 env=%s identity=%s exc_type=%s",
            env,
            identity,
            type(exc).__name__,
        )
        raise InvalidEnvironmentError(
            public_message=f"鉴权配置无效 ({env}): 身份 {identity} 的登录凭证无法构造",
            log_reason=f"LoginAuth 构造失败: identity={identity} {type(exc).__name__}",
        ) from None
    logger.info(
        "鉴权身份就绪 env=%s identity=%s kind=login tier=%s strategy=%s",
        env,
        identity,
        tier,
        strategy,
    )
    return material


def _parse_static_headers(env: str, identity: str, headers: object) -> dict[str, _HeaderTemplate]:
    if not isinstance(headers, dict) or not headers:
        raise _schema_error(env, f"身份 {identity} 的 headers 必须是非空对象")
    templates: dict[str, _HeaderTemplate] = {}
    seen_lower: dict[str, str] = {}
    for header, template in headers.items():
        if not isinstance(header, str) or not HEADER_NAME_RE.fullmatch(header):
            raise _schema_error(env, f"身份 {identity} 含非法 header 名")
        lower = header.lower()
        if lower in seen_lower:
            raise _schema_error(
                env,
                f"身份 {identity} 的 header {seen_lower[lower]} 与 {header} 仅大小写不同",
            )
        seen_lower[lower] = header
        templates[header] = _parse_secret_only_template(env, identity, header, template)
    return templates


def _parse_connections(
    env: str, raw: object, environ: Mapping[str, str]
) -> tuple[dict[str, dict[str, object]], list[str]]:
    """解析 connections；含 ${secret:} 的字段渲染为 SecretStr。

    连接级秘密不可用时不让整表失败，而是记入 reasons 并在日志中提示；
    按设计 connections 密码缺失应使依赖它的插件身份不可用——本批将连接秘密问题
    升为 schema/不可用：任一连接字段秘密不可用 → 整次加载转为对该连接的记录，
    并返回 reasons 供调用方决定。这里采取：连接秘密不可用 → InvalidEnvironmentError
    过于严格；改为返回 partial 并让 AuthTable 带上已渲染连接，秘密问题写入 reasons，
    由 load 将其视为配置层错误（连接是共享资源，缺失应 422）。
    """
    if raw is None:
        return {}, []
    if not isinstance(raw, dict):
        raise _schema_error(env, "connections 必须是对象")
    out: dict[str, dict[str, object]] = {}
    all_reasons: list[str] = []
    for name, fields in raw.items():
        if not isinstance(name, str) or not name:
            raise _schema_error(env, "connections 含非法连接名")
        if not isinstance(fields, dict):
            raise _schema_error(env, f"connections.{name} 必须是对象")
        rendered: dict[str, object] = {}
        secret_names: list[str] = []
        templates: dict[str, _MixedTemplate | object] = {}
        for key, value in fields.items():
            if not isinstance(key, str):
                raise _schema_error(env, f"connections.{name} 键必须是字符串")
            if isinstance(value, str) and "${" in value:
                templates[key] = _parse_mixed_template(env, f"connections.{name}.{key}", value)
                assert isinstance(templates[key], _MixedTemplate)
                secret_names.extend(templates[key].secrets)  # type: ignore[union-attr]
                if templates[key].has_login_ref or templates[key].has_login_host:  # type: ignore[union-attr]
                    raise _schema_error(
                        env, f"connections.{name}.{key} 不得引用 ${{login:}} / ${{login_host}}"
                    )
            elif isinstance(value, (str, int, float, bool)) or value is None:
                templates[key] = value
            else:
                raise _schema_error(env, f"connections.{name}.{key} 必须是标量")
        values, reasons = _collect_secret_problems(secret_names, environ)
        if reasons:
            all_reasons.extend(reasons)
            continue
        for key, item in templates.items():
            if isinstance(item, _MixedTemplate):
                rendered[key] = _render_mixed(item, values)
            else:
                rendered[key] = item
        out[name] = rendered
    return out, all_reasons


def _parse_login_plugins(env: str, raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise _schema_error(env, "login_plugins 必须是数组")
    names: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str) or not LOGIN_NAME_RE.fullmatch(item):
            raise _schema_error(env, "login_plugins 元素必须是合法策略名")
        if item == _GENERIC_FLOW:
            raise _schema_error(env, "login_plugins 不得列出内置策略 generic_flow")
        if item in seen:
            raise _schema_error(env, f"login_plugins 重复: {item}")
        seen.add(item)
        names.append(item)
    return tuple(names)


def load_auth_table(
    config_root: str | Path,
    env: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> AuthTable | None:
    """加载项目环境的身份表（兼容 3.3a 调用方，丢弃白名单）。

    需要插件白名单时请用 :func:`load_auth`。
    """
    result = load_auth(config_root, env, environ=environ)
    return None if result is None else result.table


def load_auth(
    config_root: str | Path,
    env: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> AuthLoadResult | None:
    """加载项目环境的身份表与 ``login_plugins`` 白名单。

    Args:
        config_root: 项目配置根目录。
        env: 环境名（调用方已由 ``load_project_environment`` 校验非空）。
        environ: 秘密来源；缺省为 ``os.environ``（测试注入假值）。

    Returns:
        ``AuthLoadResult``；配置文件不存在时返回 ``None``（Q2，不是空表）。

    Raises:
        InvalidEnvironmentError: YAML 非法、schema 错误、``default_identity`` 不存在（Q7）、
            连接秘密不可用。
    """
    source: Mapping[str, str] = os.environ if environ is None else environ
    path = auth_config_path(config_root, env)
    if not path.is_file():
        return None

    try:
        loaded: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
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

    login_plugins = _parse_login_plugins(env, loaded.get("login_plugins"))
    connections, conn_reasons = _parse_connections(env, loaded.get("connections"), source)
    if conn_reasons:
        # 连接是共享依赖：秘密不可用视为配置/环境错误（422），避免插件拿到半残连接。
        detail = "; ".join(dict.fromkeys(conn_reasons))
        raise InvalidEnvironmentError(
            public_message=f"鉴权配置无效 ({env}): 连接秘密不可用",
            log_reason=f"connections 秘密不可用: {detail}",
        )

    identities_raw = loaded["identities"]
    if not isinstance(identities_raw, dict):
        raise _schema_error(env, "identities 必须是对象")

    materials: dict[str, AuthMaterial] = {}
    for identity, body in identities_raw.items():
        if not isinstance(identity, str) or not IDENTITY_NAME_RE.fullmatch(identity):
            raise _schema_error(env, "身份名必须匹配 ^[a-z][a-z0-9_]*$")
        if identity == RESERVED_IDENTITY:
            raise _schema_error(env, "none 是保留名，不能作为身份名")
        if not isinstance(body, dict):
            raise _schema_error(env, f"身份 {identity} 必须是对象")
        unknown_id = sorted(str(key) for key in set(body) - _IDENTITY_KEYS)
        if unknown_id:
            raise _schema_error(env, f"身份 {identity} 含未知字段: {', '.join(unknown_id)}")
        has_headers = "headers" in body
        has_login = "login" in body
        if has_headers == has_login:
            # 互斥且必须恰好一个（Q1）。
            raise _schema_error(env, f"身份 {identity} 必须且只能是 headers 或 login 之一")
        if has_headers:
            templates = _parse_static_headers(env, identity, body.get("headers"))
            materials[identity] = _build_static_identity(env, identity, templates, source)
        else:
            login_body = body.get("login")
            if not isinstance(login_body, dict):
                raise _schema_error(env, f"身份 {identity} 的 login 必须是对象")
            materials[identity] = _build_login_identity(
                env, identity, login_body, source, login_plugins
            )

    default_identity = loaded.get("default_identity")
    if default_identity is not None:
        if not isinstance(default_identity, str) or not IDENTITY_NAME_RE.fullmatch(
            default_identity
        ):
            raise _schema_error(env, "default_identity 必须是合法身份名")
        if default_identity not in materials:
            raise _schema_error(env, f"default_identity 指向不存在的身份: {default_identity}")

    try:
        # U3：始终传 connections 映射（可空），不省略字段。
        table = AuthTable(
            identities=materials,
            default_identity=default_identity,
            connections=connections,
        )
    except (TypeError, ValueError) as exc:
        logger.error("构造身份表失败 env=%s exc_type=%s", env, type(exc).__name__)
        raise InvalidEnvironmentError(
            public_message=f"鉴权配置无效 ({env}): 身份表无法构造",
            log_reason=f"AuthTable 构造失败: {type(exc).__name__}",
        ) from None
    return AuthLoadResult(table=table, login_plugins=login_plugins)
