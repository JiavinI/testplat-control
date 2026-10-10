# testplat-control 前端

React + TypeScript + Ant Design 控制台。当前覆盖：项目 CRUD、只读资产浏览、单 API 执行、执行历史与详情。

## 技术栈

- Vite + React 19 + TypeScript（严格模式）
- Ant Design 5（工具台风格；入口通过 `unstableSetRender` 兼容 React 19）
- React Router、TanStack Query
- pnpm、ESLint、Vitest、Testing Library

## 开发

```bash
pnpm install
pnpm dev
```

默认通过 Vite 代理将 `/api/*` 转发到 `http://127.0.0.1:8000`（去掉 `/api` 前缀），避免 CORS。

环境变量见 `.env.example`：

- `VITE_API_BASE_URL`：浏览器侧 API 前缀（开发默认 `/api`）
- `VITE_DEV_PROXY_TARGET`：开发代理目标

后端需在本机 `8000` 端口启动；资产与配置路径在创建项目时填写（可用仓库内 `tests/fixtures/assets` 与 `tests/fixtures/config`）。

完整的单 API 执行还要求后端能够加载 sibling `testplat-engine`，或由验收 harness 显式注入 `FakeEngineAdapter`。缺少 Engine 时，项目 CRUD 和资产浏览仍可用，但执行接口会返回 500。FakeEngine 的替换 seam 与排查方式见 [`../README_INTEGRATION_TESTS.md`](../README_INTEGRATION_TESTS.md)。

## 脚本

```bash
pnpm lint
pnpm test --run
pnpm build
# 浏览器门禁：先启动可执行 API 的后端（真实 Engine 或 FakeEngine harness）和 5173 前端
node scripts/e2e-gate.mjs
```

## 目录约定

- `src/app/`：应用壳、路由、QueryClient、主题
- `src/shared/`：API client、错误模型、运行时结构校验、DTO、通用 UI
- `src/features/projects/`：项目 API / hooks / 表单与表格
- `src/features/assets/`：资产树浏览与详情
- `src/features/executions/`：参数表单、单次执行、执行历史
- `src/pages/`：项目列表页与项目工作台页

## 验收截图

- Phase 2.1 冒烟：`screenshots/`（空态→创建→工作台→编辑→删除）
- Phase 2.4 联调：`screenshots/phase2-4/`（桌面 `1440x900` 与移动 `390x844`）
