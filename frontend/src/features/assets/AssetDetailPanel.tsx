import { Card, Descriptions, Empty, Tag, Typography } from 'antd'
import { ApiHttpError } from '@/shared/api/errors'
import { ErrorState, LoadingState } from '@/shared/ui/AsyncState'
import type { AssetDetails, AssetNode } from './types'
import { isRunnableApiAsset, isRunnableCaseAsset } from './treeUtils'

interface AssetDetailPanelProps {
  selectedFromTree: AssetNode | null
  details: AssetDetails | undefined
  detailsLoading: boolean
  detailsError: unknown
  onRetryDetails: () => void
}

function formatMetadataValue(value: unknown): string {
  if (value === null || value === undefined) {
    return '—'
  }
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

/** 优先展示常见字段，其余 metadata 原文列出，避免假定结构 */
const PREFERRED_META_KEYS = [
  'method',
  'url',
  'host',
  'desc',
  'description',
  'name',
  'id',
  'api_id',
  'type',
]

export function AssetDetailPanel({
  selectedFromTree,
  details,
  detailsLoading,
  detailsError,
  onRetryDetails,
}: AssetDetailPanelProps) {
  if (!selectedFromTree) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="选择左侧资产以查看元信息"
      />
    )
  }

  const isDirectory = selectedFromTree.type === 'directory'
  const display = isDirectory ? selectedFromTree : (details ?? selectedFromTree)
  const runnableApi = isRunnableApiAsset(selectedFromTree)
  const runnableCase = isRunnableCaseAsset(selectedFromTree)
  const runnable = runnableApi || runnableCase

  if (!isDirectory && detailsLoading && !details) {
    return <LoadingState tip="加载资产详情…" />
  }

  if (!isDirectory && detailsError) {
    const is404 =
      detailsError instanceof ApiHttpError && detailsError.status === 404
    return (
      <ErrorState
        title={is404 ? '资产不存在' : '加载详情失败'}
        error={detailsError}
        onRetry={onRetryDetails}
      />
    )
  }

  const metadata = display.metadata ?? null
  const metaEntries = metadata
    ? [
        ...PREFERRED_META_KEYS.filter((k) => k in metadata).map((k) => [k, metadata[k]] as const),
        ...Object.entries(metadata).filter(([k]) => !PREFERRED_META_KEYS.includes(k)),
      ]
    : []

  return (
    <div data-testid="asset-detail-panel">
      <Typography.Title level={5} style={{ marginTop: 0, marginBottom: 8 }}>
        {display.name}
      </Typography.Title>
      <div style={{ marginBottom: 12 }}>
        <Tag>{display.type === 'directory' ? '目录' : '文件'}</Tag>
        {display.type === 'file' ? (
          runnableApi ? (
            <Tag color="blue">可运行（api.*）</Tag>
          ) : runnableCase ? (
            <Tag color="blue">可运行（case.*）</Tag>
          ) : (
            <Tag>只读 · 当前不可运行</Tag>
          )
        ) : null}
      </div>

      <Descriptions size="small" column={1} bordered>
        <Descriptions.Item label="资产 ID">
          <Typography.Text copyable code>
            {display.id}
          </Typography.Text>
        </Descriptions.Item>
        <Descriptions.Item label="路径">
          <Typography.Text code style={{ wordBreak: 'break-all' }}>
            {display.path}
          </Typography.Text>
        </Descriptions.Item>
      </Descriptions>

      {isDirectory ? (
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
          目录仅供浏览，不请求参数或运行接口。
        </Typography.Paragraph>
      ) : null}

      {!isDirectory && !runnable ? (
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
          当前阶段仅 api.* / case.* 文件支持运行；本资产可查看元信息，无运行按钮。
        </Typography.Paragraph>
      ) : null}

      {!isDirectory && runnableApi ? (
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
          此文件可运行；执行面板由工作台集成层挂载，此处不提供运行按钮。
        </Typography.Paragraph>
      ) : null}

      {!isDirectory && runnableCase ? (
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
          Case 元信息与运行由工作台 Case 面板挂载；此处不渲染 YAML 或步骤预览。
        </Typography.Paragraph>
      ) : null}

      {!isDirectory ? (
        <Card
          size="small"
          title="元信息"
          style={{ marginTop: 12 }}
          styles={{ body: { padding: metaEntries.length ? 12 : 24 } }}
        >
          {metaEntries.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无元信息" />
          ) : (
            <Descriptions size="small" column={1}>
              {metaEntries.map(([key, value]) => {
                const text = formatMetadataValue(value)
                const multiline = text.includes('\n') || text.length > 80
                return (
                  <Descriptions.Item key={key} label={key}>
                    {multiline ? (
                      <Typography.Paragraph
                        style={{
                          marginBottom: 0,
                          whiteSpace: 'pre-wrap',
                          fontFamily: 'ui-monospace, monospace',
                          fontSize: 12,
                          maxHeight: 240,
                          overflow: 'auto',
                        }}
                      >
                        {text}
                      </Typography.Paragraph>
                    ) : (
                      <Typography.Text code={typeof value !== 'object'}>
                        {text}
                      </Typography.Text>
                    )}
                  </Descriptions.Item>
                )
              })}
            </Descriptions>
          )}
        </Card>
      ) : null}
    </div>
  )
}
