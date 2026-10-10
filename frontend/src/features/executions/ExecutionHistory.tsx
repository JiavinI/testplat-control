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
import { JsonBlock } from './JsonBlock'
import { useExecutionRecord, useExecutionRecords } from './hooks'
import type {
  ExecutionHistoryProps,
  ExecutionRecordListItem,
} from './types'

const DEFAULT_LIMIT = 20

const STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'success', label: 'success' },
  { value: 'failed', label: 'failed' },
]

const ORDER_OPTIONS = [
  { value: '-start_time', label: '开始时间 ↓' },
  { value: 'start_time_asc', label: '开始时间 ↑' },
  { value: '-duration', label: '耗时 ↓' },
  { value: 'duration', label: '耗时 ↑' },
  { value: 'status', label: '状态' },
  { value: 'asset_id', label: '资产 ID' },
]

/**
 * 项目执行历史：筛选、分页（无 total，条数 < limit 判末页）、详情抽屉。
 */
export function ExecutionHistory({ projectId, assetId }: ExecutionHistoryProps) {
  const [status, setStatus] = useState<string>('')
  const [orderBy, setOrderBy] = useState('-start_time')
  const [page, setPage] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  // 外部 assetId 变化时重置分页与选中，并同步筛选
  useEffect(() => {
    setPage(0)
    setSelectedId(null)
  }, [projectId, assetId, status, orderBy])

  const query = useMemo(
    () => ({
      skip: page * DEFAULT_LIMIT,
      limit: DEFAULT_LIMIT,
      status: status || undefined,
      asset_id: assetId || undefined,
      order_by: orderBy,
    }),
    [page, status, assetId, orderBy],
  )

  const listQuery = useExecutionRecords(projectId, query)
  const detailQuery = useExecutionRecord(projectId, selectedId)

  const rows = listQuery.data ?? []
  // 列表无 total：返回条数 < limit 即末页
  const isLastPage = rows.length < DEFAULT_LIMIT
  const hasPrev = page > 0

  const columns: ColumnsType<ExecutionRecordListItem> = [
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (value: string) => (
        <Tag color={value === 'success' ? 'success' : value === 'failed' ? 'error' : 'default'}>
          {value}
        </Tag>
      ),
    },
    {
      title: '资产 ID',
      dataIndex: 'asset_id',
      key: 'asset_id',
      ellipsis: true,
      render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
    },
    {
      title: '开始时间',
      dataIndex: 'start_time',
      key: 'start_time',
      width: 180,
      render: (value: string) => formatTime(value),
    },
    {
      title: '耗时',
      dataIndex: 'duration',
      key: 'duration',
      width: 90,
      render: (value: number | null) => formatDuration(value),
    },
    {
      title: '操作',
      key: 'actions',
      width: 88,
      render: (_: unknown, record) => (
        <Button
          type="link"
          size="small"
          style={{ paddingInline: 0 }}
          onClick={() => setSelectedId(record.id)}
          aria-label={`查看记录 ${record.id}`}
        >
          详情
        </Button>
      ),
    },
  ]

  return (
    <Card
      size="small"
      title="执行历史"
      data-testid="execution-history"
      styles={{ body: { overflowX: 'auto', maxWidth: '100%' } }}
      extra={
        assetId ? (
          <Typography.Text type="secondary" code>
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

      {!listQuery.isLoading && !listQuery.isError && rows.length === 0 ? (
        <EmptyState description="暂无执行记录" />
      ) : null}

      {!listQuery.isLoading && !listQuery.isError && rows.length > 0 ? (
        <>
          <Table
            size="small"
            rowKey="id"
            columns={columns}
            dataSource={rows}
            pagination={false}
            scroll={{ x: true }}
          />
          <Space style={{ marginTop: 12, width: '100%', justifyContent: 'flex-end' }}>
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
        </>
      ) : null}

      <Drawer
        title="执行详情"
        open={Boolean(selectedId)}
        onClose={() => setSelectedId(null)}
        width={560}
        destroyOnClose
      >
        {detailQuery.isLoading ? <LoadingState tip="加载详情…" /> : null}
        {detailQuery.isError ? (
          <ErrorState
            error={detailQuery.error}
            title="详情加载失败"
            onRetry={() => {
              void detailQuery.refetch()
            }}
          />
        ) : null}
        {detailQuery.data ? <DetailBody detail={detailQuery.data} /> : null}
      </Drawer>
    </Card>
  )
}

function DetailBody({
  detail,
}: {
  detail: NonNullable<ReturnType<typeof useExecutionRecord>['data']>
}) {
  const parseError =
    detail.result &&
    typeof detail.result === 'object' &&
    'parse_error' in detail.result
      ? String((detail.result as { parse_error: unknown }).parse_error)
      : null

  return (
    <div data-testid="execution-detail">
      <Descriptions size="small" column={1} style={{ marginBottom: 16 }}>
        <Descriptions.Item label="记录 ID">
          <Typography.Text copyable code>
            {detail.id}
          </Typography.Text>
        </Descriptions.Item>
        <Descriptions.Item label="资产 ID">
          <Typography.Text code>{detail.asset_id}</Typography.Text>
        </Descriptions.Item>
        <Descriptions.Item label="状态">
          <Tag color={detail.status === 'success' ? 'success' : 'error'}>
            {detail.status}
          </Tag>
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

      {parseError ? (
        <Typography.Paragraph type="danger">
          结果解析失败：{parseError}
        </Typography.Paragraph>
      ) : null}

      <Typography.Text strong>Request</Typography.Text>
      <JsonBlock value={detail.request} aria-label="详情 request" />

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

function formatDuration(seconds: number | null): string {
  if (seconds === null || Number.isNaN(seconds)) {
    return '—'
  }
  if (seconds < 1) {
    return `${Math.round(seconds * 1000)}ms`
  }
  return `${seconds.toFixed(2)}s`
}
