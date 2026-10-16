# 接口工作区增量与验收

日期：2026-10-16（Asia/Shanghai）。基于现有四功能导航、Web 环境/账号和已跑通的 GSB 登录实现继续推进。

## 本轮行为

- 左侧延续只含 `api/` 的独立接口树，显示接口业务名称和 HTTP 方法；可按业务名称、文件名、路径或 ID 过滤。
- 详情突出名称、方法、路径和鉴权引用；接口 ID、文件路径及完整源定义收进「接口源定义」。API 请求定义优先从详情读取。
- 右上选择启用的 Web 环境。完整 URL 使用该环境 `api_hosts[host]` 去尾部斜杠后拼接接口路径，与当前 Engine 一致；Query 内容在请求区展示，发送后的参数在实际请求快照查看。缺少服务映射时提示配置入口，并禁用运行。
- 请求区明确区分 Query、JSON、Form、Raw。模板模式展示源请求内容和模板参数；临时编辑可增删完整 body 字段，并从 YAML 恢复。Query/Form 通过 JSON 对象编辑，限一层标量键值；Raw 是原始文本；JSON 显式 null 恢复后保持 null。
- 运行结果默认展示业务判定、HTTP 状态、耗时、环境及响应体；可切换响应头、实际请求。「运行详情与登录过程」和执行历史按需展开；历史仍使用原记录详情能力。
- 组件按项目、接口、环境重新挂载，清空临时内容、表单、错误和运行结果。再次运行先清除上一轮结果，避免把旧响应误当作新响应。

临时编辑仍只覆盖请求内容，不改变 method、host、auth、headers 或断言，不写回 Assets。Page 执行、场景编排、测试数据、套件及源定义保存未扩展。

## 变更边界

本轮在 Control 中新增 `ApiInfoPanel.tsx`、`ApiRunResult.tsx`，调整 `ProjectWorkspacePage.tsx`、`ApiExecutionPanel.tsx`、`types.ts`、`AssetTree.tsx`、`treeUtils.ts` 和少量 URL 样式。补充相关已有前端测试、新浏览器脚本及本地 Engine wheel 校验脚本。开始本轮前的未提交账号、导航、运行契约与凭据实现全部保留；用户 `PHASE2_3_REVIEW_REPORT.md` 未覆盖。Engine、Assets 本轮没有代码改动。

## 验收证据

| 验证 | 结果及边界 |
| --- | --- |
| Engine 全量 | 429 项通过；隔离 uv 环境 |
| Control 全量 | 379 项通过；导入应用前强制内存测试库 |
| 本地 Engine wheel → Control 假服务集成 | 19 项通过；实际从 site-packages 导入，非 editable |
| 相关前端 | 42 项通过，含 URL、缺失 host、环境/接口草稿清空、Query 标量校验、Raw、JSON null、HTTP 200 业务失败、历史详情和导航 |
| 浏览器隔离 mock | 1440 桌面、390 窄屏通过；独立 API 树、完整 URL、JSON/Query 临时覆盖、响应页签、环境/项目切换、缺 host 和抽屉；页面错误 0 |
| 真实余额 | 从预览库只读 backup 制作受保护临时副本，同时复制 Git 快照并配置空同步列表，独立后端/前端端口与平台会话；通过新页面临时 body `{}` 连续运行两次，均 HTTP 200、`errorCode: "0"`，首次 `login`、第二次 `cache`，页面错误 0 |
| Assets 静态校验 | 接口、场景引用、登录 profile schema 与环境模板通过；静态校验不代表真实业务通过 |
| build / lint / diff | 通过；构建仍有现有的大 bundle 提示 |

真实余额记录 `3babfe43-e232-4d25-b6ef-c4bd12a05025`、`a3632726-51b8-46bb-b73d-39dfed47c41b` 仅存在于已删除的隔离测试库，不会出现在原预览历史。测试后数据库副本、临时平台会话、临时服务、私有日志均随临时目录清理；原预览数据库主文件 SHA-256 比较相同，未覆盖环境、凭据或主密钥。

本次浏览器 mock 截图和报告在 `/tmp/testplat-api-workspace/`，截图明确使用「隔离验收」项目和「隔离模拟响应」，不能作为真实 GSB 响应证据。真实余额报告只保留状态、业务码和缓存来源，不含密码、Cookie、token 或主密钥；临时目录内容不保证永久保留。

## 复验入口

在 Control 的 frontend 目录：

```sh
npm test -- --run src/pages/ProjectWorkspacePage.test.tsx src/pages/FeatureWorkspacePage.test.tsx src/features/executions/ApiExecutionPanel.test.tsx src/features/assets/AssetBrowser.test.tsx
npm run lint
npm run build
node scripts/e2e-api-workspace.mjs
```

浏览器脚本需要已有前端服务（默认 `http://127.0.0.1:5173`，可用 `E2E_BASE_URL` 指定）。全部 `/api/` 请求在浏览器中拦截，未知接口直接中断，不请求预览后端、不注册真实账号、不修改数据库。可用 `E2E_OUT_DIR` 指定截图/报告目录。

本地 wheel 复验和 Engine → Control 远程交付方案见 [local-engine-delivery-2026-10-16.md](local-engine-delivery-2026-10-16.md)。Control 的旧远程 Engine 锁定尚未更新；没有进行远程推送、合并、标签发布或部署。

## 仍待验收

`api.gsb.order.search_product` 本轮只完成 Query 编辑交互及 Assets 静态校验，真实搜索请求和业务结果仍未验收。`case.gsb.smoke` 的完整两步场景仍未真实验收。下一轮按交接 P2，先确认非秘密搜索词与业务返回，再逐项验证场景参数覆盖、缓存复用与历史详情。
