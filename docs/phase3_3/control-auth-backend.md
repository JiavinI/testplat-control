# Phase 3.3a Control 后端：静态 header 凭证

权威设计：`notes/phase3.3-auth-design-draft.md`（D1–D6、§6.1、§6.2）。Engine 依赖：远程精确锁定 `8564040`（v0.3.0，https://github.com/JiavinI/testplat-engine.git main；内容由已审查的 `f631e2e` 合并而来）。

## 配置

`{config_root}/auth/{env}.yaml`（入 git，**不含秘密**）：

```yaml
identities:
  admin:
    headers:
      Authorization: "Bearer ${secret:TESTPLAT_ADMIN_TOKEN}"
  partner:
    headers:
      X-Api-Key: "${secret:TESTPLAT_PARTNER_KEY}"
default_identity: admin   # 可选
```

秘密只来自 Control 进程环境变量，变量名必须匹配 `^TESTPLAT_[A-Z0-9_]+$`。本地 `.env*` 已加入 `.gitignore`。

| 情况 | 结果 |
|---|---|
| 文件不存在 | `auth=None`，与 Phase 3 一致 |
| YAML 非法 / 未知字段 / 身份名非法或为 `none` / header 名非法或同一身份内仅大小写不同 / 模板不含 `${secret:}` 或含其它占位符 / `default_identity` 指向不存在的身份 | 加载即 422（`invalid_environment`，不写记录） |
| 变量不在白名单 / 未设置 / 为空 / 短于 8 / 含换行或 NUL | 该身份为 `UnavailableAuth`，被用到时由 Engine 报 422；未用到不影响 |

`StaticHeaderAuth.secret_values` 总是显式传入该身份模板引用的全部变量原始值（按首次出现顺序、按值去重）。

## 公开契约（相对 Phase 3 的 OpenAPI 差异：`openapi-diff-vs-phase3.diff`）

- 新 schema `ExecutionAuth {identity, header_names, overridden_headers}`。
- `RunResponse.auth`、`ExecutionRecordDetailResponse.auth`、`CaseStepResult.auth`：`ExecutionAuth | null`。
- 路由不变；完整文档 `openapi-phase3_3.json`；示例见 `examples/`：成功响应由 Fake Engine 生成；`auth-error-responses.json` 已由 Agent 4 用真实 Engine（`f631e2e`）重新生成（B5），见 `integration-real-engine.md`。
- 请求 DTO 构造失败的 422 detail 改为固定文案 `执行请求无效：参数或环境配置不合法`（不再回显 `str(exc)`）。
