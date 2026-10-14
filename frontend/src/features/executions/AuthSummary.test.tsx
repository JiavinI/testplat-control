import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider, App as AntApp } from 'antd'
import type { ReactNode } from 'react'
import { loadContractExample } from '@/test/contractExamples'
import { ApiHttpError } from '@/shared/api/errors'
import { parseRunResponse } from './api'
import { parseCaseRunResponse } from './caseParse'
import { CaseResultView } from './CaseResultView'
import { ExecutionResultCard } from './ExecutionResultCard'
import type { CaseResult, CaseStepResult } from './types'

// 测试用假秘密：只作为“不得出现在 DOM 中”的搜索目标
const FAKE_SECRETS = ['tp-fake-secret-9f31c2a7', 'tp-fake-partner-4c8e11d0']

const runCase = vi.fn()
vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>()
  return {
    ...actual,
    runCase: (...args: unknown[]) => runCase(...args),
    listExecutionRecords: vi.fn().mockResolvedValue([]),
    getCaseExecutionRecord: vi.fn(),
  }
})

function wrap(node: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntApp>
        <QueryClientProvider client={client}>{node}</QueryClientProvider>
      </AntApp>
    </ConfigProvider>,
  )
}

function expectNoSecrets(container: HTMLElement) {
  const html = container.ownerDocument.body.innerHTML
  for (const secret of FAKE_SECRETS) {
    expect(html).not.toContain(secret)
  }
}

describe('单 API 结果身份展示', () => {
  it('有身份：显示“身份：admin”，展开可见注入与被覆盖的 header 名', async () => {
    const user = userEvent.setup({ delay: null })
    const { container } = wrap(
      <ExecutionResultCard result={parseRunResponse(loadContractExample('api-run-with-auth.json'))} />,
    )
    const summary = screen.getByTestId('auth-summary')
    expect(summary).toHaveAttribute('data-auth-mode', 'identity')
    expect(within(summary).getByText('身份：admin')).toBeInTheDocument()
    expect(screen.getByTestId('auth-summary-overridden-flag')).toHaveTextContent('覆盖 1 个 header')
    await user.click(within(summary).getByText('查看 header / Cookie 名'))
    expect(screen.getByTestId('auth-summary-header-names')).toHaveTextContent('Authorization')
    expect(screen.getByTestId('auth-summary-overridden-headers')).toHaveTextContent('authorization')
    expect(within(summary).queryByText('匿名')).not.toBeInTheDocument()
    expectNoSecrets(container)
  })

  it('auth 为 null：显示“匿名”', () => {
    wrap(
      <ExecutionResultCard
        result={parseRunResponse({ record_id: 'r', status: 'success', duration: 0, result: {}, auth: null })}
      />,
    )
    const summary = screen.getByTestId('auth-summary')
    expect(summary).toHaveAttribute('data-auth-mode', 'anonymous')
    expect(summary).toHaveTextContent('匿名')
  })

  it('响应 auth 中夹带的多余键（含值）不会进入 DOM', () => {
    const payload = loadContractExample('api-run-with-auth.json') as { auth: Record<string, unknown> }
    payload.auth = { ...payload.auth, secret: FAKE_SECRETS[0], partner: FAKE_SECRETS[1] }
    const { container } = wrap(<ExecutionResultCard result={parseRunResponse(payload)} />)
    expect(screen.getByTestId('auth-summary')).toHaveTextContent('身份：admin')
    expectNoSecrets(container)
  })
})

function step(overrides: Partial<CaseStepResult>): CaseStepResult {
  return {
    step_id: 's',
    name: null,
    type: 'api',
    status: 'success',
    duration_seconds: 0.01,
    request: { method: 'GET', url: 'http://x' },
    response: { status_code: 200 },
    error: null,
    output: null,
    skip_reason: null,
    auth: null,
    ...overrides,
  }
}

