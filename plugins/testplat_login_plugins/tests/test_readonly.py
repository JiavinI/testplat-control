"""只读：fake 客户端方法名；本机有 redis-server 时跑真实 GET + commandstats。"""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
from testplat_engine import ApiExecutionRequest, create_engine

from support import (
    CAPTCHA_4,
    ENV,
    FAKE_UUID,
    KEY_PREFIX,
    FakeTarget,
    assert_no_secrets,
    assets_root,
    engine_for,
    make_auth,
)
from testplat_login_plugins.vcode_redis import VcodeRedisStrategy

# Redis INFO commandstats 中视为写命令的前缀（小写）。
_WRITE_CMD_PREFIXES = (
    "cmdstat_set",
    "cmdstat_setex",
    "cmdstat_setnx",
    "cmdstat_mset",
    "cmdstat_del",
    "cmdstat_hset",
    "cmdstat_lpush",
    "cmdstat_rpush",
    "cmdstat_sadd",
    "cmdstat_zadd",
    "cmdstat_incr",
    "cmdstat_decr",
    "cmdstat_append",
    "cmdstat_expire",
    "cmdstat_flush",
    "cmdstat_rename",
)


async def test_fake_redis_only_get_and_aclose() -> None:
    target = FakeTarget()
    auth, fake_redis = make_auth()
    d = (
        await engine_for(target, fake_redis).execute(
            ApiExecutionRequest(
                api_id="api.vcode.echo",
                assets_root=assets_root(),
                environment=ENV,
                params={},
                auth=auth,
            )
        )
    ).to_dict()
    assert d["status"] == "success"
    assert fake_redis.calls == ["get", "aclose"]
    assert_no_secrets(target, d)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def redis_server():
    """起临时端口的 redis-server；没有二进制则 skip。"""
    binary = shutil.which("redis-server")
    if not binary:
        pytest.skip("本机无 redis-server，跳过真实 Redis 只读测试")
    port = _free_port()
    work = Path("/tmp/testplat-vcode-redis-test")
    work.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [
            binary,
            "--save",
            "",
            "--appendonly",
            "no",
            "--port",
            str(port),
            "--bind",
            "127.0.0.1",
            "--dir",
            str(work),
            "--dbfilename",
            f"dump-{port}.rdb",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # 等待就绪
    deadline = time.time() + 5
    import redis as redis_sync

    while time.time() < deadline:
        try:
            client = redis_sync.Redis(host="127.0.0.1", port=port, socket_connect_timeout=0.2)
            client.ping()
            client.close()
            break
        except Exception:
            time.sleep(0.05)
    else:
        proc.kill()
        pytest.skip("redis-server 未能在超时内就绪")
    yield port
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


async def test_real_redis_get_and_no_writes(redis_server: int) -> None:
    """真实 GET；CONFIG RESETSTAT 后断言 commandstats 无写命令。"""
    import redis as redis_sync

    port = redis_server
    key = f"{KEY_PREFIX}{FAKE_UUID}"
    writer = redis_sync.Redis(host="127.0.0.1", port=port, decode_responses=True)
    try:
        writer.set(key, CAPTCHA_4)
        writer.execute_command("CONFIG", "RESETSTAT")
    finally:
        writer.close()

    target = FakeTarget()
    auth, _ = make_auth(captcha_in_redis=None)
    # 覆盖连接为临时端口、无密码
    assert auth.connections is not None
    # AuthTable.connections 是 MappingProxyType，需重建
    from testplat_engine import AuthTable, LoginAuth

    material = auth.identities["df_admin"]
    assert isinstance(material, LoginAuth)
    auth2 = AuthTable(
        identities={"df_admin": material},
        connections={
            "redis_main": {
                "host": "127.0.0.1",
                "port": port,
                "database": 0,
            }
        },
    )

    strategy = VcodeRedisStrategy()  # 真实 redis.asyncio.Redis
    engine = create_engine(login_strategies=[strategy])
    engine._client_factory = target.factory  # noqa: SLF001
    d = (
        await engine.execute(
            ApiExecutionRequest(
                api_id="api.vcode.echo",
                assets_root=assets_root(),
                environment=ENV,
                params={},
                auth=auth2,
            )
        )
    ).to_dict()
    assert d["status"] == "success", d.get("error")

    checker = redis_sync.Redis(host="127.0.0.1", port=port, decode_responses=True)
    try:
        stats = checker.info("commandstats")
    finally:
        checker.close()

    [k for k in stats if k.lower().startswith(_WRITE_CMD_PREFIXES) and stats[k]]
    # commandstats 值是字典；只要出现写命令键且 calls>0 即失败
    offenders = []
    for key_name, meta in stats.items():
        low = key_name.lower()
        if any(low.startswith(p) for p in _WRITE_CMD_PREFIXES):
            calls = meta.get("calls", 0) if isinstance(meta, dict) else 0
            if calls:
                offenders.append(key_name)
    assert not offenders, f"Redis 出现写命令: {offenders}"
    # 至少有一次 get
    get_meta = stats.get("cmdstat_get") or {}
    assert isinstance(get_meta, dict) and get_meta.get("calls", 0) >= 1
    assert_no_secrets(target, d)
