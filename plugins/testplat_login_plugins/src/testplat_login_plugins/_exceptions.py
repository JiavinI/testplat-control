"""vcode_redis 业务失败异常。

全部继承 ``Exception``（不继承内置 ``ConnectionError`` / ``TimeoutError``），
以便 Engine 归类为 ``strategy_error``；公开面只出现类型名。
消息不含验证码、uuid、密码、host 或 Redis key。
"""


class VcodeCreateFailed(Exception):  # noqa: N818 — 设计稿公开类型名
    """createVCode 响应状态码 ≥ 400。"""


class VcodeUuidMissing(Exception):  # noqa: N818 — 设计稿公开类型名
    """createVCode 响应缺少 uuid 路径。"""


class VcodeCodeMissing(Exception):  # noqa: N818 — 设计稿公开类型名
    """Redis 中验证码 key 不存在或值为空。"""


class VcodeLoginFailed(Exception):  # noqa: N818 — 设计稿公开类型名
    """登录响应状态码 ≥ 400。"""


class VcodeTokenMissing(Exception):  # noqa: N818 — 设计稿公开类型名
    """登录响应缺少 ``extract.token`` 路径。"""


class VcodeConnectionMissing(Exception):  # noqa: N818 — 设计稿公开类型名
    """``params.redis_connection`` 指向的连接不存在。"""
