import { Alert, Button, Descriptions, Empty, Input, Modal, Select, Space, Switch, Typography } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { formatErrorMessage } from '@/shared/ui/errorMessage'
import { ErrorState, LoadingState } from '@/shared/ui/AsyncState'
import { useUnauthorizedGuard } from '@/features/auth/hooks'
import { getEnvironment } from './api'
import { isCurrentEditTarget, nextEditTarget, type EditTarget } from './editSession'
import {
  useCreateEnvironment,
  useEnvironments,
  useUpdateEnvironment,
} from './hooks'
import {
  collectHosts,
  formatCaseParams,
  hostsToRows,
  parseCaseParamsText,
  parseTimeoutText,
  validateEnvName,
  type HostRow,
} from './names'
import { isRevisionConflict, REVISION_CONFLICT_MESSAGE } from './revision'
import type { ProjectEnvironment } from './types'
import { ServiceHosts } from './ServiceHosts'

interface EnvDraft {
  mode: 'create' | 'edit'
  env: string
  enabled: boolean
  timeoutText: string
  caseParamsText: string
  hosts: HostRow[]
  revision: number | null
}

function blankDraft(): EnvDraft {
  return {
    mode: 'create',
    env: '',
    enabled: true,
    timeoutText: '',
    caseParamsText: '',
    hosts: [{ name: '', url: '' }],
    revision: null,
  }
}

function draftFromEnvironment(row: ProjectEnvironment): EnvDraft {
  return {
    mode: 'edit',
    env: row.env,
    enabled: row.enabled,
    timeoutText: row.timeout_seconds === null ? '' : String(row.timeout_seconds),
    caseParamsText: formatCaseParams(row.case_params),
    hosts: hostsToRows(row.api_hosts),
    revision: row.revision,
  }
}

/**
 * 环境新增、编辑、停用。保存带 revision；409 只提示刷新，不自动用旧表单覆盖。
 * 不用 Monaco、继承树或拖拽编辑器。
 */
