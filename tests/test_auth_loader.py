"""``services/auth_loader.py`` 单元测试（Phase 3.3a，手册 §5 第 1、6、7 项）。

覆盖：文件缺失 → None（Q2）、正常渲染与 secret_values 一一对应（A1/Q5）、
变量层问题降级为 UnavailableAuth、配置层问题直接 422（A2/Q3/Q6/Q7），
以及所有异常消息、public_reason、日志里都不含假秘密（M1）。
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from testplat_engine import (
    AuthTable,
    InvalidEnvironmentError,
    SecretStr,
    StaticHeaderAuth,
    UnavailableAuth,
)

from testplat_control.services import auth_loader
from testplat_control.services.auth_loader import load_auth_table
from tests.auth_support import (
    FAKE_PARTNER,
    FAKE_SECRET,
    STANDARD_CONFIG,
    STANDARD_ENV,
    assert_no_secret,
    log_text,
    write_auth,
)


def _reveal_all(values) -> list[str]:  # noqa: ANN001
    # 测试专用：核对渲染结果需要原值；生产代码只有 Engine 注入点调用 reveal()。
    return [value.reveal() for value in values]


def test_missing_file_returns_none_not_empty_table(tmp_path: Path) -> None:
    """Q2：没有 auth 配置文件 → None，而不是空 AuthTable。"""
    assert load_auth_table(tmp_path, "test", environ=STANDARD_ENV) is None


def test_other_env_file_is_ignored(tmp_path: Path) -> None:
    write_auth(tmp_path, STANDARD_CONFIG, env="staging")
    assert load_auth_table(tmp_path, "test", environ=STANDARD_ENV) is None


def test_standard_config_builds_static_header_auth(tmp_path: Path) -> None:
    write_auth(tmp_path, STANDARD_CONFIG)
    table = load_auth_table(tmp_path, "test", environ=STANDARD_ENV)
    assert isinstance(table, AuthTable)
    assert table.default_identity == "admin"
    admin = table.identities["admin"]
    partner = table.identities["partner"]
    assert isinstance(admin, StaticHeaderAuth) and isinstance(partner, StaticHeaderAuth)
    assert _reveal_all(admin.headers.values()) == [f"Bearer {FAKE_SECRET}"]
    assert _reveal_all(partner.headers.values()) == [FAKE_PARTNER]
    # 公开表示只有名字。
    assert_no_secret([repr(table), str(table.to_dict())])


def test_secret_values_correspond_one_to_one_with_referenced_variables(tmp_path: Path) -> None:
    """A1：secret_values = 模板引用变量的原始值（去重），与变量一一对应，不靠 Engine 兜底。"""
    env = {
        "TESTPLAT_A": "tp-fake-aaaa-0001",
        "TESTPLAT_B": "tp-fake-bbbb-0002",
        "TESTPLAT_C": "tp-fake-cccc-0003",
        "TESTPLAT_UNUSED": "tp-fake-unused-0004",
    }
    write_auth(
        tmp_path,
        {
            "identities": {
                "multi": {
                    "headers": {
                        # Q5：一个 header 多个占位符；变量 A 在两个 header 中重复引用。
                        "Authorization": "Basic ${secret:TESTPLAT_A}:${secret:TESTPLAT_B}",
                        "X-Tenant-Token": "${secret:TESTPLAT_C}.${secret:TESTPLAT_A}",
                    }
                }
            }
        },
    )
    table = load_auth_table(tmp_path, "test", environ=env)
    material = table.identities["multi"]
    assert isinstance(material, StaticHeaderAuth)
    raw = _reveal_all(material.secret_values)
    referenced = ["TESTPLAT_A", "TESTPLAT_B", "TESTPLAT_C"]
    assert raw == [env[name] for name in referenced]  # 首次出现顺序、无重复
    assert len(raw) == len(set(raw))
    assert env["TESTPLAT_UNUSED"] not in raw  # 未引用的变量绝不进入
    assert _reveal_all(material.headers.values()) == [
        f"Basic {env['TESTPLAT_A']}:{env['TESTPLAT_B']}",
        f"{env['TESTPLAT_C']}.{env['TESTPLAT_A']}",
    ]
    assert all(len(value) >= 8 for value in raw)


def test_secret_values_deduplicate_equal_values_across_variables(tmp_path: Path) -> None:
    write_auth(
        tmp_path,
        {
            "identities": {
                "twin": {
                    "headers": {
                        "X-One": "${secret:TESTPLAT_ONE}",
                        "X-Two": "${secret:TESTPLAT_TWO}",
                    }
                }
            }
        },
    )
    table = load_auth_table(
        tmp_path, "test", environ={"TESTPLAT_ONE": FAKE_SECRET, "TESTPLAT_TWO": FAKE_SECRET}
    )
    assert _reveal_all(table.identities["twin"].secret_values) == [FAKE_SECRET]


def test_engine_receives_explicit_secret_values_every_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A1：Control 每次构造 StaticHeaderAuth 都显式传入非空 secret_values。"""
    calls: list[dict] = []
    real = auth_loader.StaticHeaderAuth

    def spy(**kwargs):  # noqa: ANN003
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(auth_loader, "StaticHeaderAuth", spy)
    write_auth(tmp_path, STANDARD_CONFIG)
    load_auth_table(tmp_path, "test", environ=STANDARD_ENV)
    assert len(calls) == 2
    for kwargs in calls:
        assert set(kwargs) == {"headers", "secret_values"}
        assert kwargs["secret_values"] and all(
            isinstance(item, SecretStr) for item in kwargs["secret_values"]
        )


