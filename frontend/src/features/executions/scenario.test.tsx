import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ApiParseError } from '@/shared/api/errors'
import { parseCaseAssetDetail, parseCaseResult } from './caseParse'
import { CaseResultView } from './CaseResultView'
import { ScenarioBindings } from './ScenarioBindings'
import type { CaseStepResult, ScenarioDefinition } from './types'

const definition: ScenarioDefinition = {
  schema_version: '0.3', kind: 'case', id: 'case.demo.repeat', name: '重复调用',
  params: { common: { enabled: true }, private: { first: 1, second: 2 } },
  inputs: {}, outputs: {},
  steps: ['first', 'second'].map((name) => ({
    step_id: name, type: 'flow', name, asset_id: 'flow.demo.echo',
    params: { value: '${params.private.' + name + '}' }, output: name, identity: null,
    definition: {
      schema_version: '0.3', kind: 'flow', id: 'flow.demo.echo', name: null,
      params: {}, inputs: { value: { type: 'integer' } }, outputs: { value: '${echo.body}' },
      steps: [{ step_id: 'echo', type: 'api', name: null, asset_id: 'api.demo.echo',
        params: { value: '${inputs.value}' }, output: 'echo', identity: null }],
    },
  })),
}

function failedStep(id: string, children: CaseStepResult[] = []): CaseStepResult {
  return {
    step_id: id, name: id, type: children.length ? 'flow' : 'api', status: 'failed',
    duration_seconds: 0.01, request: null, response: null, output: null, skip_reason: null,
    error: { kind: 'variable_resolution', message: '缺少引用值', stage: 'execution', path: 'inputs.missing' },
    trace: { node_id: id, parent_id: id === 'outer' ? null : 'outer',
      asset_id: `${children.length ? 'flow' : 'api'}.demo.${id}`,
      inputs: { value: 2 }, outputs: {}, children,
      bindings: [{ target_path: 'value', reference: 'params.private.second',
        source_node_id: 'case-params', value: 2, value_type: 'integer' }],
    },
  }
}

