# testplat-control 前端

React + TypeScript + Ant Design 控制台，覆盖 MVP 项目管理（列表 / 创建 / 编辑 / 删除 / 工作台骨架）。

## 技术栈

- Vite + React + TypeScript（严格模式）
- Ant Design（克制紧凑的测试工具风格）
- React Router、TanStack Query
- pnpm、ESLint、Vitest、Testing Library

## 开发

```bash
# 需已启用 pnpm
pnpm install
pnpm dev
```

默认通过 Vite 代理将 `/api/*` 转发到 `http://127.0.0.1:8000`（去掉 `/api` 前缀），避免 CORS。

环境变量见 `.env.example`：

- `VITE_API_BASE_URL`：浏览器侧 API 前缀（开发默认 `/api`）
- `VITE_DEV_PROXY_TARGET`：开发代理目标

## 脚本

```bash
pnpm lint
pnpm test --run
pnpm build
```

## 目录约定

- `src/app/`：应用壳、路由、QueryClient
- `src/shared/`：API client、错误模型、DTO、通用 UI
- `src/features/projects/`：项目 API / hooks / 表单与表格
- `src/pages/`：页面（工作台仅为空集成容器）

本阶段不实现 `features/assets` 与 `features/executions`。

## 验收截图

本地 Playwright 冒烟截图保存在 `screenshots/`（空态→创建→工作台→编辑→删除）。
