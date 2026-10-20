import { useEffect, useMemo, useState } from 'react'
import { Button, Drawer, Input, InputNumber, Modal, Segmented, Select, Space, Tag, Typography } from 'antd'
import { useSearchParams } from 'react-router-dom'
import { ArrowLeftOutlined, ArrowRightOutlined, CodeOutlined, PlayCircleOutlined, SettingOutlined } from '@ant-design/icons'
import type { AssetNode } from '@/features/assets'
import type { ScenarioDefinition, ScenarioStepDefinition } from './types'
import './ScenarioWorkbenchPrototype.css'

type Props = { definition: ScenarioDefinition; assets: AssetNode[]; env: string; projectId: string; commit: string }
type Row = { step: ScenarioStepDefinition; number: string; parent?: string }

function assetIndex(nodes: AssetNode[], result = new Map<string, AssetNode>()) {
  for (const node of nodes) {
    result.set(node.id, node)
    if (node.children) assetIndex(node.children, result)
  }
  return result
}

function flatten(steps: ScenarioStepDefinition[], prefix = ''): Row[] {
  return steps.flatMap((step, index) => {
    const number = prefix ? `${prefix}.${index + 1}` : `${index + 1}`
    const row = { step, number, parent: prefix || undefined }
    return [row, ...(step.definition ? flatten(step.definition.steps, number) : [])]
  })
}

function setAt(source: Record<string, unknown>, path: string, value: unknown): Record<string, unknown> {
  const [head, ...tail] = path.split('.')
  if (!head) return source
  return { ...source, [head]: tail.length ? setAt((source[head] as Record<string, unknown>) ?? {}, tail.join('.'), value) : value }
}

function fields(value: unknown, prefix = ''): Array<{ path: string; value: unknown }> {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return Object.entries(value).flatMap(([key, child]) => fields(child, prefix ? `${prefix}.${key}` : key))
  }
  return [{ path: prefix, value }]
}

// Three throwaway layouts on the existing scenario route; all mutations stay in memory.

