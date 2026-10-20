import type { ScenarioStepDefinition } from './types'

export const scenarioTypeLabel = (type: string) => ({
  api: 'API', flow: '公共流程', map: '有序遍历', extract: '数据提取',
  decimal: '金额计算', assert: '条件断言', transform: '列表处理',
}[type] ?? type)

export const scenarioOperationLabel = (operation?: string) => ({
  add: '金额相加', multiply: '金额相乘', sum: '金额求和',
  project: '列表投影', positive_integer_sum: '正整数求和',
  non_empty: '非空', positive_integer: '正整数', equal: '严格相等', decimal_equal: 'Decimal 相等',
}[operation ?? ''] ?? operation ?? '—')

export function scenarioConfiguration(step: ScenarioStepDefinition): Record<string, unknown> {
  const result: Record<string, unknown> = {}
  if (step.source !== undefined) result['数据来源'] = step.source
  if (step.selector !== undefined) result['选择器'] = step.selector
  if (step.cardinality !== undefined) result['命中要求'] = step.cardinality === 'one' ? '恰好一项' : '全部匹配项'
  if (step.value_type !== undefined) result['结果类型'] = step.value_type
  if (step.nullable !== undefined) result['允许 null'] = step.nullable
  if (step.operation !== undefined) result['操作'] = scenarioOperationLabel(step.operation)
  if (step.operands !== undefined) result['操作数'] = step.operands
  if (step.scale !== undefined) result['小数位数'] = step.scale
  if (step.rounding !== undefined) result['舍入规则'] = step.rounding
  if (step.path !== undefined) result['读取路径'] = step.path
  if (step.type === 'map') result['执行方式'] = '按序串行，首错停止；下列子步骤为每项复用定义'
  return result
}