export function EnvironmentSection({ projectId }: { projectId: string }) {
  const listQuery = useEnvironments(projectId)
  const [selectedEnv, setSelectedEnv] = useState<string | null>(null)
  const createMutation = useCreateEnvironment(projectId)
  const updateMutation = useUpdateEnvironment(projectId)
  const discardUnauthorized = useUnauthorizedGuard()
  const targetRef = useRef<EditTarget | null>(null)
  const [draft, setDraft] = useState<EnvDraft | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [conflict, setConflict] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [listError, setListError] = useState<string | null>(null)
  const saving = createMutation.isPending || updateMutation.isPending

  const begin = (envName: string | null) => {
    const next = nextEditTarget(targetRef.current, {
      projectId,
      env: envName ?? '',
      accountName: null,
    })
    targetRef.current = next
    return next
  }

  const close = () => {
    begin(null)
    setDraft(null)
    setConflict(false)
    setRefreshing(false)
  }

  useEffect(() => {
    setSelectedEnv(null)
    targetRef.current = nextEditTarget(targetRef.current, {
      projectId,
      env: '',
      accountName: null,
    })
    setDraft(null)
    setFormError(null)
    setConflict(false)
    setRefreshing(false)
  }, [projectId])

  const save = async () => {
    const session = targetRef.current
    if (!draft || !session || session.projectId !== projectId) {
      return
    }
    setFormError(null)
    const envName = draft.env.trim()
    if (draft.mode === 'create') {
      const nameError = validateEnvName(envName)
      if (nameError) {
        setFormError(nameError)
        return
      }
    }
    const hosts = collectHosts(draft.hosts)
    if ('error' in hosts) {
      setFormError(hosts.error)
      return
    }
    const params = parseCaseParamsText(draft.caseParamsText)
    if ('error' in params) {
      setFormError(params.error)
      return
    }
    const timeout = parseTimeoutText(draft.timeoutText)
    if ('error' in timeout) {
      setFormError(timeout.error)
      return
    }
    const body = {
      api_hosts: hosts.hosts,
      timeout_seconds: timeout.value,
      case_params: params.value,
      enabled: draft.enabled,
    }
    try {
      if (draft.mode === 'create') {
        await createMutation.mutateAsync({ env: envName, ...body })
      } else {
        if (draft.revision === null) {
          setFormError('缺少配置版本，请刷新后再保存')
          return
        }
        await updateMutation.mutateAsync({
          env: draft.env,
          body: { revision: draft.revision, ...body },
        })
      }
      if (!isCurrentEditTarget(targetRef.current, session)) {
        return
      }
      close()
      setSelectedEnv(envName)
    } catch (error) {
      if (!isCurrentEditTarget(targetRef.current, session)) {
        return
      }
      if (discardUnauthorized(error)) {
        close()
        return
      }
      if (isRevisionConflict(error)) {
        setConflict(true)
        setFormError(REVISION_CONFLICT_MESSAGE)
        return
      }
      setFormError(formatErrorMessage(error))
    }
  }

  const refresh = async () => {
    const session = targetRef.current
    if (!draft || draft.mode !== 'edit' || !session || session.env !== draft.env) {
      return
    }
    setRefreshing(true)
    try {
      const fresh = await getEnvironment(session.projectId, session.env)
      if (!isCurrentEditTarget(targetRef.current, session)) {
        return
      }
      setDraft(draftFromEnvironment(fresh))
      setConflict(false)
      setFormError(null)
    } catch (error) {
      if (!isCurrentEditTarget(targetRef.current, session)) {
        return
      }
      if (discardUnauthorized(error)) {
        close()
        return
      }
      setFormError(formatErrorMessage(error))
    } finally {
      if (isCurrentEditTarget(targetRef.current, session)) {
        setRefreshing(false)
      }
    }
  }

  const toggleEnabled = async (row: ProjectEnvironment) => {
    setListError(null)
    try {
      await updateMutation.mutateAsync({
        env: row.env,
        body: { revision: row.revision, enabled: !row.enabled },
      })
    } catch (error) {
      if (isRevisionConflict(error)) {
        setListError(REVISION_CONFLICT_MESSAGE)
        return
      }
      setListError(formatErrorMessage(error))
    }
  }

  if (listQuery.isLoading) {
    return <LoadingState tip="加载环境…" />
  }
  if (listQuery.isError) {
    return (
      <ErrorState
        error={listQuery.error}
        title="环境加载失败"
        onRetry={() => {
          void listQuery.refetch()
        }}
      />
    )
  }

  const rows = listQuery.data ?? []
  const current = rows.find((row) => row.env === selectedEnv) ?? rows.find((row) => row.enabled) ?? rows[0]

  return (
    <div data-testid="environment-manager">
      <Space style={{ marginBottom: 16 }} wrap>
        <span>环境</span>
        <Select
          aria-label="查看环境"
          data-testid="environment-select"
          style={{ minWidth: 180 }}
          value={current?.env}
          placeholder="请选择环境"
          options={rows.map((row) => ({ value: row.env, label: row.enabled ? row.env : `${row.env}（已停用）` }))}
          onChange={(value) => { close(); setListError(null); setSelectedEnv(value) }}
        />
        {current ? (
          <>
            <Button
              data-testid={`env-edit-${current.env}`}
              onClick={() => {
                begin(current.env)
                setFormError(null)
                setConflict(false)
                setDraft(draftFromEnvironment(current))
              }}
            >编辑当前环境</Button>
            <Button data-testid={`env-toggle-${current.env}`} onClick={() => { void toggleEnabled(current) }}>
              {current.enabled ? '停用' : '启用'}
            </Button>
          </>
        ) : null}
        <Button
          type="primary"
          data-testid="env-create-open"
          onClick={() => {
            begin(null)
            setFormError(null)
            setConflict(false)
            setDraft(blankDraft())
          }}
        >
          新增环境
        </Button>
      </Space>
      {listError ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message={listError}
          data-testid="env-list-error"
        />
      ) : null}
      {current ? (
        <div data-testid="environment-detail">
          <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 4 }}>
            <Descriptions.Item label="状态">{current.enabled ? '使用中' : '已停用'}</Descriptions.Item>
            <Descriptions.Item label="请求超时">{current.timeout_seconds ?? 30} 秒</Descriptions.Item>
            <Descriptions.Item label="版本">{current.revision}</Descriptions.Item>
            <Descriptions.Item label="更新人">{current.updated_by || '—'}</Descriptions.Item>
          </Descriptions>
          <ServiceHosts hosts={current.api_hosts} />
          <Typography.Paragraph type="secondary" style={{ marginTop: 16 }}>
            服务地址用于当前环境的请求和登录。共享配置的影响范围见上方提示。
          </Typography.Paragraph>
          {Object.keys(current.case_params).length > 0 ? (
            <Typography.Paragraph type="secondary">
              此环境保留 {Object.keys(current.case_params).length} 项参数覆盖，可在编辑环境中维护。
            </Typography.Paragraph>
          ) : null}
        </div>
      ) : <Empty description="还没有环境，请先新增环境" />}
      <Modal
        width={860}
        title={draft?.mode === 'edit' ? `编辑环境 ${draft.env}` : '新增环境'}
        open={draft !== null}
        onCancel={close}
        destroyOnClose
        footer={
          <Space>
            <Button data-testid="env-cancel" onClick={close}>
              取消
            </Button>
            <Button
              type="primary"
              loading={saving}
              data-testid="env-save"
              onClick={() => {
                void save()
              }}
            >
              保存环境
            </Button>
          </Space>
        }
      >
        {draft ? (
          <EnvironmentForm
            draft={draft}
            conflict={conflict}
            refreshing={refreshing}
            formError={formError}
            onChange={setDraft}
            onRefresh={() => {
              void refresh()
            }}
          />
        ) : null}
      </Modal>
    </div>
  )
}