export default function ScenarioWorkbenchPrototype({ definition, assets, env, projectId, commit }: Props) {
  const [searchParams, setSearchParams] = useSearchParams()
  const variant = ['A', 'B', 'C'].includes(searchParams.get('variant') ?? '') ? searchParams.get('variant')! : 'A'
  const [params, setParams] = useState(definition.params)
  const [drawer, setDrawer] = useState(false)
  const [jsonMode, setJsonMode] = useState(false)
  const [jsonText, setJsonText] = useState(JSON.stringify(definition.params, null, 2))
  const [jsonError, setJsonError] = useState('')
  const [showDetails, setShowDetails] = useState<string | null>(null)
  const [ran, setRan] = useState(false)
  const [snapshot, setSnapshot] = useState<Record<string, unknown> | null>(null)
  const [inspected, setInspected] = useState('1')
  const [collapsed, setCollapsed] = useState<string[]>([])
  const [mode, setMode] = useState('我的草稿')
  const [savedDraft, setSavedDraft] = useState(definition.params)
  const [teamParams, setTeamParams] = useState(definition.params)
  const [publish, setPublish] = useState(false)
  const [schemeName, setSchemeName] = useState('回归数据')
  const index = useMemo(() => assetIndex(assets), [assets])
  const rows = useMemo(() => flatten(definition.steps), [definition.steps])

  const changeVariant = (next: string) => {
    const updated = new URLSearchParams(searchParams)
    updated.set('variant', next)
    setSearchParams(updated, { replace: true })
  }
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target
      if (target instanceof Element && target.closest('input,textarea,select,[contenteditable=true],[role=combobox]')) return
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
      event.preventDefault()
      const choices = ['A', 'B', 'C']
      const next = choices[(choices.indexOf(variant) + (event.key === 'ArrowRight' ? 1 : 2)) % 3]
      const updated = new URLSearchParams(searchParams); updated.set('variant', next)
      setSearchParams(updated, { replace: true })
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [searchParams, setSearchParams, variant])
  const changeValue = (path: string, value: unknown) => {
    const next = setAt(params, path, value)
    setParams(next)
    setJsonText(JSON.stringify(next, null, 2))
  }
  const saveJson = () => {
    try {
      const parsed: unknown = JSON.parse(jsonText)
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('请输入 JSON 对象')
      setParams(parsed as Record<string, unknown>); setJsonError(''); setJsonMode(false)
    } catch (error) { setJsonError(error instanceof Error ? error.message : 'JSON 格式无效') }
  }
  const titleFor = (row: Row) => row.step.name ?? row.step.definition?.name ?? String(index.get(row.step.asset_id)?.metadata?.name ?? index.get(row.step.asset_id)?.name ?? row.step.step_id)
  const editValue = (field: { path: string; value: unknown }) => {
    const label = `${field.path} 的值`
    if (typeof field.value === 'boolean') return <Select aria-label={label} value={field.value ? 'true' : 'false'} options={[{ value: 'true', label: '开启 · true' }, { value: 'false', label: '关闭 · false' }]} onChange={value => changeValue(field.path, value === 'true')} />
    if (typeof field.value === 'number') return <InputNumber aria-label={label} value={field.value} onChange={value => { if (value !== null) changeValue(field.path, value) }} style={{ width: '100%' }} />
    if (Array.isArray(field.value) || field.value === null) return <Input aria-label={label} readOnly value={JSON.stringify(field.value)} suffix={<Button type="link" size="small" onClick={() => setJsonMode(true)}>JSON</Button>} />
    return <Input aria-label={label} value={String(field.value ?? '')} onChange={event => changeValue(field.path, event.target.value)} />
  }
  const editButton = <Button icon={<SettingOutlined />} onClick={() => setDrawer(true)}>参数与数据</Button>
  const runButton = <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => { setSnapshot(structuredClone(params)); setRan(true) }}>模拟运行</Button>

  const stepRow = (row: Row, compact = false) => {
    const asset = index.get(row.step.asset_id)
    const isInspected = variant === 'B' && row.number === inspected
    return <div style={{ marginLeft: row.parent ? (row.number.split('.').length - 1) * 16 : 0 }} className={`sw-step ${compact ? 'sw-step--compact' : ''} ${isInspected ? 'sw-step--inspected' : ''}`} key={`${row.number}-${row.step.step_id}`}>
      <span className="sw-step-number">{row.number}</span>
      <div className="sw-step-main">
        <div className="sw-step-title"><strong>{titleFor(row)}</strong><Tag>{row.step.type === 'flow' ? '公共流程' : asset?.metadata?.method ? String(asset.metadata.method) : 'API'}</Tag>{row.step.identity ? <Tag color="blue">身份：{row.step.identity}</Tag> : <Tag>{row.step.type === 'flow' ? '身份见子步骤' : '未显式指定身份'}</Tag>}</div>
        <div className="sw-step-meta"><span>{row.step.asset_id}</span>{asset?.metadata?.url ? <span>{String(asset.metadata.method ?? 'GET')} {String(asset.metadata.url)}</span> : null}{row.step.output ? <span>输出：{row.step.output}</span> : null}</div>
      </div>
      <Space size={0}>{row.step.definition && variant !== 'B' ? <Button size="small" type="text" onClick={() => setCollapsed(previous => previous.includes(row.number) ? previous.filter(item => item !== row.number) : [...previous, row.number])}>{collapsed.includes(row.number) ? '展开子步骤' : '折叠子步骤'}</Button> : null}<Button type="link" size="small" onClick={() => setShowDetails(showDetails === row.number ? null : row.number)}>{showDetails === row.number ? '收起' : '详情'}</Button></Space>
      {showDetails === row.number ? <div className="sw-detail">
        <div className="sw-detail-target">
          <span className="sw-detail-label">{row.step.type === 'flow' ? '流程' : '请求'}</span>
          <code>{row.step.type === 'flow' ? row.step.asset_id : `${String(asset?.metadata?.method ?? '方法待解析')} ${String(asset?.metadata?.url ?? row.step.asset_id)}`}</code>
        </div>
        <div className="sw-detail-facts">
          <span className="sw-detail-label">登录身份</span><span>{row.step.identity ?? (row.step.type === 'flow' ? '由各子步骤分别指定' : '未显式指定，按接口配置')}</span>
          {row.step.output ? <><span className="sw-detail-label">结果别名</span><code>{row.step.output}</code></> : null}
        </div>
        <section className="sw-detail-section"><div className="sw-detail-section-title">输入映射 <span>{fields(row.step.params).length}</span></div>
          {fields(row.step.params).map(field => <div className="sw-binding" key={field.path}><code>{field.path}</code><span>←</span><code>{typeof field.value === 'string' ? field.value : JSON.stringify(field.value)}</code></div>)}
        </section>
        {row.step.definition ? <details className="sw-detail-section"><summary>流程输出契约 · {Object.keys(row.step.definition.outputs).length} 项</summary>{fields(row.step.definition.outputs).map(field => <div className="sw-binding" key={field.path}><code>{field.path}</code><span>←</span><code>{String(field.value)}</code></div>)}</details> : null}
        <details className="sw-detail-section"><summary>原始绑定 JSON</summary><pre>{JSON.stringify(row.step.params, null, 2)}</pre></details>
      </div> : null}
    </div>
  }

  const numbered = <div className="sw-steps">{rows.filter(row => !collapsed.some(number => row.number.startsWith(`${number}.`))).map(row => stepRow(row))}</div>
  const header = <div className="sw-runbar"><div><strong>{definition.name ?? definition.id}</strong><div className="sw-subtitle">{definition.id} · {env || '未选择环境'} · {mode === '我的草稿' ? '我的草稿' : '团队方案副本'}</div></div><Space>{editButton}{runButton}</Space></div>
  const result = ran ? <div className="sw-result"><strong>模拟结果</strong>{rows.map(row => <div key={row.number}><code>{row.number}</code> {titleFor(row)} <Tag color="success">成功</Tag></div>)}<details><summary>本次模拟输入快照</summary><pre>{JSON.stringify(snapshot, null, 2)}</pre></details></div> : null

  return <div className="sw-prototype">
    <div className="sw-prototype-banner" title={`${projectId} · ${commit}`}><Tag color="gold">交互原型</Tag><span>只模拟参数和结果，不发送请求、不保存配置</span></div>
    {variant === 'A' ? <>
      {header}
      <div className="sw-section-heading"><div><h3>执行步骤</h3><span>按顺序运行；子步骤使用父编号展开</span></div><Button type="link" onClick={() => setDrawer(true)}>参数方案：{mode} ▾</Button></div>
      {numbered}{result}
    </> : variant === 'B' ? <>
      <div className="sw-split-header">{header}</div><div className="sw-split">
        <nav className="sw-outline" aria-label="场景步骤目录"><h3>步骤目录</h3>{rows.map(row => {
          const stepAsset = index.get(row.step.asset_id)
          return <button key={row.number} className={`${row.parent ? 'is-child' : ''} ${row.number === inspected ? 'is-selected' : ''}`} aria-current={row.number === inspected ? 'step' : undefined} onClick={() => { setInspected(row.number); setShowDetails(row.number) }}><code>{row.number}</code><span>{titleFor(row)}<small>{row.step.type === 'flow' ? '公共流程' : stepAsset?.metadata?.method ? `${String(stepAsset.metadata.method)} 请求` : 'API 请求'}</small></span></button>
        })}</nav>
        <main className="sw-inspector-content">{rows.filter(row => row.number === inspected).map(row => stepRow(row))}{result}</main>
      </div>
    </> : <>
      <div className="sw-timeline-head"><div><Tag color="blue">场景执行</Tag><strong>{definition.name ?? definition.id}</strong></div><Space>{editButton}{runButton}</Space></div>
      <div className="sw-timeline"><div className="sw-env-block"><b>运行配置</b><span>环境：{env || '未选择'} 参数：{mode}</span><Button size="small" onClick={() => setDrawer(true)}>更改</Button></div>{rows.filter(row => !collapsed.some(number => row.number.startsWith(`${number}.`))).map(row => <div className="sw-timeline-node" key={row.number}><div className="sw-timeline-rail"><span>{row.number}</span></div>{stepRow(row, true)}</div>)}</div>{result}
    </>}
    <div className="sw-switcher"><Button aria-label="上一个原型" icon={<ArrowLeftOutlined />} onClick={() => changeVariant(variant === 'A' ? 'C' : variant === 'B' ? 'A' : 'B')} /><Segmented value={variant} options={[{ label: 'A 步骤主屏', value: 'A' }, { label: 'B 目录检查器', value: 'B' }, { label: 'C 执行时间线', value: 'C' }]} onChange={value => changeVariant(String(value))} /><Button aria-label="下一个原型" icon={<ArrowRightOutlined />} onClick={() => changeVariant(variant === 'A' ? 'B' : variant === 'B' ? 'C' : 'A')} /></div>
    <Drawer title="运行数据" open={drawer} onClose={() => setDrawer(false)} width={Math.min(560, window.innerWidth - 24)}>
      <div className="sw-drawer-intro"><Space wrap><Select value={mode} style={{ minWidth: 180 }} onChange={value => {
        if (mode === '我的草稿') setSavedDraft(params)
        setMode(value)
        const next = value === '我的草稿' ? savedDraft : teamParams
        setParams(next); setJsonText(JSON.stringify(next, null, 2))
      }} options={[{ value: '我的草稿', label: '我的草稿' }, { value: '团队方案', label: `团队方案：${schemeName}` }]} /><Button type="link" onClick={() => { setMode('我的草稿'); setSavedDraft(params) }}>复制为我的草稿</Button></Space><Typography.Text type="secondary">当前为{mode === '我的草稿' ? '个人草稿' : '团队方案的工作副本'}；此原型刷新后清空。</Typography.Text><Button onClick={() => setPublish(true)}>另存为团队方案（模拟）</Button></div>
      <div className="sw-param-head"><div><strong>场景参数</strong><Typography.Text type="secondary">{JSON.stringify(params) === JSON.stringify(definition.params) ? '当前展示：资产文件示例值' : '当前展示：本次编辑值'}</Typography.Text></div><Button icon={<CodeOutlined />} onClick={() => { setJsonText(JSON.stringify(params, null, 2)); setJsonMode(!jsonMode) }}>{jsonMode ? '字段编辑' : 'JSON'}</Button></div>
      {jsonMode ? <><Input.TextArea rows={18} value={jsonText} onChange={event => setJsonText(event.target.value)} aria-label="参数 JSON" />{jsonError ? <div className="sw-error">{jsonError}</div> : null}<Button type="primary" onClick={saveJson} style={{ marginTop: 10 }}>应用 JSON</Button></> : fields(params).map(field => <div className="sw-param-row" key={field.path}><div><strong>{field.path.split('.').at(-1)}</strong><code>{field.path}</code></div>{editValue(field)}<Tag>{JSON.stringify(fields(definition.params).find(item => item.path === field.path)?.value) === JSON.stringify(field.value) ? '资产文件' : '本次编辑'}</Tag></div>)}
      <div className="sw-source-note"><b>字段分组怎么理解</b><p><code>common</code> 和 <code>private</code> 是场景作者定义的路径名，只用于组织参数；不是平台公共/私密权限，也不是用户隔离范围。</p><Button type="link" onClick={() => { setParams(definition.params); setJsonText(JSON.stringify(definition.params, null, 2)) }}>恢复示例值</Button><Button type="primary" onClick={() => setDrawer(false)}>完成</Button></div>
    </Drawer>
    <Modal title="保存团队数据方案 · 模拟" open={publish} onCancel={() => setPublish(false)} okText="仅在原型中保存" onOk={() => { setTeamParams(structuredClone(params)); setPublish(false) }}>
      <Typography.Paragraph>其他测试人员可选择并复制方案；修改副本不会覆盖共享版本。此处只演示显式共享动作。</Typography.Paragraph>
      <Input aria-label="团队方案名称" value={schemeName} onChange={event => setSchemeName(event.target.value)} />
    </Modal>
  </div>
}