@pytest.mark.parametrize(
    ("environ", "variable", "fragment"),
    [
        ({}, "TESTPLAT_ADMIN_TOKEN", "未设置"),
        ({"TESTPLAT_ADMIN_TOKEN": ""}, "TESTPLAT_ADMIN_TOKEN", "为空"),
        ({"TESTPLAT_ADMIN_TOKEN": "tp-7ch!"}, "TESTPLAT_ADMIN_TOKEN", "长度不足 8"),
        ({"TESTPLAT_ADMIN_TOKEN": "tp-fake\nsecret-9f31"}, "TESTPLAT_ADMIN_TOKEN", "控制字符"),
        # B2：CR 与 NUL 同样降级为不可用。NUL 无法放进真实进程环境变量，只能经 environ 映射注入，
        # 真实 Engine 矩阵因此只覆盖 CR/LF（见 docs/phase3_3/integration-real-engine.md）
        ({"TESTPLAT_ADMIN_TOKEN": "tp-fake\rsecret-9f31"}, "TESTPLAT_ADMIN_TOKEN", "控制字符"),
        ({"TESTPLAT_ADMIN_TOKEN": "tp-fake\x00secret-9f31"}, "TESTPLAT_ADMIN_TOKEN", "控制字符"),
    ],
)
def test_variable_problems_degrade_to_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    environ: dict[str, str],
    variable: str,
    fragment: str,
) -> None:
    """变量缺失/为空/过短 → UnavailableAuth（不在 Control 报错）；短值时不触发 Engine 构造。"""
    built: list[object] = []
    real = auth_loader.StaticHeaderAuth

    def spy(**kwargs):  # noqa: ANN003
        built.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(auth_loader, "StaticHeaderAuth", spy)
    write_auth(tmp_path, {"identities": STANDARD_CONFIG["identities"]})
    table = load_auth_table(
        tmp_path, "test", environ={**environ, "TESTPLAT_PARTNER_KEY": FAKE_PARTNER}
    )
    admin = table.identities["admin"]
    assert isinstance(admin, UnavailableAuth)
    assert variable in admin.public_reason and fragment in admin.public_reason
    # 只构造了 partner 一次；admin 从未进入 Engine 构造（A1：短值由 Control 先拦截）。
    assert len(built) == 1
    for value in environ.values():
        if value:
            assert value not in admin.public_reason


@pytest.mark.parametrize("variable", ["HOME", "AWS_SECRET_ACCESS_KEY", "testplat_lower"])
def test_non_whitelisted_variable_is_unavailable_and_never_read(
    tmp_path: Path, variable: str
) -> None:
    """D2 / §6-6：白名单外变量 → UnavailableAuth，原因只含变量名，值绝不被读取或外显。"""
    write_auth(
        tmp_path, {"identities": {"evil": {"headers": {"X-Key": f"${{secret:{variable}}}"}}}}
    )
    table = load_auth_table(tmp_path, "test", environ={variable: FAKE_SECRET})
    material = table.identities["evil"]
    assert isinstance(material, UnavailableAuth)
    assert variable in material.public_reason and "白名单" in material.public_reason
    assert_no_secret([material.public_reason, repr(material), repr(table)])


def test_multiple_problems_are_all_reported_by_name(tmp_path: Path) -> None:
    write_auth(
        tmp_path,
        {
            "identities": {
                "multi": {"headers": {"Authorization": "${secret:TESTPLAT_X}-${secret:TESTPLAT_Y}"}}
            }
        },
    )
    table = load_auth_table(tmp_path, "test", environ={"TESTPLAT_X": "short"})
    reason = table.identities["multi"].public_reason
    assert "TESTPLAT_X" in reason and "TESTPLAT_Y" in reason
    assert "short" not in reason


