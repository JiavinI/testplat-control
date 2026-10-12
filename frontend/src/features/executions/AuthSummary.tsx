import { Space, Tag, Typography } from 'antd'
import type { AuthDisplayMode } from './auth'
import type { ExecutionAuth } from './types'

export type AuthSummaryProps = {
  auth: ExecutionAuth | null
  mode: AuthDisplayMode
  /** 测试 / 门禁定位用，同一页可能有多处（单 API、每个 Case 步骤）。 */
  testId?: string
}

/**
 * 身份展示：“身份：admin” / “匿名” / “—”，可展开查看注入与被覆盖的 header 名。
 * 只渲染名字：auth 本身就只有名字，这里也不从 request.headers 取任何值，
 * 因此 DOM 中不可能出现凭证值；本组件也不提供任何秘密录入入口（设计稿 §3 非目标）。
 */
export function AuthSummary({ auth, mode, testId = 'auth-summary' }: AuthSummaryProps) {
  if (mode === 'not_applicable' || (mode === 'identity' && !auth)) {
    // 未发出请求：身份不适用，用“—”而不是“匿名”，避免误导为匿名执行
    return (
      <Typography.Text type="secondary" data-testid={testId} data-auth-mode="not_applicable">
        —
      </Typography.Text>
    )
  }
  if (mode === 'anonymous' || !auth) {
    return (
      <Tag data-testid={testId} data-auth-mode="anonymous">
        匿名
      </Tag>
    )
  }
  const overridden = auth.overridden_headers
  return (
    <div data-testid={testId} data-auth-mode="identity" className="tp-auth-summary">
      <Space wrap size={[6, 4]}>
        <Tag className="tp-auth-identity">
          身份：{auth.identity}
        </Tag>
        {overridden.length > 0 ? (
          <Tag color="gold" data-testid={`${testId}-overridden-flag`}>
            覆盖 {overridden.length} 个 header
          </Tag>
        ) : null}
      </Space>
      {/* 原生 details：零依赖、键盘可达，默认收起，展开只列 header 名 */}
      <details className="tp-auth-details">
        <summary>查看 header 名</summary>
        <dl className="tp-auth-details__list">
          <dt>注入的 header</dt>
          <dd data-testid={`${testId}-header-names`}>
            {auth.header_names.length > 0
              ? auth.header_names.map((name) => (
                  <Typography.Text code key={name}>
                    {name}
                  </Typography.Text>
                ))
              : '—'}
          </dd>
          <dt>被覆盖的资产 header</dt>
          <dd data-testid={`${testId}-overridden-headers`}>
            {overridden.length > 0
              ? overridden.map((name) => (
                  <Typography.Text code key={name}>
                    {name}
                  </Typography.Text>
                ))
              : '无'}
          </dd>
        </dl>
      </details>
    </div>
  )
}
