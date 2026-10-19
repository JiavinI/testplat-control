import { Input, Table, Tag, Typography } from 'antd'
import { useState } from 'react'
import { formatParameterValue, resolveParameterValues, validParameterDefault } from './parameterValues'
import type { ParameterContext, ParamInfo } from './types'

const labels = { asset: '资产默认值（Git）', saved: '页面保存的默认值', environment: '环境覆盖（兼容共享）', override: '当前资产环境覆盖', temporary: '本次输入', unset: '未设置' }

export function ParameterPreview({ assetDefaults, caseParams, temporary, params, env, context }: {
  context?: ParameterContext
  assetDefaults?: Record<string, unknown>
  caseParams?: Record<string, unknown>
  temporary?: Record<string, unknown>
  params?: ParamInfo[]
  env: string
}) {
  const [search, setSearch] = useState('')
  const rows = resolveParameterValues(context?.git_defaults ?? assetDefaults, context?.shared_environment ?? caseParams, temporary, params?.map((item) => item.name), context?.asset_default.values, context?.environment_override.values)
  const valueColumn = (title: string, key: 'asset' | 'saved' | 'environment' | 'override' | 'temporary') => ({
    title, key,
    render: (_: unknown, row: typeof rows[number]) => <span className="tp-parameter-value">{formatParameterValue(row.name, row[key])}</span>,
  })
  return (
    <section data-testid="parameter-preview" style={{ margin: '16px 0' }}>
      <Typography.Title level={5}>参数生效预览 · {env}</Typography.Title>
      <Typography.Paragraph type="secondary">
        {context ? 'Git 默认值 → 页面默认值 → 兼容共享环境值 → 当前资产环境覆盖 → 本次输入。' : '资产默认值 → 环境覆盖 → 本次输入。'}仅按顶层键替换，本次输入不会自动保存。
        这里展示模板输入参数；最终请求值与类型由接口模板渲染决定，以执行后的请求展示为准。
      </Typography.Paragraph>
      {context ? <Typography.Paragraph type="secondary">先查看生效值与来源，横向滚动可比较各层配置。</Typography.Paragraph> : null}
      {rows.length > 10 ? <Input.Search aria-label="查找参数" allowClear placeholder="按参数名查找" value={search} onChange={(event) => setSearch(event.target.value)} style={{ maxWidth: 320, marginBottom: 8 }} /> : null}
      <Table
        size="small"
        rowKey="name"
        pagination={false}
        scroll={{ x: context ? 1050 : 720 }}
        dataSource={rows.filter((row) => row.name.toLowerCase().includes(search.toLowerCase()))}
        locale={{ emptyText: '没有可预览的参数' }}
        columns={[
          { title: '参数', dataIndex: 'name', key: 'name', width: 110 },
          {
            title: '生效值与来源', key: 'effective', width: 190,
            render: (_: unknown, row: typeof rows[number]) => {
              const spec = params?.find((item) => item.name === row.name)
              const invalid = spec && row.source !== 'unset' && !validParameterDefault(spec, row)
              return <div data-testid={`parameter-effective-${row.name}`}>
                <span className="tp-parameter-value">{formatParameterValue(row.name, row.effective)}</span>
                <div><Tag color={invalid ? 'error' : undefined}>{labels[row.source]}</Tag>{invalid ? <Typography.Text type="danger">类型不匹配，请覆盖为 {spec.type}</Typography.Text> : null}</div>
              </div>
            },
          },
          valueColumn('资产默认值', 'asset'),
          ...(context ? [valueColumn('页面默认值', 'saved')] : []),
          valueColumn('环境覆盖', 'environment'),
          ...(context ? [valueColumn('当前资产环境覆盖', 'override')] : []),
          valueColumn('本次输入', 'temporary'),
        ]}
      />
    </section>
  )
}
