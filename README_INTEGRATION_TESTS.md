# 集成测试

这条链路覆盖控制面的一次完整 API 执行：创建项目、读取资产树、取出参数表单、执行接口、列出并查看执行记录。测试只使用本仓库里的资产，不依赖仓库外的 `test_assets`。

资产在 `tests/fixtures/assets`，环境配置在 `tests/fixtures/config/test.yaml`。用例在 `tests/integration/test_api_execution_flow.py`。

## 如何运行

在仓库根目录安装开发依赖后执行：

```bash
pip install -e ".[dev]"
pytest tests/integration -q
```

只跑整条主流程：

```bash
pytest tests/integration/test_api_execution_flow.py::test_full_api_execution_flow -q
```

全量测试（含单元测试）：

```bash
pytest -q
```

看这组用例碰到了哪些路由代码：

```bash
pytest tests/integration --cov=testplat_control.api --cov=testplat_control.services --cov=testplat_control.parsers --cov-report=term-missing
```

## 覆盖范围

| 用例 | 行为 |
| --- | --- |
| `test_full_api_execution_flow` | 建项目 → 资产树 → 参数表单 → 执行 → 列表 → 详情 |
| `test_execution_with_invalid_params` | 缺必填、类型错误、未知参数返回 422，且不写记录 |
| `test_execution_record_filtering` | 按 `status`、`asset_id` 过滤，默认按开始时间倒序 |
| `test_multiple_executions` | 同一接口连续执行产生多条记录 |
| `test_execution_failure_handling` | 引擎返回失败时 HTTP 仍为 200，记录状态为 `failed` |
| `test_concurrent_executions` | 五个并发请求各自留下一条成功记录 |

`assert_execution_record(record, expected_status)` 检查状态、记录 ID、资产 ID、开始时间和非负耗时。详情还会检查解析后的 `result.status` 和 `display`。

登录接口 `api.user.login` 的 `password` 为 `wrong-password` 时，替身引擎返回失败。其他参数合法的调用返回成功。

## 依赖

开发额外依赖见 `pyproject.toml` 的 `[project.optional-dependencies] dev`：

- `pytest`
- `pytest-asyncio`（这组用例本身是同步测试，并发用例内部使用 `asyncio.run`）
- `httpx`（`AsyncClient` 发并发请求，`TestClient` 走其余请求）
- `pytest-cov`（只在查看覆盖率时需要）

运行时依赖是 FastAPI、SQLAlchemy、Pydantic、PyYAML。不需要安装 sibling 仓库 `testplat-engine`。`tests/conftest.py` 会在引擎缺失时放入最小桩；集成测试另外把 `EngineAdapter` 换成 `FakeEngineAdapter`，因此结果稳定，也不会访问真实网络。

数据库用的是应用启动时的共享内存 SQLite（`StaticPool`）。每个用例创建自己的项目，记录按 `project_id` 隔离。

## 排查

- **资产 404**：项目的 `assets_root` 必须是 `tests/fixtures/assets`。资产 ID 来自目录，例如 `api/user/login.yaml` 对应 `api.user.login`。
- **参数 422**：`password` 在登录接口上必填；`username` 和 `email` 在创建用户接口上必填且必须是字符串。未在 YAML `inputs` 里声明的字段会被拒绝。
- **执行 500**：说明请求打到了真正的 `EngineAdapter`，而本机没有 `testplat-engine`。确认测试启用了 `engine` fixture，替身挂在 `testplat_control.api.run.EngineAdapter`。
- **列表是空的**：执行若返回 422，记录不会写入。先看执行响应的 `status`，再用同一个 `project_id` 查询。
- **全量 `pytest` 里有 skip**：`tests/test_asset_service.py` 和部分 YAML 解析用例依赖仓库外的 `testplat1/test_assets`。目录不存在时会跳过。集成测试不使用那个目录。
- **并发用例失败**：它通过一个事件循环同时发出请求，并在替身里短暂等待，让请求重叠。不要改成多个进程共享这个内存库。
