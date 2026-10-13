import { LockOutlined } from '@ant-design/icons'
import { Typography } from 'antd'
import { loginReasonLabel } from './loginDisplay'

export type LoginFailedBannerProps = {
  /** 后端 error.message，原样展示，不硬编码 */
  message: string
  reason?: string | null
  failedStep?: string | null
  identity?: string | null
  testId?: string
}

/**
 * 登录失败醒目横幅：固定标题「登录失败」，独立色板与锁图标，
 * 与断言失败（红）/ 系统错误（红 Alert）区分；正文来自后端 message。
 */
export function LoginFailedBanner({
  message,
  reason,
  failedStep,
  identity,
  testId = 'login-failed-banner',
}: LoginFailedBannerProps) {
  const reasonLabel = loginReasonLabel(reason)
  return (
    <div
      className="tp-login-failed-banner"
      data-testid={testId}
      role="alert"
      aria-label="登录失败"
    >
      <div className="tp-login-failed-banner__title">
        <LockOutlined className="tp-login-failed-banner__icon" aria-hidden />
        <Typography.Text strong className="tp-login-failed-banner__heading">
          登录失败
        </Typography.Text>
        {identity ? (
          <Typography.Text type="secondary" data-testid={`${testId}-identity`}>
            身份：{identity}
          </Typography.Text>
        ) : null}
        {reasonLabel ? (
          <span className="tp-login-failed-banner__reason" data-testid={`${testId}-reason`}>
            {reasonLabel}
            {reason ? `（${reason}）` : ''}
          </span>
        ) : null}
      </div>
      <Typography.Paragraph className="tp-login-failed-banner__message" style={{ marginBottom: 0 }}>
        {message}
      </Typography.Paragraph>
      {failedStep ? (
        <Typography.Text type="secondary" data-testid={`${testId}-failed-step`}>
          失败步骤：{failedStep}
        </Typography.Text>
      ) : null}
    </div>
  )
}
