# 场景 0.3 独立复审（2026-10-20）

结论：**未通过，停止交付。** 用户授权以审查通过为前提；本轮没有提交、推送、修改版本/依赖锁或启用 Assets，不部署、不执行真实业务。两项原断言问题已修复，但独立复核发现三项新缺口。

## 基线与范围

- Engine `a4d9500c1fa41c80595e3b4812c92586b9864b0f`
- Control `35f4e26e71106b7be4985a5a92543e27699f402d`
- Assets `c41e987caaf5d85b7803eeefc17d35d250a11d25`

以上均为 main。比较固定 HEAD 与工作区修改，并逐一包含未跟踪候选；普通 git diff 无法覆盖新增 Engine 场景模块。规格来源为 CONTEXT、SOP、ADR-003 至 ADR-008、核心场景设计、Engine schema 文档和验收交接。本轮使用 code-review 技能的两个独立代理，分别审查 Standards/Spec；主代理独立复现三项 Spec 发现。Control 用户文件 PHASE2_3_REVIEW_REPORT.md 不参与提交清单；既有预览、数据库和凭据未触碰。

## Standards

未发现新增、已确认的硬性规范或安全阻断。旧 Case 0.2 入口保留，新执行复用 ApiStepExecutor；Control 展示 Engine 契约。测试使用隔离资产、临时数据库或本机假服务。

已知交付门槛仍在：Engine 元数据与公开版本仍为 0.5.2；Control 锁旧 Engine 提交且启动检查尚不要求 describe_case。只有 Spec 审查通过后才进入版本与依赖门槛升级切片。

提交边界需注意：ProjectWorkspacePage.tsx 的 DEV lazy import/render 依赖未跟踪 ScenarioWorkbenchPrototype.tsx/.css。若排除原型，提交树须同时排除关联 hunks，保留用户工作区原文件并独立构建；不能只漏掉依赖文件。

判断性建议：scenario.py 加载、预检、执行反复按类型分支，存在 Repeated Switches 维护成本；不要求本轮为此重构。

本轴：硬性缺陷 0，非阻断维护建议 1；版本门槛和提交边界须交付前落实。

## Spec

1. **P1：合法 map 动态绑定触发内部错误。** Engine `src/testplat_engine/engine/scenario.py:773` 在 source 已知时立即解析全部 params，没有处理前序响应的未知占位。最小组合：fetch API 输出 fetch，map.source=`${params.rows}`（已知非空数组），map.params.value=`${fetch.body.echo}`。describe_case 接受；execute 在零请求时抛 EngineInternalError。核心设计第176行要求未来响应字段延迟检查；应保留已知字段检查并在响应产生后完成所有迭代预检。

2. **P1：已知 flow 输出缺失在副作用之后才失败。** `_preflight` 未检查 definition.outputs；只在 `scenario.py:1227` 的运行末尾解析。flow.inputs.value 为 `{present: true}`，outputs.value=`${inputs.value.missing}`，flow 内一个 echo API。describe_case 接受；主代理确认发送一次假请求后才以 variable_resolution 失败。核心设计第176行要求任何请求前检查输入/输出及已知参数；依赖已知输入的输出路径应提前校验，响应依赖仍延迟。

3. **P2：嵌套 expected 绕过描述阶段引用校验。** `scenario.py:338` 仅在 expected 为字符串时收集引用。expected=`{nested: '${inputs.undeclared}'}` 或 `['${future.body}']` 时，未声明 flow 输入或前向 alias 被 describe_case 接受；执行却递归解析这些引用。违反核心设计第112行要求未知字段或引用明确拒绝，Assets 复用描述入口也会漏检。应递归检查 expected 的所有引用。

本轴：缺陷 3（P1 两项、P2 一项），本轮不放行。

## 验证与限制

本轮重新执行：

| 检查 | 结果 | 依赖与隔离范围 |
| --- | --- | --- |
| Engine `uv run pytest -q` | 570 passed | 当前 Engine 源码，既有隔离测试 |
| Control `bash scripts/dev.sh pytest -q tests ../testplat-assets/tests` | 488 passed，13 项既有警告 | 显式本地 Engine 覆盖，不是正式远程锁验证 |
| 前端 `npm test -- --run` | 211 passed / 29 files | 本地候选 |
| 前端 `npm run lint` / `npm run build` | 通过 | 既有 bundle 大小提示 |
| 三仓 `git diff --check` | 通过 | 不覆盖未跟踪文件内容审查 |
| 新发现复现 | 三项均确认 | 临时资产与 loopback 假服务，无真实业务 |

全量测试通过说明既有覆盖通过，不能否定本轮已复现的未覆盖缺陷。之前审查构建的 0.5.2 wheel 也不能代表修复后的全新远程交付。没有访问真实 GO2、没有真实订单或 WAIT_PAY 验收。

## 下一切片

先修复三项 Spec 缺陷并加入真实调用模式的回归：已知 source + 动态 map 参数、请求前已知 flow 输出缺失、递归 expected 中未声明/前向引用。补充合法动态路径仍能执行的正向证据，并重跑 Engine/Assets 隔离测试和复审。之后才推进唯一新版本、Control 能力门槛、Engine 提交/推送、Control 精确 SHA 与生成锁的干净安装验证、Assets 清单启用。用户原条件授权仍有效，但本轮未满足通过条件。