def test_default_identity_pointing_to_unavailable_identity_loads(tmp_path: Path) -> None:
    """Q7：default_identity 指向不可用身份 → 加载成功，留给 Engine 在用到时报错。"""
    write_auth(tmp_path, STANDARD_CONFIG)
    table = load_auth_table(tmp_path, "test", environ={"TESTPLAT_PARTNER_KEY": FAKE_PARTNER})
    assert table.default_identity == "admin"
    assert isinstance(table.identities["admin"], UnavailableAuth)


SCHEMA_ERRORS: list[tuple[str, object, str]] = [
    ("yaml_invalid", "identities: [unclosed\n  admin: ${secret:TESTPLAT_ADMIN_TOKEN", "YAML 无效"),
    ("root_not_mapping", "- a\n- b\n", "根节点"),
    ("empty_file", "", "根节点"),
    ("unknown_root_field", {**STANDARD_CONFIG, "secrets": {"x": 1}}, "未知字段"),
    ("missing_identities", {"default_identity": None}, "缺少 identities"),
    (
        "unknown_identity_field",
        {"identities": {"admin": {"headers": {"A": "${secret:TESTPLAT_A}"}, "token": "x"}}},
        "未知字段",
    ),
    (
        "reserved_none",
        {"identities": {"none": {"headers": {"A": "${secret:TESTPLAT_A}"}}}},
        "保留名",
    ),
    (
        "bad_identity_name",
        {"identities": {"Admin": {"headers": {"A": "${secret:TESTPLAT_A}"}}}},
        "身份名",
    ),
    ("empty_headers", {"identities": {"admin": {"headers": {}}}}, "非空对象"),
    (
        "bad_header_name",
        {"identities": {"admin": {"headers": {"Bad Header": "${secret:TESTPLAT_A}"}}}},
        "非法 header 名",
    ),
    (
        "case_duplicate_header",
        {
            "identities": {
                "admin": {
                    "headers": {
                        "Authorization": "${secret:TESTPLAT_A}",
                        "authorization": "${secret:TESTPLAT_B}",
                    }
                }
            }
        },
        "仅大小写不同",
    ),
    (
        "template_without_secret",
        {"identities": {"admin": {"headers": {"X-Tenant": "tenant-001"}}}},
        "至少包含一个",
    ),
    (
        "other_placeholder",
        {"identities": {"admin": {"headers": {"A": "${secret:TESTPLAT_A}${env:HOME}"}}}},
        "只允许",
    ),
    ("non_string_template", {"identities": {"admin": {"headers": {"A": 12345678}}}}, "字符串"),
    (
        "default_identity_missing",
        {**STANDARD_CONFIG, "default_identity": "ghost"},
        "不存在的身份: ghost",
    ),
    ("default_identity_bad_type", {**STANDARD_CONFIG, "default_identity": ["admin"]}, "合法身份名"),
]


@pytest.mark.parametrize(
    ("content", "fragment"),
    [(content, fragment) for _, content, fragment in SCHEMA_ERRORS],
    ids=[name for name, _, _ in SCHEMA_ERRORS],
)
def test_schema_errors_raise_invalid_environment_without_secret(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, content: object, fragment: str
) -> None:
    """配置层错误：直接 InvalidEnvironmentError（preflight）；消息与日志不含秘密（M1）。"""
    write_auth(tmp_path, content)  # type: ignore[arg-type]
    environ = {
        **STANDARD_ENV,
        "TESTPLAT_A": FAKE_SECRET,
        "TESTPLAT_B": FAKE_PARTNER,
        "HOME": FAKE_SECRET,
    }
    with caplog.at_level(logging.DEBUG), pytest.raises(InvalidEnvironmentError) as info:
        load_auth_table(tmp_path, "test", environ=environ)
    exc = info.value
    assert exc.stage == "preflight" and exc.kind == "invalid_environment"
    assert fragment in exc.public_message
    assert_no_secret(
        [exc.public_message, exc.log_reason, str(exc), repr(exc), *log_text(caplog.records)]
    )
    # YAML 错误不保留原始异常链（其文本含出错行片段）。
    assert exc.__cause__ is None


def test_logs_only_contain_names(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    write_auth(tmp_path, STANDARD_CONFIG)
    with caplog.at_level(logging.DEBUG, logger="testplat_control"):
        load_auth_table(tmp_path, "test", environ={"TESTPLAT_ADMIN_TOKEN": FAKE_SECRET})
    text = log_text(caplog.records)
    joined = "\n".join(text)
    assert "identity=admin" in joined and "TESTPLAT_PARTNER_KEY" in joined
    assert_no_secret(text)
