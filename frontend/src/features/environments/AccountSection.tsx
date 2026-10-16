import {
  Alert,
  Button,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useEffect, useState } from 'react'
import { formatErrorMessage } from '@/shared/ui/errorMessage'
import { ErrorState, LoadingState } from '@/shared/ui/AsyncState'
import { getAccount } from './api'
import {
  fetchAccountCredentials,
  useAccounts,
  useCreateAccount,
  useEnvironments,
  useLoginProfiles,
  useUpdateAccount,
} from './hooks'
import {
  sameCredentials,
  validateAccountName,
  validateCredentialValue,
} from './names'
import { isRevisionConflict, REVISION_CONFLICT_MESSAGE } from './revision'
import type { TestAccount } from './types'

interface AccountDraft {
  mode: 'create' | 'edit'
  account_name: string
  display_name: string
  business_role: string
  login_profile: string
  originalProfile: string
  enabled: boolean
  revision: number | null
}

function blankAccount(): AccountDraft {
  return {
    mode: 'create',
    account_name: '',
    display_name: '',
    business_role: '',
    login_profile: '',
    originalProfile: '',
    enabled: true,
    revision: null,
  }
}

function draftFromAccount(row: TestAccount): AccountDraft {
  return {
    mode: 'edit',
    account_name: row.account_name,
    display_name: row.display_name ?? '',
    business_role: row.business_role ?? '',
    login_profile: row.login_profile,
    originalProfile: row.login_profile,
    enabled: row.enabled,
    revision: row.revision,
  }
}

/**
 * 测试账号。列表不展示密码。
 * 凭据只在点击「查看凭据」后进入本组件状态，不进 Query 缓存。
 */
export function AccountSection({ projectId }: { projectId: string }) {
  const environments = useEnvironments(projectId)
  const [env, setEnv] = useState<string | null>(null)
  const accounts = useAccounts(projectId, env)
  const [editorOpen, setEditorOpen] = useState(false)
  const profiles = useLoginProfiles(projectId, editorOpen)

  useEffect(() => {
    if (!environments.data || environments.data.length === 0) {
      setEnv(null)
      return
    }
    setEnv((current) => {
      if (current && environments.data.some((item) => item.env === current)) {
        return current
      }
      return environments.data[0]?.env ?? null
    })
  }, [environments.data])

  useEffect(() => {
    setEditorOpen(false)
  }, [env])

  if (environments.isLoading) {
    return <LoadingState tip="加载环境…" />
  }
  if (environments.isError) {
    return (
      <ErrorState
        error={environments.error}
        title="环境加载失败"
        onRetry={() => {
          void environments.refetch()
        }}
      />
    )
  }

  const envRows = environments.data ?? []
  if (envRows.length === 0) {
    return <Alert type="info" showIcon message="请先新增环境，再维护测试账号。" />
  }

  return (
    <div data-testid="account-manager">
      <Space style={{ marginBottom: 12 }} wrap>
        <span>环境</span>
        <Select
          data-testid="account-env-select"
          aria-label="账号所属环境"
          style={{ minWidth: 180 }}
          value={env ?? undefined}
          options={envRows.map((item) => ({
            value: item.env,
            label: item.enabled ? item.env : `${item.env}（已停用）`,
          }))}
          onChange={(value) => setEnv(value)}
        />
      </Space>
      {env ? (
        <AccountTable
          key={env}
          projectId={projectId}
          env={env}
          accounts={accounts}
          profiles={profiles.data?.profiles ?? []}
          profilesLoading={profiles.isLoading}
          profilesError={profiles.error}
          editorOpen={editorOpen}
          onEditorOpen={setEditorOpen}
          onRetryProfiles={() => {
            void profiles.refetch()
          }}
        />
      ) : null}
    </div>
  )
}