describe('新版场景展示契约', () => {
  it('保留集中参数和两次独立引用，展开流程后仍只展示绑定', () => {
    const detail = parseCaseAssetDetail({ case_id: definition.id, path: 'scenarios/demo/repeat.case.yaml',
      file_name: 'repeat.case.yaml', size_bytes: 100, modified_at: '2026-10-19', definition })
    expect(detail.definition).toEqual(definition)
    render(<ScenarioBindings definition={detail.definition!} />)
    fireEvent.click(screen.getByText('first · 公共流程'))
    expect(screen.getByText(/params.private.first/)).toBeInTheDocument()
    fireEvent.click(screen.getByText('echo · API'))
    expect(screen.getByText(/inputs.value/)).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('历史解析保留递归结果并自动展开至失败 API', () => {
    const outer = failedStep('outer', [failedStep('inner', [failedStep('leaf')])])
    const result = parseCaseResult({ case_id: definition.id, status: 'failed', duration_seconds: 0.03,
      result_version: '0.3', steps: [outer], summary: { total: 1, success: 0, failed: 1, skipped: 0 },
      error: null, logins: [] })
    expect(result.steps[0].trace?.children[0].trace?.children[0].trace?.inputs.value).toBe(2)
    render(<CaseResultView result={result} />)
    expect(screen.getByText(/api.demo.leaf/)).toBeVisible()
    expect(screen.getAllByText(/params.private.second/)).toHaveLength(3)
    expect(screen.getAllByText('Request')).toHaveLength(1)
  })

  it('拒绝格式错误的嵌套历史，避免静默丢失失败子步骤', () => {
    const outer = failedStep('outer', [failedStep('leaf')])
    expect(() => parseCaseResult({ case_id: definition.id, status: 'failed', duration_seconds: 0.01,
      steps: [{ ...outer, trace: { ...outer.trace, children: [{ step_id: 'broken' }] } }],
      summary: { total: 1, success: 0, failed: 1, skipped: 0 }, error: null, logins: [] })).toThrow(ApiParseError)
  })
})

function resultWith(step: CaseStepResult) {
  return { case_id: definition.id, status: 'failed', duration_seconds: 0.01,
    result_version: '0.3', steps: [step], summary: { total: 1, success: 0, failed: 1, skipped: 0 },
    error: null, logins: [] }
}

describe('schema 0.3 本地节点与遍历', () => {
  it.each([null, false, 0, '0.30', [], [1, 2]].map(outputs => ({ outputs })))('保留 JSON 输出 $outputs', ({ outputs }) => {
    const step = failedStep('local')
    step.type = 'extract'
    step.trace = { ...step.trace!, outputs, extracts: [{ match_count: 1, value: outputs, status: 'success' }] }
    const result = parseCaseResult(resultWith(step))
    expect(result.steps[0].trace?.outputs).toEqual(outputs)
    expect(result.steps[0].trace?.extracts).toEqual(step.trace.extracts)
  })

  it.each([{ iteration_index: -1 }, { extracts: {} }, { assertions: [null] }, { transforms: [1] }])('拒绝畸形证据 %j', (evidence) => {
    const step = failedStep('local')
    step.trace = { ...step.trace!, ...evidence } as CaseStepResult['trace']
    expect(() => parseCaseResult(resultWith(step))).toThrow(ApiParseError)
  })

  it('保留五种节点配置，显示静态 map 定义与金额规则', () => {
    const extra = [
      { type: 'map' as const, source: '${params.items}', definition: definition.steps[0].definition },
      { type: 'extract' as const, source: '${rows}', selector: { path: ['skuList'], where: { color: '红' } }, cardinality: 'one', value_type: 'object', nullable: false },
      { type: 'decimal' as const, operation: 'multiply', operands: ['0.335', 2], scale: 2, rounding: 'HALF_UP' },
      { type: 'assert' as const, operation: 'decimal_equal' },
      { type: 'transform' as const, operation: 'project', source: '${items}', path: ['id'] },
    ].map((config, index) => ({ step_id: `step${index}`, asset_id: definition.id, name: null,
      params: {}, output: null, identity: null, ...config }))
    const full = { ...definition, steps: extra }
    const parsed = parseCaseAssetDetail({ case_id: definition.id, path: 'demo.case.yaml',
      file_name: 'demo.case.yaml', size_bytes: 1, modified_at: '2026-10-20', definition: full })
    expect(parsed.definition).toEqual(full)
    render(<ScenarioBindings definition={parsed.definition!} />)
    fireEvent.click(screen.getByText('step0 · 有序遍历'))
    expect(screen.getByText(/下列子步骤为每项复用定义/)).toBeVisible()
    fireEvent.click(screen.getByText('step2 · 金额计算'))
    expect(screen.getByText(/HALF_UP/)).toBeVisible()
  })

  it('自动展开失败 map 第二项，显示命中数和断言实际/期望值，不生成本地请求面板', () => {
    const leaf = failedStep('sku')
    leaf.type = 'extract'
    leaf.trace = { ...leaf.trace!, outputs: {}, extracts: [{ match_count: 0, status: 'failed', value: null }] }
    const iteration = failedStep('each[1]', [leaf])
    iteration.trace!.iteration_index = 1
    const map = failedStep('each', [iteration]); map.type = 'map'
    render(<CaseResultView result={parseCaseResult(resultWith(map))} />)
    expect(screen.getByText(/遍历项 2（index=1）/)).toBeVisible()
    expect(screen.getByRole('region', { name: '提取证据' })).toHaveTextContent(/命中数.*0/)
    expect(screen.queryByText('Request')).not.toBeInTheDocument()
  })

  it('失败断言保留实际值和期望值及来源', () => {
    const step = failedStep('check'); step.type = 'assert'
    step.trace!.assertions = [{ operation: 'decimal_equal', actual: '11.20', expected: '11.21', status: 'failed' }]
    render(<CaseResultView result={parseCaseResult(resultWith(step))} />)
    const evidence = screen.getByRole('region', { name: '断言证据' })
    expect(evidence).toHaveTextContent(/实际值.*11\.20/)
    expect(evidence).toHaveTextContent(/期望值.*11\.21/)
    expect(screen.getByText(/case-params/)).toBeVisible()
    expect(screen.queryByText('Request')).not.toBeInTheDocument()
  })
})
