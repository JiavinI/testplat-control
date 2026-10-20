import { Descriptions, Typography } from 'antd'
import { JsonBlock } from './JsonBlock'
import { scenarioOperationLabel } from './scenarioDisplay'
import type { ScenarioTrace } from './types'

const labels: Record<string, string> = {
  operation: '操作', actual: '实际值', expected: '期望值', status: '结果',
  source: '数据来源', selector: '选择器', cardinality: '命中要求', value_type: '结果类型',
  target: '目标变量', match_count: '命中数', value: '结果值', path: '读取路径',
  scale: '小数位数', rounding: '舍入规则',
}

export function ScenarioEvidence({ trace }: { trace: ScenarioTrace }) {
  const groups = [
    ['extracts', '提取证据'], ['calculations', '金额计算证据'],
    ['assertions', '断言证据'], ['transforms', '列表处理证据'],
  ] as const
  return <>{groups.map(([key, title]) => trace[key]?.length ? <section key={key} aria-label={title}>
    <Typography.Paragraph strong>{title}</Typography.Paragraph>
    {trace[key]!.map((entry, index) => <Descriptions key={index} size="small" column={1} items={Object.entries(entry).map(([name, value]) => ({
      key: name, label: labels[name] ?? name,
      children: <JsonBlock value={name === 'operation' && typeof value === 'string' ? scenarioOperationLabel(value) : name === 'status' ? (value === 'success' ? '通过' : '失败') : value} />,
    }))} />)}
  </section> : null)}</>
}
