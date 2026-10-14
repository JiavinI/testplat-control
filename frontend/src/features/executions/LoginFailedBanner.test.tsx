import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { CaseResultView } from './CaseResultView'
import type { CaseResult } from './types'

const FAKE = 'tp-fake-login-token-aabbcc'

describe('login_failed 醒目展示', () => {
  it('标题固定为登录失败；正文来自后端 message；skipped 文案区分 fail_fast', () => {
    const backendMessage = '后端返回的登录失败说明-不可改写'
    const result: CaseResult = {
      case_id: 'case.demo.login',
      status: 'failed',
      duration_seconds: 0.2,
      steps: [
        {
          step_id: 'create',
          name: '步骤 create',
          type: 'api',
          status: 'failed',
          duration_seconds: 0.1,
          request: null,
          response: null,
          error: {
            kind: 'login_failed',
            message: backendMessage,
            stage: null,
            step_id: null,
            path: null,
            login: {
              identity: 'buyer',
              strategy: 'generic_flow',
              failed_step: 'login',
              reason: 'assertion',
            },
          },
          output: null,
          skip_reason: null,
          auth: {
            identity: 'buyer',
            kind: 'login',
            tier: 'generic',
            header_names: ['Authorization'],
            overridden_headers: [],
            cookie_names: [],
            login_ref: 0,
            session_source: 'login',
            reauthenticated: false,
          },
        },
        {
          step_id: 'get',
          name: '步骤 get',
          type: 'api',
          status: 'skipped',
          duration_seconds: 0,
          request: null,
          response: null,
          error: null,
          output: null,
          skip_reason: 'login_failed',
          auth: null,
        },
      ],
      summary: { total: 2, success: 0, failed: 1, skipped: 1 },
      error: null,
      logins: [
        {
          identity: 'buyer',
          strategy: 'generic_flow',
          tier: 'generic',
          status: 'failed',
          duration_seconds: 0.05,
          steps: [
            {
              name: 'login',
              request: {
                method: 'POST',
                url: 'http://127.0.0.1/login',
                body: { password: '***' },
                body_type: 'json',
              },
              response: { status_code: 401, body: { error: 'bad' } },
            },
          ],
          probe: null,
          error: { reason: 'assertion', failed_step: 'login' },
        },
      ],
    }
    const { container } = render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <CaseResultView result={result} />
      </ConfigProvider>,
    )
    expect(screen.getByTestId('login-failed-banner')).toHaveTextContent('登录失败')
    expect(screen.getAllByText(backendMessage).length).toBeGreaterThan(0)
    expect(screen.getByTestId('case-login-failed-marker')).toBeInTheDocument()
    expect(screen.getByTestId('step-login-failed-marker-create')).toBeInTheDocument()
    expect(screen.getByTestId('step-skipped-login-failed-get')).toHaveTextContent('因登录失败跳过')
    expect(screen.getByTestId('login-process-panel')).toBeInTheDocument()
    expect(container.innerHTML).not.toContain(FAKE)
  })
})
