import { Alert, Button, Descriptions, Divider, Drawer, Input, InputNumber, Select, Space, Tag, Typography } from 'antd'
import { CodeOutlined, PlayCircleOutlined, SettingOutlined } from '@ant-design/icons'
import { useMemo, useState } from 'react'
import { ApiHttpError, ApiParseError } from '@/shared/api/errors'
import { formatRunFailure } from './accountFailure'
import { formatErrorMessage } from '@/shared/ui/errorMessage'
import { shortSha } from '@/shared/project/display'
import { getCaseExecutionRecord, listExecutionRecords } from './api'
import { scenarioTypeLabel } from './scenarioDisplay'
import { ScenarioConfiguration } from './ScenarioConfiguration'
import { CaseResultView } from './CaseResultView'
import { useRunCase } from './hooks'
import { ParameterPreview } from './ParameterPreview'
import type { AssetNode } from '@/features/assets'
import type {
  CaseExecutionPanelProps, CaseExecutionRecordDetail, CaseRunResponse,
  ScenarioDefinition, ScenarioStepDefinition,
} from './types'
import './CaseExecutionPanel.css'

type LocatedSystemFailure = { record: CaseExecutionRecordDetail; publicMessage: string; httpStatus: number }
type ScenarioRow = { step: ScenarioStepDefinition; number: string; parent?: string }
type ParameterField = { path: string; value: unknown }

export function CaseExecutionPanel(props: CaseExecutionPanelProps) {
  return <CaseExecutionPanelReady key={`${props.projectId}:${props.caseId}:${props.env}`} {...props} />
}

function flattenSteps(definition: ScenarioDefinition, assets: AssetNode[], prefix = '', index = assetIndex(assets)): ScenarioRow[] {
  return definition.steps.flatMap((step, position) => {
    const number = prefix ? `${prefix}.${position + 1}` : `${position + 1}`
    const row = { step, number, parent: prefix || undefined }
    return [row, ...(step.definition ? flattenSteps(step.definition, assets, number, index) : [])]
  })
}

function assetIndex(nodes: AssetNode[], index = new Map<string, AssetNode>()) {
  for (const node of nodes) {
    index.set(node.id, node)
    if (node.children) assetIndex(node.children, index)
  }
  return index
}

function parameterFields(value: unknown, prefix = ''): ParameterField[] {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const entries = Object.entries(value)
    return entries.length ? entries.flatMap(([key, child]) => parameterFields(child, prefix ? `${prefix}.${key}` : key)) : [{ path: prefix, value }]
  }
  return [{ path: prefix, value }]
}

function updatePath(source: Record<string, unknown>, path: string, value: unknown): Record<string, unknown> {
  const [head, ...tail] = path.split('.')
  if (!head) return source
  const child = source[head]
  return { ...source, [head]: tail.length ? updatePath(child && typeof child === 'object' && !Array.isArray(child) ? child as Record<string, unknown> : {}, tail.join('.'), value) : value }
}

function titleFor(row: ScenarioRow, assets: Map<string, AssetNode>) {
  return row.step.name?.trim() || row.step.definition?.name?.trim() || String(assets.get(row.step.asset_id)?.metadata?.name ?? assets.get(row.step.asset_id)?.name ?? row.step.step_id)
}

