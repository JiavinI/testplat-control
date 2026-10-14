"""秘密取值的唯一入口。

不变量：``SecretStr.reveal()`` 只允许出现在本模块（AST 测试约束）。
其它模块必须经 ``reveal_value`` 取连接密码与 ``field.*`` 等秘密参数。
"""

from __future__ import annotations

from testplat_engine import SecretStr


def reveal_value(value: object) -> str:
    """把 ``str | SecretStr`` 变成明文；其它类型转成字符串。

    调用方负责不把返回值写入日志、异常消息或公开记录。
    """
    if isinstance(value, SecretStr):
        return value.reveal()
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)
