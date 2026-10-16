# 功能导航与项目上下文

2026-10-16：功能作为一级入口，项目作为功能内部的选择范围。

| 菜单 | 路由 | 资产与能力 |
| --- | --- | --- |
| 接口管理 | `/apis/{repo}/{project}` | 只展示 `api/`，调试运行与接口历史 |
| Page 管理 | `/pages/{repo}/{project}` | 只展示 `pages/`，当前为只读浏览 |
| 场景测试 | `/scenarios/{repo}/{project}` | 展示 `scenarios/` 与 `flows/`，场景运行与场景历史 |
| 配置 | `/configuration/{repo}/{project}` | 项目配置文件、环境管理、测试账号 |

项目选择写入 URL，并记住最近选择。切换功能保留项目，切换项目清空选中的资产、运行面板与配置草稿。配置内切换项目保留当前页签。项目不存在或尚未同步时提供明确空态，不借用其它项目的数据。

配置页签可通过 `?tab=environments`、`?tab=accounts` 直接打开；运行页的「去配置」跳转到同一项目的环境页签。配置文件展示资产快照中的 `config/`；环境与账号沿用数据库维护，供运行时冻结解析。旧工作台内的配置折叠区已移除。

仓库同步入口是「配置 → 仓库同步」（`/configuration/repositories`）。旧 `/projects` 跳转到接口管理；旧 `/projects/{repo}/{project}` 仍可打开对应项目的接口管理。

开发代理精确匹配 `^/api(?:/|$)`，避免将 `/apis` 前端页面当成后端请求。生产静态服务也应将 `/api/` 与 SPA 路由分别处理。

## 本地验证

- 54 项导航、工作台、资产树、项目来源、登录与历史回归通过；22 项环境与账号表单回归通过。
- 前端 build、lint、diff 检查通过。
- 浏览器覆盖 1440 桌面和 390 窄屏：四个菜单、资产隔离、配置页签、抽屉、页面错误数 0。
- 从新入口运行 `api.gsb.account.balance` 成功，记录 `0e4f9f7c-9985-414c-b3ac-3d2258eff5f1`。沿用当前本地 Engine 覆盖环境，账号与配置未修改。
- 浏览器回归脚本：`frontend/scripts/e2e-feature-navigation.mjs`。截图和报告：`/tmp/testplat-feature-navigation/`。
