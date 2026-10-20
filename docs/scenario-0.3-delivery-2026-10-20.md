# 场景 schema 0.3 三仓分支交付

日期：2026-10-20。用户授权修复引用/预检问题、复审通过后继续必要本地提交、三仓分支推送、Control 精确锁及 Assets 启用。主线合并、标签、发布包、部署及真实业务操作未包含在本次交付。

## 修复与复审

已知 map source 与动态绑定组合的内部错误、已知 flow 输出缺路径在业务请求后暴露、嵌套 assert.expected 引用绕过加载校验，均先补回归再修复。复审额外发现嵌套 flow 整体透传混合对象会丢失已知字段：新增正反例先运行 1 failed/1 passed，修复后缺路径 InvalidInputError 且 0 请求，合法混合对象仍完整输出。专项 12 passed，Engine 全量 582 passed。

修复两轴复审均放行。Standards 硬性问题 0、非阻断判断性气味 1（预检路径遍历与既有查找少量重复）；Spec 0。交付 delta 再次独立复审：Standards 硬性 0、非阻断气味 1（GSB API 副本维护的明确权衡）；Spec 0。原发现与放行证据保存在 workspace-records/docs/reviews。

## 交付顺序与内容

1. Engine：版本 0.6.0；场景集中参数、flow/map、extract、Decimal、assert、transform、公开 describe_case 与递归 trace。旧 Case 0.2 保持原严格规则。提交 bddb200a7e21804db0a6032e35c635b977168caf 已推送至 codex/scenario-0-3-delivery。
2. Control：版本要求 >=0.6.0,<0.7，公开 describe_case 必须可调用。pyproject.toml 与 uv 生成锁精确指向上述真实远程 SHA，仅 Engine 来源与版本变化。展示七种节点的定义、来源、执行证据与嵌套历史，沿用既有参数保存和请求契约。
3. Assets：GO2 的 gsb.assets 指向 projects/gsb_go2；保留全部原 API 与旧 smoke，加入已验证的 1 case/3 flow。原配置仍在 projects/gsb/config；E3E3 保持 projects/gsb 与自己的配置。清单仍为 10 工作区。

Control 当前按资产根扫描 case，没有 case 项目过滤。独立 GO2 目录防止建单入口出现在 E3E3；GSB API 副本须同步维护，回归测试检查路径和逐字内容一致。参数集按稳定的 repo/project key、asset_type/id、scope/env_key 保存，未使用 assets 路径作为身份，所以 gsb 标识与原 API ID 保留时既有参数集身份不变。未复制环境、登录配置或凭据到新目录。

## 验证证据

- Engine 从提交的干净 git archive 构建 sdist→wheel，确认五个 scenario 模块入包。隔离安装 wheel 后模块来自 site-packages，包/模块版本 0.6.0、describe_case 可调用；全量 582 passed。ruff check/format 通过。
- Control 从真实远程 SHA 隔离 locked 安装，未使用相邻 Engine、PYTHONPATH 或 editable 覆盖；模块来源 site-packages，启动兼容检查返回 0.6.0。Control+Assets 初次全量 495 passed（收集时 Assets 65 项）。
- 资产启用前新增 3 项测试均预期失败；启用后及动态测试分别覆盖 candidate/active，Assets 全量 95 passed。检查 GO2 可见、E3E3 不可见、原配置/接口/smoke 保留；所有业务调用使用 MockTransport。
- 正式精确锁下静态验证：10 个清单工作区、go2-pending 和 scenario-parameters 两示例 ALL PASSED；仅加载/描述，无业务请求。
- 前端全量 211 passed，lint/build 通过；保留既有 bundle 体积提示。12 个改动 Python 文件 ruff check/format 通过。
- 正式精确锁下隔离浏览器：成功 8 次假请求；第二项 SKU 缺失 2 次；金额不符 8 次且只创建一次。三分支均验证嵌套证据、刷新历史、390px 无横向溢出、页面异常 0。临时内存库、虚构静态头账号和 MockTransport，验收后自动清理；原预览未修改。

## 复现

在配套 Control 目录运行：

```sh
uv run --isolated --locked --extra dev --no-editable pytest -q tests ../testplat-assets/tests
uv run --isolated --locked --extra dev python ../testplat-assets/scripts/validate.py
uv run --isolated --locked --extra dev python ../testplat-assets/scripts/validate.py --candidate go2-pending
uv run --isolated --locked --extra dev python scripts/verify_pending_workspace.py
cd frontend
npm test -- --run
npm run lint
npm run build
```

没有真实 GO2 下单、WAIT_PAY 状态或支付验收。原预览、数据库、账号、密钥及用户 PHASE2_3_REVIEW_REPORT.md 保留。分支推送及干净副本最终验证结果将在完成后追加；历史主线交付文档不代表本次主线已更新。