function EnvironmentForm({
  draft,
  conflict,
  refreshing,
  formError,
  onChange,
  onRefresh,
}: {
  draft: EnvDraft
  conflict: boolean
  refreshing: boolean
  formError: string | null
  onChange: (next: EnvDraft) => void
  onRefresh: () => void
}) {
  return (
    <div data-testid="env-editor">
      {conflict ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          data-testid="revision-conflict"
          message={REVISION_CONFLICT_MESSAGE}
          description="刷新后请再保存。未保存的修改会被服务器上的版本替换。"
          action={
            <Button
              size="small"
              data-testid="revision-refresh"
              loading={refreshing}
              onClick={onRefresh}
            >
              刷新
            </Button>
          }
        />
      ) : null}
      {formError && !conflict ? (
        <Alert type="error" showIcon style={{ marginBottom: 12 }} message={formError} />
      ) : null}
      {draft.mode === 'edit' && draft.revision !== null ? (
        <Typography.Paragraph data-testid="editing-revision" style={{ marginBottom: 8 }}>
          版本 {draft.revision}
        </Typography.Paragraph>
      ) : null}
      <Typography.Text>环境名</Typography.Text>
      <Input
        aria-label="环境名"
        style={{ margin: '4px 0 12px' }}
        value={draft.env}
        disabled={draft.mode === 'edit'}
        onChange={(event) => onChange({ ...draft, env: event.target.value })}
      />
      <Space style={{ marginBottom: 12 }}>
        <span>启用</span>
        <Switch
          aria-label="启用环境"
          checked={draft.enabled}
          onChange={(checked) => onChange({ ...draft, enabled: checked })}
        />
      </Space>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
        逻辑服务名与地址。留空表示该环境不配置 host。
      </Typography.Paragraph>
      {draft.hosts.map((row, index) => (
        <div key={index} className="tp-host-editor-row">
          <label>
            <Typography.Text type="secondary">逻辑服务名</Typography.Text>
            <Input
              aria-label={`服务名 ${index + 1}`}
              placeholder="gsb"
              value={row.name}
              onChange={(event) => {
                const hosts = draft.hosts.slice()
                hosts[index] = { ...row, name: event.target.value }
                onChange({ ...draft, hosts })
              }}
            />
          </label>
          <label>
            <Typography.Text type="secondary">完整地址</Typography.Text>
            <Input.TextArea
              autoSize={{ minRows: 1, maxRows: 5 }}
              aria-label={`地址 ${index + 1}`}
              placeholder="https://example.invalid"
              value={row.url}
              onChange={(event) => {
                const hosts = draft.hosts.slice()
                hosts[index] = { ...row, url: event.target.value }
                onChange({ ...draft, hosts })
              }}
            />
          </label>
          <Button
            aria-label={`删除服务地址 ${index + 1}`}
            onClick={() => {
              const hosts = draft.hosts.filter((_, itemIndex) => itemIndex !== index)
              onChange({
                ...draft,
                hosts: hosts.length > 0 ? hosts : [{ name: '', url: '' }],
              })
            }}
          >
            删除
          </Button>
        </div>
      ))}
      <Button
        style={{ marginBottom: 16, display: 'block' }}
        onClick={() => onChange({ ...draft, hosts: [...draft.hosts, { name: '', url: '' }] })}
      >
        添加服务地址
      </Button>
      <Typography.Text>超时（秒）</Typography.Text>
      <Input
        aria-label="超时（秒）"
        style={{ margin: '4px 0 12px' }}
        value={draft.timeoutText}
        placeholder="留空使用默认 30 秒"
        onChange={(event) => onChange({ ...draft, timeoutText: event.target.value })}
      />
      <Typography.Text>环境参数覆盖（兼容现有配置）</Typography.Text>
      <Input.TextArea
        aria-label="参数默认值"
        style={{ marginTop: 4 }}
        rows={4}
        value={draft.caseParamsText}
        placeholder='{"product_keyword":"demo"}'
        onChange={(event) => onChange({ ...draft, caseParamsText: event.target.value })}
      />
      <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
        JSON 对象，仅用于环境差异，单次输入优先。接口／场景自身的默认值应随各自维护；已有值继续生效。
      </Typography.Paragraph>
    </div>
  )
}
