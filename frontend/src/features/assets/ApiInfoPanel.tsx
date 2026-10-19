import { Alert, Button, Collapse, Descriptions, Space, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import type { AssetDetails, AssetNode } from './types'
import type { ProjectEnvironment } from '@/features/environments/types'
import { sectionPath } from '@/shared/project/sections'
import { JsonBlock } from '@/features/executions/JsonBlock'

/** URL 拼接与 Engine 一致：去掉服务地址尾部斜杠，再拼接口路径。 */
export function ApiInfoPanel({ asset, environment, projectId }: {
  asset: AssetNode | AssetDetails
  environment?: ProjectEnvironment
  projectId: string
}) {
  const metadata = asset.metadata ?? {}
  const host = typeof metadata.host === 'string' ? metadata.host : ''
  const path = typeof metadata.url === 'string' ? metadata.url : ''
  const base = environment?.api_hosts[host]
  const fullUrl = base && path ? `${base.replace(/\/+$/, '')}${path}` : null
  const name = typeof metadata.name === 'string' ? metadata.name : asset.name
  const description = metadata.description ?? metadata.desc

  return (
    <div data-testid="api-info-panel">
      <Typography.Title level={4} style={{ margin: '0 0 12px' }}>{name}</Typography.Title>
      <Space wrap style={{ marginBottom: 12 }}>
        <Tag color={metadata.method === 'GET' ? 'green' : 'blue'}>{String(metadata.method ?? '—')}</Tag>
        <Typography.Text code style={{ overflowWrap: 'anywhere' }}>{path || '未定义路径'}</Typography.Text>
        <Typography.Text type="secondary">调用身份由本次调试或场景步骤选择</Typography.Text>
      </Space>
      {typeof description === 'string' ? <Typography.Paragraph>{description}</Typography.Paragraph> : null}
      {fullUrl ? (
        <div className="tp-api-url" data-testid="api-full-url">
          <Typography.Text type="secondary">{environment?.env} · {host}</Typography.Text>
          <Typography.Text copyable style={{ overflowWrap: 'anywhere', fontFamily: 'monospace' }}>{fullUrl}</Typography.Text>
        </div>
      ) : (
        <Alert
          type="warning" showIcon
          message={!environment ? '选择环境后查看完整 URL' : !host || !path ? '接口缺少 host 或路径定义' : `环境 ${environment.env} 未配置服务地址：${host}`}
          action={<Link to={`${sectionPath('configuration', projectId)}?tab=environments`}><Button size="small">配置环境</Button></Link>}
        />
      )}
      <Collapse ghost size="small" style={{ marginTop: 8 }} items={[{
        key: 'source', label: '接口源定义', children: <>
          <Descriptions size="small" column={1}>
            <Descriptions.Item label="接口 ID">{asset.id}</Descriptions.Item>
            <Descriptions.Item label="源文件">{asset.path}</Descriptions.Item>
          </Descriptions>
          <JsonBlock value={metadata} aria-label="接口源定义" />
        </>,
      }]} />
    </div>
  )
}