function AccountTable({
  projectId,
  env,
  accounts,
  profiles,
  profilesLoading,
  profilesError,
  editorOpen,
  onEditorOpen,
  onRetryProfiles,
}: {
  projectId: string
  env: string
  accounts: ReturnType<typeof useAccounts>
  profiles: Array<{ name: string; credential_fields: string[] }>
  profilesLoading: boolean
  profilesError: unknown
  editorOpen: boolean
  onEditorOpen: (open: boolean) => void
  onRetryProfiles: () => void
}) {
  const createMutation = useCreateAccount(projectId, env)
  const updateMutation = useUpdateAccount(projectId, env)
  const [draft, setDraft] = useState<AccountDraft | null>(null)
  const [revealed, setRevealed] = useState<Record<string, string> | null>(null)
  const [credentialDraft, setCredentialDraft] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [conflict, setConflict] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [revealing, setRevealing] = useState(false)
  const [listError, setListError] = useState<string | null>(null)
  const saving = createMutation.isPending || updateMutation.isPending

  const openCreate = () => {
    setDraft(blankAccount())
    setRevealed(null)
    setCredentialDraft({})
    setFormError(null)
    setConflict(false)
    onEditorOpen(true)
  }

  const openEdit = (row: TestAccount) => {
    setDraft(draftFromAccount(row))
    setRevealed(null)
    setCredentialDraft({})
    setFormError(null)
    setConflict(false)
    onEditorOpen(true)
  }

  const close = () => {
    setDraft(null)
    setRevealed(null)
    setCredentialDraft({})
    setConflict(false)
    onEditorOpen(false)
  }

  const profileFields =
    profiles.find((item) => item.name === draft?.login_profile)?.credential_fields ?? []

  const reveal = async () => {
    if (!draft || draft.mode !== 'edit') {
      return
    }
    setRevealing(true)
    setFormError(null)
    try {
      const data = await fetchAccountCredentials(projectId, env, draft.account_name)
      setRevealed(data.credentials)
      setCredentialDraft({ ...data.credentials })
    } catch (error) {
      setFormError(formatErrorMessage(error))
    } finally {
      setRevealing(false)
    }
  }

  const refresh = async () => {
    if (!draft || draft.mode !== 'edit') {
      return
    }
    setRefreshing(true)
    try {
      const fresh = await getAccount(projectId, env, draft.account_name)
      setDraft(draftFromAccount(fresh))
      if (revealed) {
        const data = await fetchAccountCredentials(projectId, env, draft.account_name)
        setRevealed(data.credentials)
        setCredentialDraft({ ...data.credentials })
      }
      setConflict(false)
      setFormError(null)
    } catch (error) {
      setFormError(formatErrorMessage(error))
    } finally {
      setRefreshing(false)
    }
  }

  const save = async () => {
    if (!draft) {
      return
    }
    setFormError(null)
    const profileChanged = draft.mode === 'edit' && draft.login_profile !== draft.originalProfile
    if (!draft.login_profile) {
      setFormError('请选择登录流程')
      return
    }
    const credentialsResult = resolveCredentials({
      mode: draft.mode,
      profileChanged,
      fields: profileFields,
      revealed,
      credentialDraft,
    })
    if ('error' in credentialsResult) {
      setFormError(credentialsResult.error)
      return
    }
    const displayName = draft.display_name.trim() || null
    const businessRole = draft.business_role.trim() || null
    try {
      if (draft.mode === 'create') {
        const nameError = validateAccountName(draft.account_name.trim())
        if (nameError) {
          setFormError(nameError)
          return
        }
        if (!credentialsResult.credentials) {
          setFormError('请填写凭据')
          return
        }
        await createMutation.mutateAsync({
          account_name: draft.account_name.trim(),
          display_name: displayName,
          business_role: businessRole,
          login_profile: draft.login_profile,
          credentials: credentialsResult.credentials,
          enabled: draft.enabled,
        })
      } else {
        if (draft.revision === null) {
          setFormError('缺少配置版本，请刷新后再保存')
          return
        }
        await updateMutation.mutateAsync({
          name: draft.account_name,
          body: {
            revision: draft.revision,
            display_name: displayName,
            business_role: businessRole,
            login_profile: draft.login_profile,
            enabled: draft.enabled,
            ...(credentialsResult.credentials
              ? { credentials: credentialsResult.credentials }
              : {}),
          },
        })
      }
      close()
    } catch (error) {
      if (isRevisionConflict(error)) {
        setConflict(true)
        setFormError(REVISION_CONFLICT_MESSAGE)
        return
      }
      setFormError(formatErrorMessage(error))
    }
  }

  const toggleEnabled = async (row: TestAccount) => {
    setListError(null)
    try {
      await updateMutation.mutateAsync({
        name: row.account_name,
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

  if (accounts.isLoading) {
    return <LoadingState tip="加载账号…" />
  }
  if (accounts.isError) {
    return (
      <ErrorState
        error={accounts.error}
        title="账号加载失败"
        onRetry={() => {
          void accounts.refetch()
        }}
      />
    )
  }

  const rows = accounts.data ?? []
  const columns: ColumnsType<TestAccount> = [
    { title: '账号名', dataIndex: 'account_name', key: 'account_name' },
    {
      title: '展示名',
      dataIndex: 'display_name',
      key: 'display_name',
      render: (value: string | null) => value || '—',
    },
    {
      title: '业务角色',
      dataIndex: 'business_role',
      key: 'business_role',
      render: (value: string | null) => value || '—',
    },
    { title: '登录流程', dataIndex: 'login_profile', key: 'login_profile' },
    {
      title: '启用',
      dataIndex: 'enabled',
      key: 'enabled',
      render: (value: boolean) => (value ? '是' : '否'),
    },
    { title: '版本', dataIndex: 'revision', key: 'revision' },
    {
      title: '操作',
      key: 'actions',
      render: (_value, row) => (
        <Space>
          <Button
            size="small"
            data-testid={`account-edit-${row.account_name}`}
            onClick={() => openEdit(row)}
          >
            编辑
          </Button>
          <Button
            size="small"
            data-testid={`account-toggle-${row.account_name}`}
            onClick={() => {
              void toggleEnabled(row)
            }}
          >
            {row.enabled ? '停用' : '启用'}
          </Button>
        </Space>
      ),
    },
  ]

  const showCredentialInputs = draft?.mode === 'create' || revealed !== null

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Button type="primary" data-testid="account-create-open" onClick={openCreate}>
          新增账号
        </Button>
      </Space>
      {listError ? (
        <Alert type="warning" showIcon style={{ marginBottom: 12 }} message={listError} />
      ) : null}
      <Table
        size="small"
        rowKey="account_name"
        columns={columns}
        dataSource={rows}
        pagination={false}
        data-testid="account-table"
        locale={{ emptyText: '这个环境还没有测试账号' }}
      />
      <Modal
        title={
          draft?.mode === 'edit'
            ? `编辑账号 ${draft.account_name}（${env}）`
            : `新增账号（${env}）`
        }
        open={editorOpen && draft !== null}
        onCancel={close}
        destroyOnClose
        footer={
          <Space>
            <Button onClick={close}>取消</Button>
            <Button
              type="primary"
              loading={saving}
              data-testid="account-save"
              onClick={() => {
                void save()
              }}
            >
              保存账号
            </Button>
          </Space>
        }
      >
        {draft ? (
          <div data-testid="account-editor">
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
                    onClick={() => {
                      void refresh()
                    }}
                  >
                    刷新
                  </Button>
                }
              />
            ) : null}
            {formError && !conflict ? (
              <Alert type="error" showIcon style={{ marginBottom: 12 }} message={formError} />
            ) : null}
            {profilesError ? (
              <Alert
                type="error"
                showIcon
                style={{ marginBottom: 12 }}
                message={formatErrorMessage(profilesError)}
                action={
                  <Button size="small" onClick={onRetryProfiles}>
                    重试
                  </Button>
                }
              />
            ) : null}
            {draft.mode === 'edit' && draft.revision !== null ? (
              <Typography.Paragraph data-testid="editing-revision">
                版本 {draft.revision}
              </Typography.Paragraph>
            ) : null}
            <Typography.Text>账号名</Typography.Text>
            <Input
              aria-label="账号名"
              style={{ margin: '4px 0 12px' }}
              value={draft.account_name}
              disabled={draft.mode === 'edit'}
              onChange={(event) => setDraft({ ...draft, account_name: event.target.value })}
            />
            <Typography.Text>展示名</Typography.Text>
            <Input
              aria-label="展示名"
              style={{ margin: '4px 0 12px' }}
              value={draft.display_name}
              onChange={(event) => setDraft({ ...draft, display_name: event.target.value })}
            />
            <Typography.Text>业务角色</Typography.Text>
            <Input
              aria-label="业务角色"
              style={{ margin: '4px 0 12px' }}
              value={draft.business_role}
              onChange={(event) => setDraft({ ...draft, business_role: event.target.value })}
            />
            <Typography.Paragraph style={{ marginBottom: 4 }}>登录流程</Typography.Paragraph>
            <Select
              aria-label="登录流程"
              data-testid="login-profile-select"
              style={{ width: '100%', marginBottom: 12 }}
              loading={profilesLoading}
              value={draft.login_profile || undefined}
              placeholder="选择 Git 登录流程"
              options={profiles.map((item) => ({ value: item.name, label: item.name }))}
              onChange={(value) => setDraft({ ...draft, login_profile: value })}
            />
            <Space style={{ marginBottom: 12 }}>
              <span>启用</span>
              <Switch
                aria-label="启用账号"
                checked={draft.enabled}
                onChange={(checked) => setDraft({ ...draft, enabled: checked })}
              />
            </Space>
            {draft.mode === 'edit' && revealed === null ? (
              <Button
                data-testid="reveal-credentials"
                loading={revealing}
                onClick={() => {
                  void reveal()
                }}
              >
                查看凭据
              </Button>
            ) : null}
            {showCredentialInputs ? (
              <div data-testid="credential-fields" style={{ marginTop: 12 }}>
                {draft.login_profile && profileFields.length === 0 ? (
                  <Typography.Text type="secondary">
                    该登录流程没有声明凭据字段。
                  </Typography.Text>
                ) : (
                  profileFields.map((field) => (
                    <div key={field} style={{ marginBottom: 8 }}>
                      <Typography.Text>{field}</Typography.Text>
                      <Input.Password
                        aria-label={field}
                        data-testid={`credential-${field}`}
                        style={{ marginTop: 4 }}
                        value={credentialDraft[field] ?? ''}
                        onChange={(event) =>
                          setCredentialDraft({
                            ...credentialDraft,
                            [field]: event.target.value,
                          })
                        }
                      />
                    </div>
                  ))
                )}
              </div>
            ) : (
              <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
                密码默认不显示。点击查看后可以显示和修改，保存时才提交变更。
              </Typography.Paragraph>
            )}
          </div>
        ) : null}
      </Modal>
    </div>
  )
}

