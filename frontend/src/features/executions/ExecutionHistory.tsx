import {
  Button,
  Card,
  Descriptions,
  Drawer,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useEffect, useMemo, useState } from 'react'
import { ErrorState, EmptyState, LoadingState } from '@/shared/ui/AsyncState'
import { CaseResultView } from './CaseResultView'
import { apiAuthDisplayMode } from './auth'
import { AuthSummary } from './AuthSummary'
import { JsonBlock } from './JsonBlock'
import { LoginFailedBanner } from './LoginFailedBanner'
import { LoginProcessPanel } from './LoginProcessPanel'
import { isCacheReuseWithoutLogin } from './loginDisplay'
import {
  apiResultHasLoginFailed,
  caseHasLoginFailed,
  extractLoginsFromResult,
} from './loginDisplay'
import { RequestSnapshot } from './RequestSnapshot'
import { useCaseExecutionRecord, useExecutionRecord, useExecutionRecords } from './hooks'
import {
  formatDurationSeconds,
  runStatusColor,
  runStatusLabel,
} from './statusLabel'
import type {
  CaseExecutionRecordDetail,
  ExecutionHistoryProps,
  ExecutionRecordDetail,
  ExecutionRecordListItem,
} from './types'

const DEFAULT_LIMIT = 20

const STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'success', label: 'success' },
  { value: 'failed', label: 'failed' },
]

const ASSET_TYPE_OPTIONS = [
  { value: '', label: '全部类型' },
  { value: 'api', label: 'api' },
  { value: 'case', label: 'case' },
]

const ORDER_OPTIONS = [
  { value: '-start_time', label: '开始时间 ↓' },
  { value: 'start_time_asc', label: '开始时间 ↑' },
  { value: '-duration', label: '耗时 ↓' },
  { value: 'duration', label: '耗时 ↑' },
  { value: 'status', label: '状态' },
  { value: 'asset_id', label: '资产 ID' },
]