describe('Case 步骤身份展示', () => {
  it('冻结示例：每个步骤显示“身份：partner”', async () => {
    const user = userEvent.setup({ delay: null })
    const { container } = wrap(
      <CaseResultView result={parseCaseRunResponse(loadContractExample('case-run-with-auth.json')).result} />,
    )
    await user.click(screen.getByText('步骤 create'))
    const auth = await screen.findByTestId('step-auth-create')
    expect(auth).toHaveTextContent('身份：partner')
    await user.click(within(auth).getByText('查看 header / Cookie 名'))
    expect(screen.getByTestId('step-auth-create-header-names')).toHaveTextContent('X-Api-Key')
    expect(screen.getByTestId('step-auth-create-overridden-headers')).toHaveTextContent('无')
    expectNoSecrets(container)
  })

  it('系统错误步骤 auth 为 null 显示“—”而非“匿名”；已发请求的匿名步骤显示“匿名”；错误文案原样来自后端', async () => {
    const backendMessage = '后端返回的超时文案-不应被前端改写'
    const result: CaseResult = {
      case_id: 'case.demo.mixed',
      status: 'failed',
      duration_seconds: 0.3,
      steps: [
        step({ step_id: 'anon', name: '匿名步骤' }),
        step({
          step_id: 'admin',
          name: '管理员步骤',
          auth: { identity: 'admin', kind: 'static_headers', tier: null, header_names: ['Authorization'], overridden_headers: [], cookie_names: [], login_ref: null, session_source: null, reauthenticated: false },
        }),
        step({
          step_id: 'slow',
          name: '超时步骤',
          status: 'failed',
          request: null,
          response: null,
          error: { kind: 'timeout', message: backendMessage, stage: 'execution', step_id: null, path: null },
        }),
      ],
      summary: { total: 3, success: 2, failed: 1, skipped: 0 },
      error: { kind: 'timeout', stage: 'execution', message: backendMessage },
      logins: [],
    }
    const user = userEvent.setup({ delay: null })
    wrap(<CaseResultView result={result} />)
    // 首个失败步骤默认展开
    const slow = await screen.findByTestId('step-auth-slow')
    expect(slow).toHaveAttribute('data-auth-mode', 'not_applicable')
    expect(slow).toHaveTextContent('—')
    expect(slow).not.toHaveTextContent('匿名')
    expect(screen.getAllByText(backendMessage).length).toBeGreaterThan(0)

    await user.click(screen.getByText('匿名步骤'))
    expect(await screen.findByTestId('step-auth-anon')).toHaveTextContent('匿名')
    await user.click(screen.getByText('管理员步骤'))
    expect(await screen.findByTestId('step-auth-admin')).toHaveTextContent('身份：admin')
  })
})

describe('身份相关 422', () => {
  it('预检 422 原样展示后端 detail（不硬编码文案）', async () => {
    const { CaseExecutionPanel } = await import('./CaseExecutionPanel')
    const errors = loadContractExample('auth-error-responses.json') as Record<string, { status: number; body: { detail: string } }>
    const sample = errors.identity_unavailable
    runCase.mockRejectedValueOnce(
      new ApiHttpError(sample.status, sample.body.detail, JSON.stringify(sample.body)),
    )
    const user = userEvent.setup({ delay: null })
    const { container } = wrap(<CaseExecutionPanel projectId="p1" caseId="case.demo.create_then_get" />)
    await user.click(await screen.findByRole('button', { name: '执行 Case' }))
    expect(await screen.findByText(sample.body.detail)).toBeInTheDocument()
    expect(screen.getByText(/预检失败/)).toBeInTheDocument()
    expectNoSecrets(container)
  })
})


describe('Phase 3.3d 缓存与重登展示', () => {
  it('session_source=cache：显示「复用登录（未重新登录）」且无登录过程面板', () => {
    const result = parseRunResponse({
      record_id: 'r-cache',
      status: 'success',
      duration: 0.1,
      result: { request: { method: 'GET', url: 'http://x' }, response: { status_code: 200 } },
      auth: {
        identity: 'buyer',
        kind: 'login',
        tier: 'generic',
        header_names: ['X-TOKEN'],
        overridden_headers: [],
        cookie_names: [],
        login_ref: null,
        session_source: 'cache',
        reauthenticated: false,
      },
    })
    const { container } = wrap(<ExecutionResultCard result={result} />)
    expect(screen.getByTestId('auth-summary-session-cache')).toHaveTextContent(
      '复用登录（未重新登录）',
    )
    expect(screen.getByTestId('login-cache-reuse-note')).toHaveTextContent(
      '本次无登录过程可查看',
    )
    expect(screen.queryByTestId('login-process-panel')).not.toBeInTheDocument()
    expectNoSecrets(container)
  })

  it('reauthenticated=true：显示「鉴权失效，已重新登录并重发」', () => {
    const result = parseRunResponse({
      record_id: 'r-reauth',
      status: 'success',
      duration: 0.2,
      result: {
        request: { method: 'GET', url: 'http://x' },
        response: { status_code: 200 },
        logins: [
          {
            identity: 'buyer',
            strategy: 'generic_flow',
            tier: 'generic',
            status: 'success',
            duration_seconds: 0.05,
            steps: [],
            probe: null,
            error: null,
          },
        ],
      },
      auth: {
        identity: 'buyer',
        kind: 'login',
        tier: 'generic',
        header_names: ['X-TOKEN'],
        overridden_headers: [],
        cookie_names: [],
        login_ref: 0,
        session_source: 'login',
        reauthenticated: true,
      },
    })
    wrap(<ExecutionResultCard result={result} />)
    expect(screen.getByTestId('auth-summary-reauthenticated')).toHaveTextContent(
      '鉴权失效，已重新登录并重发',
    )
  })

  it('旧七键记录：不显示缓存/重登标签', () => {
    // 契约示例仍为七键；解析后 session_source=null、reauthenticated=false
    wrap(
      <ExecutionResultCard result={parseRunResponse(loadContractExample('api-run-with-auth.json'))} />,
    )
    expect(screen.queryByTestId('auth-summary-session-cache')).not.toBeInTheDocument()
    expect(screen.queryByTestId('auth-summary-reauthenticated')).not.toBeInTheDocument()
  })
})