function CaseExecutionPanelReady({ projectId, caseId, env, assetDefaults, caseParams, parameterContext, parameterSettings, definition, assets = [] }: CaseExecutionPanelProps) {
  const runMutation = useRunCase(projectId, caseId)
  const [runResult, setRunResult] = useState<CaseRunResponse | null>(null)
  const [submitError, setSubmitError] = useState<unknown>(null)
  const [located, setLocated] = useState<LocatedSystemFailure | null>(null)
  const [locating, setLocating] = useState(false)
  const [paramsText, setParamsText] = useState('')
  const [parameterDrawer, setParameterDrawer] = useState(false)
  const [jsonMode, setJsonMode] = useState(false)
  const [jsonDraft, setJsonDraft] = useState('')
  const [jsonError, setJsonError] = useState('')
  const [selectedNumber, setSelectedNumber] = useState('1')
  const temporary = parseTemporaryParams(paramsText)
  const submitting = runMutation.isPending || locating
  const index = useMemo(() => assetIndex(assets), [assets])
  const rows = useMemo(() => definition ? flattenSteps(definition, assets) : [], [definition, assets])
  const selectedRow = rows.find((row) => row.number === selectedNumber) ?? rows[0]
  const baseParams = definition?.params ?? {}
  const draftParams = { ...baseParams, ...('error' in temporary ? {} : temporary.value) }
  const fields = parameterFields(draftParams)

  const handleRun = async () => {
    setSubmitError(null); setLocated(null); setRunResult(null)
    try {
      if ('error' in temporary) throw new Error(temporary.error)
      const data = await runMutation.mutateAsync({ env, params: temporary.value })
      setRunResult(data)
    } catch (error) {
      if (error instanceof ApiHttpError && error.status >= 500) {
        setSubmitError(error); setLocating(true)
        try {
          const items = await listExecutionRecords(projectId, { asset_type: 'case', asset_id: caseId, status: 'failed', limit: 5, order_by: '-start_time' })
          if (items.length > 0) {
            const record = await getCaseExecutionRecord(projectId, items[0].id)
            setLocated({ record, publicMessage: formatErrorMessage(error), httpStatus: error.status })
          }
        } catch { /* Keep the original public error if history lookup fails. */ }
        finally { setLocating(false) }
        return
      }
      setSubmitError(error)
    }
  }

  const changeParameter = (path: string, value: unknown) => {
    const next = updatePath(draftParams, path, value)
    setParamsText(JSON.stringify(next, null, 2))
    if (jsonMode) setJsonDraft(JSON.stringify(next, null, 2))
  }
  const openParameters = () => {
    setJsonDraft(JSON.stringify(draftParams, null, 2))
    setJsonError('')
    setJsonMode(false)
    setParameterDrawer(true)
  }
  const applyJson = () => {
    try {
      const parsed: unknown = JSON.parse(jsonDraft)
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('场景参数必须是 JSON 对象')
      setParamsText(JSON.stringify(parsed, null, 2)); setJsonError(''); setJsonMode(false)
    } catch (error) { setJsonError(error instanceof Error ? error.message : 'JSON 格式无效') }
  }

  return <div className="tp-scenario-workbench" data-testid="case-execution-panel">
    <header className="tp-scenario-runbar">
      <div className="tp-scenario-runbar__identity">
        <Typography.Text strong>{definition?.name || caseId}</Typography.Text>
        <Typography.Text type="secondary">{env}</Typography.Text>
      </div>
      <Space wrap>
        <Button aria-label="本次参数" icon={<SettingOutlined />} onClick={openParameters}>本次参数</Button>
        <Button type="primary" aria-label="执行 Case" icon={<PlayCircleOutlined />} loading={submitting} disabled={submitting || 'error' in temporary} onClick={() => { void handleRun() }} data-testid="case-run-button">
          {submitting ? (locating ? '定位记录…' : '执行中…') : '运行场景'}
        </Button>
      </Space>
    </header>

    {definition ? <div className="tp-scenario-inspector">
      <nav className="tp-scenario-outline" aria-label="场景步骤目录" data-testid="scenario-step-outline">
        <div className="tp-scenario-outline__heading"><Typography.Text strong>执行顺序</Typography.Text><Typography.Text type="secondary">{rows.length} 步</Typography.Text></div>
        {rows.map((row) => {
          const asset = index.get(row.step.asset_id)
          const selected = row.number === (selectedRow?.number ?? selectedNumber)
          const operation = row.step.type === 'api' ? (asset?.metadata?.method ? `${String(asset.metadata.method)} 请求` : 'API 请求') : scenarioTypeLabel(row.step.type)
          return <button key={`${row.number}:${row.step.step_id}`} type="button" className={`tp-scenario-outline__item${row.parent ? ' is-nested' : ''}${selected ? ' is-selected' : ''}`} aria-current={selected ? 'step' : undefined} onClick={() => setSelectedNumber(row.number)}>
            <code>{row.number}</code><span className="tp-scenario-outline__copy"><strong>{titleFor(row, index)}</strong><small>{operation}</small></span>
          </button>
        })}
      </nav>

      <main className="tp-scenario-step-detail" data-testid="scenario-step-detail">
        {selectedRow ? <>
          <div className="tp-scenario-step-detail__head"><div><Typography.Text type="secondary">步骤 {selectedRow.number}</Typography.Text><Typography.Title level={4}>{titleFor(selectedRow, index)}</Typography.Title></div><Tag>{scenarioTypeLabel(selectedRow.step.type)}</Tag></div>
          {selectedRow.step.type === 'api' || selectedRow.step.type === 'flow' || selectedRow.step.type === 'map' ? <div className="tp-scenario-facts">
            <div><Typography.Text type="secondary">{selectedRow.step.type !== 'api' ? '流程引用' : '请求目标'}</Typography.Text><strong>{selectedRow.step.type !== 'api' ? selectedRow.step.asset_id : `${String(index.get(selectedRow.step.asset_id)?.metadata?.method ?? '方法待解析')} ${String(index.get(selectedRow.step.asset_id)?.metadata?.url ?? selectedRow.step.asset_id)}`}</strong></div>
            <div><Typography.Text type="secondary">登录身份</Typography.Text><strong>{selectedRow.step.identity ?? (selectedRow.step.type !== 'api' ? '由子步骤分别指定' : '未显式指定，按接口配置')}</strong></div>
          </div> : null}
          <ScenarioConfiguration step={selectedRow.step} />
          {selectedRow.step.output ? <div className="tp-scenario-output"><Typography.Text type="secondary">结果别名</Typography.Text><Typography.Text code>{selectedRow.step.output}</Typography.Text></div> : null}
          <section className="tp-scenario-bindings"><div className="tp-scenario-section-heading"><Typography.Text strong>输入映射</Typography.Text><Typography.Text type="secondary">{Object.keys(selectedRow.step.params).length} 项</Typography.Text></div>
            {Object.entries(selectedRow.step.params).length ? Object.entries(selectedRow.step.params).map(([key, value]) => <div className="tp-scenario-binding" key={key}><code>{key}</code><span>←</span><code>{typeof value === 'string' ? value : JSON.stringify(value)}</code></div>) : <Typography.Text type="secondary">无显式输入映射</Typography.Text>}
          </section>
          {selectedRow.step.definition ? <details className="tp-scenario-contract"><summary>流程输入与输出契约</summary><Descriptions size="small" column={1}><Descriptions.Item label="输入">{JSON.stringify(selectedRow.step.definition.inputs)}</Descriptions.Item><Descriptions.Item label="输出">{JSON.stringify(selectedRow.step.definition.outputs)}</Descriptions.Item></Descriptions></details> : null}
          <details className="tp-scenario-contract"><summary>查看原始绑定 JSON</summary><pre>{JSON.stringify(selectedRow.step.params, null, 2)}</pre></details>
        </> : <Typography.Text type="secondary">此场景尚无可执行步骤</Typography.Text>}
      </main>
    </div> : <Alert type="warning" message="当前场景定义不可用" />}

    {submitError ? <Alert type="error" showIcon role="alert" style={{ marginTop: 12 }} message={submitError instanceof ApiHttpError && submitError.status >= 500 ? `系统错误（HTTP ${submitError.status}）` : submitError instanceof ApiHttpError && submitError.status === 422 ? '预检失败（HTTP 422）' : submitError instanceof ApiParseError ? '响应格式异常' : '执行失败'} description={<div><div data-testid="case-run-failure">{formatRunFailure(submitError, env)}</div>{submitError instanceof ApiHttpError && submitError.status >= 500 ? <Typography.Paragraph type="secondary">正在按 Case ID 查找失败历史记录。</Typography.Paragraph> : null}</div>} /> : null}

    {located?.record.result ? <section className="tp-scenario-run-result" data-testid="case-system-error-located"><Divider /><Typography.Title level={5}>系统错误 · 历史步骤</Typography.Title><CaseResultView result={located.record.result} recordId={located.record.id} locateNote={`HTTP ${located.httpStatus}：${located.publicMessage}；已定位记录 ${located.record.id}`} /></section> : null}
    {located && !located.record.result ? <Alert type="warning" style={{ marginTop: 12 }} message="已定位失败记录，但 result 无法解析" description={`记录 ID：${located.record.id}`} /> : null}

    {runResult ? <section key={runResult.record_id} className="tp-scenario-run-result" data-testid="case-run-result-wrap"><Divider /><Typography.Title level={5}>运行结果</Typography.Title><Descriptions size="small" column={{ xs: 1, sm: 2 }} style={{ marginBottom: 12 }} data-testid="case-run-trace"><Descriptions.Item label="操作人">{runResult.operator || '—'}</Descriptions.Item><Descriptions.Item label="环境">{env}</Descriptions.Item><Descriptions.Item label="Commit"><Typography.Text code>{shortSha(runResult.commit_sha)}</Typography.Text></Descriptions.Item>{typeof runResult.config_revision === 'number' ? <Descriptions.Item label="配置版本">{runResult.config_revision}</Descriptions.Item> : null}</Descriptions><CaseResultView result={runResult.result} recordId={runResult.record_id} /></section> : null}

    <Drawer title="本次运行参数" open={parameterDrawer} onClose={() => setParameterDrawer(false)} width={Math.min(620, window.innerWidth - 24)} destroyOnClose>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Typography.Text type="secondary">修改值仅用于本次运行；共享默认值与环境差异在此维护区操作。</Typography.Text>
        {parameterSettings ? <div className="tp-scenario-parameter-settings">{parameterSettings}</div> : null}
        <Space><Button size="small" onClick={() => setJsonMode(false)} type={!jsonMode ? 'primary' : 'default'}>字段编辑</Button><Button size="small" aria-label="JSON" icon={<CodeOutlined />} onClick={() => { setJsonDraft(JSON.stringify(draftParams, null, 2)); setJsonMode(true) }}>JSON</Button></Space>
        {jsonMode ? <><Input.TextArea aria-label="本次场景参数 JSON" value={jsonDraft} onChange={(event) => setJsonDraft(event.target.value)} autoSize={{ minRows: 12, maxRows: 24 }} style={{ fontFamily: 'monospace' }} />{jsonError ? <Alert type="error" message={jsonError} /> : null}<Button type="primary" onClick={applyJson}>应用 JSON</Button></> : fields.length ? fields.map((field) => <div className="tp-scenario-param-field" key={field.path}><div><Typography.Text strong>{field.path.split('.').at(-1) || field.path}</Typography.Text><Typography.Text code>{field.path}</Typography.Text></div>{typeof field.value === 'boolean' ? <Select aria-label={`${field.path} 的值`} value={field.value ? 'true' : 'false'} options={[{ value: 'true', label: 'true' }, { value: 'false', label: 'false' }]} onChange={(value) => changeParameter(field.path, value === 'true')} /> : typeof field.value === 'number' ? <InputNumber aria-label={`${field.path} 的值`} value={field.value} onChange={(value) => { if (value !== null) changeParameter(field.path, value) }} style={{ width: '100%' }} /> : <Input aria-label={`${field.path} 的值`} value={field.value === null ? 'null' : String(field.value ?? '')} onChange={(event) => changeParameter(field.path, event.target.value)} />}</div>) : <Typography.Text type="secondary">当前没有可覆盖参数</Typography.Text>}
        {'error' in temporary ? <Alert type="error" message={temporary.error} /> : <ParameterPreview env={env} assetDefaults={assetDefaults} caseParams={caseParams} temporary={temporary.value} context={parameterContext} />}
        <Space><Button onClick={() => { setParamsText(''); setJsonDraft('{}') }}>清除本次覆盖</Button><Button type="primary" aria-label="完成" onClick={() => setParameterDrawer(false)}>完成</Button></Space>
      </Space>
    </Drawer>
  </div>
}

function parseTemporaryParams(text: string): { value: Record<string, unknown> } | { error: string } {
  if (!text.trim()) return { value: {} }
  try {
    const value: unknown = JSON.parse(text)
    if (value === null || typeof value !== 'object' || Array.isArray(value)) return { error: '场景参数必须是 JSON 对象' }
    return { value: value as Record<string, unknown> }
  } catch { return { error: '场景参数不是合法 JSON' } }
}