function useDrawerWidth(preferred = 560): number {
  const [width, setWidth] = useState(preferred)
  useEffect(() => {
    const update = () => {
      const vw = window.innerWidth
      setWidth(Math.min(preferred, Math.max(280, vw - 24)))
    }
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [preferred])
  return width
}

function isCaseAssetId(assetId: string): boolean {
  return assetId.startsWith('case.')
}

/**
 * 项目执行历史：筛选、分页（无 total，条数 < limit 判末页）、详情抽屉。
 * Case 记录走类型化详情端点；旧 API 记录仍走通用详情，不回退。
 */
export function ExecutionHistory({ projectId, assetId }: ExecutionHistoryProps) {
  const [status, setStatus] = useState<string>('')
  const [assetType, setAssetType] = useState<string>('')
  const [orderBy, setOrderBy] = useState('-start_time')
  const [page, setPage] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selectedAssetId, setSelectedAssetId] = useState<string | null>(null)
  const drawerWidth = useDrawerWidth(560)

  useEffect(() => {
    setPage(0)
    setSelectedId(null)
    setSelectedAssetId(null)
  }, [projectId, assetId, status, assetType, orderBy])

  const query = useMemo(
    () => ({
      skip: page * DEFAULT_LIMIT,
      limit: DEFAULT_LIMIT,
      status: status || undefined,
      asset_id: assetId || undefined,
      asset_type: (assetType === 'api' || assetType === 'case'
        ? assetType
        : undefined) as 'api' | 'case' | undefined,
      order_by: orderBy,
    }),
    [page, status, assetId, assetType, orderBy],
  )

  const listQuery = useExecutionRecords(projectId, query)
  const selectedIsCase = Boolean(selectedAssetId && isCaseAssetId(selectedAssetId))
  const apiDetailQuery = useExecutionRecord(
    projectId,
    selectedIsCase ? null : selectedId,
  )
  const caseDetailQuery = useCaseExecutionRecord(
    projectId,
    selectedIsCase ? selectedId : null,
  )

  const rows = listQuery.data ?? []
  // 列表无 total：返回条数 < limit 即末页；空页（越界）也视为末页
  const isLastPage = rows.length < DEFAULT_LIMIT
  const hasPrev = page > 0
  const showPager = !listQuery.isLoading && !listQuery.isError && (rows.length > 0 || page > 0)
  const showEmptyFirstPage =
    !listQuery.isLoading && !listQuery.isError && rows.length === 0 && page === 0
  const showEmptyBeyond =
    !listQuery.isLoading && !listQuery.isError && rows.length === 0 && page > 0

  const columns: ColumnsType<ExecutionRecordListItem> = [
    {
      title: '运行 ID',
      dataIndex: 'id',
      key: 'id',
      width: 120,
      ellipsis: true,
      render: (value: string) => (
        <Typography.Text code copyable={{ text: value }} style={{ maxWidth: 110 }}>
          {value}
        </Typography.Text>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      render: (value: string, record: ExecutionRecordListItem) => (
        <Space wrap size={[4, 4]}>
          <Tag color={runStatusColor(value)}>
            {runStatusLabel(value)}（{value}）
          </Tag>
          {record.login_failed ? (
            <Tag className="tp-login-failed-tag" data-testid={`history-login-failed-${record.id}`}>
              登录失败
            </Tag>
          ) : null}
        </Space>
      ),
    },
    {
      title: '资产 ID',
      dataIndex: 'asset_id',
      key: 'asset_id',
      ellipsis: true,
      render: (value: string) => (
        <Typography.Text code style={{ wordBreak: 'break-all' }}>
          {value}
        </Typography.Text>
      ),
    },
    {
      title: '开始时间',
      dataIndex: 'start_time',
      key: 'start_time',
      width: 160,
      render: (value: string) => formatTime(value),
    },
    {
      title: '耗时',
      dataIndex: 'duration',
      key: 'duration',
      width: 80,
      render: (value: number | null) => formatDurationSeconds(value),
    },
    {
      title: '操作',
      key: 'actions',
      width: 72,
      fixed: 'right',
      render: (_: unknown, record) => (
        <Button
          type="link"
          size="small"
          style={{ paddingInline: 0 }}
          onClick={() => {
            setSelectedId(record.id)
            setSelectedAssetId(record.asset_id)
          }}
          aria-label={`查看记录 ${record.id}`}
        >
          详情
        </Button>
      ),
    },
  ]

  const pager = (
    <Space
      style={{ marginTop: 12, width: '100%', justifyContent: 'flex-end' }}
      data-testid="execution-history-pager"
    >
      <Button
        disabled={!hasPrev || listQuery.isFetching}
        onClick={() => setPage((p) => Math.max(0, p - 1))}
        aria-label="上一页"
      >
        上一页
      </Button>
      <Typography.Text type="secondary">第 {page + 1} 页</Typography.Text>
      <Button
        disabled={isLastPage || listQuery.isFetching}
        onClick={() => setPage((p) => p + 1)}
        aria-label="下一页"
      >
        下一页
      </Button>
    </Space>
  )

  const detailLoading = selectedIsCase
    ? caseDetailQuery.isLoading
    : apiDetailQuery.isLoading
  const detailError = selectedIsCase ? caseDetailQuery.error : apiDetailQuery.error
  const detailRetry = () => {
    if (selectedIsCase) {
      void caseDetailQuery.refetch()
    } else {
      void apiDetailQuery.refetch()
    }
  }

  return (
    <Card
      size="small"
      title="执行历史"
      data-testid="execution-history"
      styles={{ body: { overflowX: 'auto', maxWidth: '100%' } }}
      extra={
        assetId ? (
          <Typography.Text type="secondary" code style={{ wordBreak: 'break-all' }}>
            {assetId}
          </Typography.Text>
        ) : null
      }
    >
      <Space wrap style={{ marginBottom: 12 }}>
        <Select
          style={{ width: 140 }}
          value={status}
          options={STATUS_OPTIONS}
          onChange={(value) => setStatus(value)}
          aria-label="按状态筛选"
          data-testid="filter-status"
        />
        <Select
          style={{ width: 140 }}
          value={assetType}
          options={ASSET_TYPE_OPTIONS}
          onChange={(value) => setAssetType(value)}
          aria-label="按资产类型筛选"
          data-testid="filter-asset-type"
        />
        <Select
          style={{ width: 160 }}
          value={orderBy}
          options={ORDER_OPTIONS}
          onChange={(value) => setOrderBy(value)}
          aria-label="排序"
          data-testid="filter-order"
        />
      </Space>

      {listQuery.isLoading ? <LoadingState tip="加载执行记录…" /> : null}

      {listQuery.isError ? (
        <ErrorState
          error={listQuery.error}
          title="历史加载失败"
          onRetry={() => {
            void listQuery.refetch()
          }}
        />
      ) : null}

      {showEmptyFirstPage ? <EmptyState description="暂无执行记录" /> : null}

      {showEmptyBeyond ? (
        <>
          <EmptyState description="本页无记录，可返回上一页" />
          {pager}
        </>
      ) : null}

      {!listQuery.isLoading && !listQuery.isError && rows.length > 0 ? (
        <>
          <Table
            size="small"
            rowKey="id"
            columns={columns}
            dataSource={rows}
            pagination={false}
            scroll={{ x: 640 }}
          />
          {showPager ? pager : null}
        </>
      ) : null}

      <Drawer
        title={selectedIsCase ? 'Case 执行详情' : '执行详情'}
        open={Boolean(selectedId)}
        onClose={() => {
          setSelectedId(null)
          setSelectedAssetId(null)
        }}
        width={drawerWidth}
        destroyOnClose
        styles={{
          body: { overflowX: 'auto', maxWidth: '100%' },
          wrapper: { maxWidth: '100vw' },
        }}
      >
        {detailLoading ? <LoadingState tip="加载详情…" /> : null}
        {detailError ? (
          <ErrorState
            error={detailError}
            title="详情加载失败"
            onRetry={detailRetry}
          />
        ) : null}
        {selectedIsCase && caseDetailQuery.data ? (
          <CaseDetailBody detail={caseDetailQuery.data} />
        ) : null}
        {!selectedIsCase && apiDetailQuery.data ? (
          <ApiDetailBody detail={apiDetailQuery.data} />
        ) : null}
      </Drawer>
    </Card>
  )
}

function CaseDetailBody({ detail }: { detail: CaseExecutionRecordDetail }) {
  return (
    <div data-testid="execution-detail" data-asset-type="case" style={{ maxWidth: '100%', overflowX: 'hidden' }}>
      <Descriptions size="small" column={1} style={{ marginBottom: 16 }}>
        <Descriptions.Item label="运行 ID">
          <Typography.Text copyable code style={{ wordBreak: 'break-all' }}>
            {detail.id}
          </Typography.Text>
        </Descriptions.Item>
        <Descriptions.Item label="资产 ID">
          <Typography.Text code style={{ wordBreak: 'break-all' }}>
            {detail.asset_id}
          </Typography.Text>
        </Descriptions.Item>
        <Descriptions.Item label="类型">
          <Tag>case</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="状态">
          <Space wrap size={[8, 4]}>
            <Tag color={runStatusColor(detail.status)}>
              {runStatusLabel(detail.status)}（{detail.status}）
            </Tag>
            {detail.result && caseHasLoginFailed(detail.result) ? (
              <Tag className="tp-login-failed-tag" data-testid="history-case-login-failed-marker">
                登录失败
              </Tag>
            ) : null}
          </Space>
        </Descriptions.Item>
        <Descriptions.Item label="开始">
          {detail.display.start_time}
        </Descriptions.Item>
        <Descriptions.Item label="结束">
          {detail.display.end_time ?? '—'}
        </Descriptions.Item>
        <Descriptions.Item label="耗时">
          {detail.display.duration ?? '—'}
        </Descriptions.Item>
      </Descriptions>

      {detail.result ? (
        <CaseResultView result={detail.result} recordId={detail.id} />
      ) : (
        <Typography.Paragraph type="secondary">
          存档缺失或无法按 CaseResult 解析（result 为 null）。
        </Typography.Paragraph>
      )}
    </div>
  )
}

function ApiDetailBody({ detail }: { detail: ExecutionRecordDetail }) {
  const parseError =
    detail.result &&
    typeof detail.result === 'object' &&
    'parse_error' in detail.result
      ? String((detail.result as { parse_error: unknown }).parse_error)
      : null
  const loginFailed = apiResultHasLoginFailed(detail.result)
  const logins = extractLoginsFromResult(detail.result)
  const errorValue =
    detail.result && typeof detail.result === 'object'
      ? (detail.result as Record<string, unknown>).error
      : null
  const errorObj =
    errorValue && typeof errorValue === 'object' && !Array.isArray(errorValue)
      ? (errorValue as Record<string, unknown>)
      : null
  const loginMeta =
    errorObj?.login && typeof errorObj.login === 'object' && !Array.isArray(errorObj.login)
      ? (errorObj.login as Record<string, unknown>)
      : null
  const requestRaw =
    detail.request ??
    (detail.result && typeof detail.result === 'object'
      ? (detail.result as Record<string, unknown>).request
      : null)
  const requestForSnapshot =
    requestRaw && typeof requestRaw === 'object' && !Array.isArray(requestRaw)
      ? {
          method:
            typeof (requestRaw as Record<string, unknown>).method === 'string'
              ? String((requestRaw as Record<string, unknown>).method)
              : '—',
          url:
            typeof (requestRaw as Record<string, unknown>).url === 'string'
              ? String((requestRaw as Record<string, unknown>).url)
              : typeof (requestRaw as Record<string, unknown>).api_id === 'string'
                ? String((requestRaw as Record<string, unknown>).api_id)
                : '—',
          headers:
            (requestRaw as Record<string, unknown>).headers &&
            typeof (requestRaw as Record<string, unknown>).headers === 'object'
              ? ((requestRaw as Record<string, unknown>).headers as Record<string, unknown>)
              : undefined,
          body: (requestRaw as Record<string, unknown>).body,
          body_type:
            typeof (requestRaw as Record<string, unknown>).body_type === 'string'
              ? String((requestRaw as Record<string, unknown>).body_type)
              : 'json',
          query:
            (requestRaw as Record<string, unknown>).query &&
            typeof (requestRaw as Record<string, unknown>).query === 'object'
              ? ((requestRaw as Record<string, unknown>).query as Record<string, unknown>)
              : null,
        }
      : null

  return (
    <div
      data-testid="execution-detail"
      data-asset-type="api"
      data-login-failed={loginFailed ? 'true' : 'false'}
      style={{ maxWidth: '100%', overflowX: 'hidden' }}
    >
      <Descriptions size="small" column={1} style={{ marginBottom: 16 }}>
        <Descriptions.Item label="运行 ID">
          <Typography.Text copyable code style={{ wordBreak: 'break-all' }}>
            {detail.id}
          </Typography.Text>
        </Descriptions.Item>
        <Descriptions.Item label="资产 ID">
          <Typography.Text code style={{ wordBreak: 'break-all' }}>
            {detail.asset_id}
          </Typography.Text>
        </Descriptions.Item>
        <Descriptions.Item label="类型">
          <Tag>{detail.asset_type}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="状态">
          <Space wrap size={[8, 4]}>
            <Tag color={runStatusColor(detail.status)}>
              {runStatusLabel(detail.status)}（{detail.status}）
            </Tag>
            {loginFailed ? (
              <Tag className="tp-login-failed-tag" data-testid="history-api-login-failed-marker">
                登录失败
              </Tag>
            ) : null}
          </Space>
        </Descriptions.Item>
        <Descriptions.Item label="开始">
          {detail.display.start_time}
        </Descriptions.Item>
        <Descriptions.Item label="结束">
          {detail.display.end_time ?? '—'}
        </Descriptions.Item>
        <Descriptions.Item label="耗时">
          {detail.display.duration ?? '—'}
        </Descriptions.Item>
        {/* API 历史详情：顶层 auth，null（含 3.3 之前的旧记录）即匿名 */}
        <Descriptions.Item label="身份">
          <AuthSummary
            auth={detail.auth ?? null}
            mode={apiAuthDisplayMode(detail.auth ?? null)}
          />
        </Descriptions.Item>
      </Descriptions>

      {loginFailed && errorObj && typeof errorObj.message === 'string' ? (
        <div style={{ marginBottom: 12 }}>
          <LoginFailedBanner
            message={errorObj.message}
            reason={typeof loginMeta?.reason === 'string' ? loginMeta.reason : null}
            failedStep={
              typeof loginMeta?.failed_step === 'string' ? loginMeta.failed_step : null
            }
            identity={
              typeof loginMeta?.identity === 'string'
                ? loginMeta.identity
                : detail.auth?.identity
            }
          />
        </div>
      ) : null}

      {logins.length > 0 ? (
        <div style={{ marginBottom: 16 }}>
          <LoginProcessPanel
            logins={logins}
            defaultExpanded={loginFailed}
            highlightRef={detail.auth?.login_ref ?? null}
          />
        </div>
      ) : isCacheReuseWithoutLogin(detail.auth) ? (
        <Typography.Text
          type="secondary"
          data-testid="login-cache-reuse-note"
          style={{ display: 'block', marginBottom: 16 }}
        >
          复用登录（未重新登录），本次无登录过程可查看
        </Typography.Text>
      ) : null}

      {parseError ? (
        <Typography.Paragraph type="danger">
          结果解析失败：{parseError}
        </Typography.Paragraph>
      ) : null}

      <Typography.Text strong>Request</Typography.Text>
      {requestForSnapshot ? (
        <RequestSnapshot request={requestForSnapshot} ariaLabel="详情 request" />
      ) : (
        <JsonBlock value={detail.request} aria-label="详情 request" />
      )}

      <Typography.Text strong style={{ display: 'block', marginTop: 12 }}>
        Response
      </Typography.Text>
      <JsonBlock value={detail.response} aria-label="详情 response" />

      <Typography.Text strong style={{ display: 'block', marginTop: 12 }}>
        Result
      </Typography.Text>
      <JsonBlock value={detail.result} aria-label="详情 result" />
    </div>
  )
}

function formatTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString('zh-CN', { hour12: false })
}