function resolveCredentials(input: {
  mode: 'create' | 'edit'
  profileChanged: boolean
  fields: string[]
  revealed: Record<string, string> | null
  credentialDraft: Record<string, string>
}): { credentials?: Record<string, string> } | { error: string } {
  const { mode, profileChanged, fields, revealed, credentialDraft } = input
  if (mode === 'edit' && !profileChanged && revealed === null) {
    return {}
  }
  if (mode === 'edit' && profileChanged && revealed === null) {
    return { error: '更换登录流程后请先查看并填写凭据' }
  }
  if (fields.length === 0) {
    return { error: '该登录流程没有可填写的凭据字段' }
  }
  const next: Record<string, string> = {}
  for (const field of fields) {
    const value = credentialDraft[field] ?? ''
    const fieldError = validateCredentialValue(value)
    if (fieldError) {
      return { error: `${field}：${fieldError}` }
    }
    next[field] = value
  }
  if (mode === 'edit' && revealed && !profileChanged && sameCredentials(next, pickFields(revealed, fields))) {
    return {}
  }
  return { credentials: next }
}

function pickFields(source: Record<string, string>, fields: string[]): Record<string, string> {
  const picked: Record<string, string> = {}
  for (const field of fields) {
    picked[field] = source[field] ?? ''
  }
  return picked
}
