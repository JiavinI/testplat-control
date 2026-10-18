import type { ParamInfo } from './types'

export type ParameterSource = 'asset' | 'saved' | 'environment' | 'override' | 'temporary' | 'unset'
export interface ParameterValue {
  name: string
  asset: unknown
  saved: unknown
  environment: unknown
  override: unknown
  temporary: unknown
  effective: unknown
  source: ParameterSource
}

const owns = (value: Record<string, unknown>, name: string) => Object.prototype.hasOwnProperty.call(value, name)

/** 与运行时一致的顶层覆盖。接口只看声明键；场景保留全部 JSON 顶层键。 */
export function resolveParameterValues(
  asset: Record<string, unknown> = {},
  environment: Record<string, unknown> = {},
  temporary: Record<string, unknown> = {},
  names: string[] | undefined = undefined,
  saved: Record<string, unknown> = {},
  override: Record<string, unknown> = {},
): ParameterValue[] {
  const layers = { asset, saved, environment, override, temporary }
  const keys = names ?? [...new Set(Object.values(layers).flatMap(Object.keys))]
  return keys.map((name) => {
    const source = (['temporary', 'override', 'environment', 'saved', 'asset'] as const).find((key) => owns(layers[key], name)) ?? 'unset'
    const effective = source === 'unset' ? undefined : layers[source][name]
    return {
      name,
      asset: owns(asset, name) ? asset[name] : undefined,
      saved: owns(saved, name) ? saved[name] : undefined,
      environment: owns(environment, name) ? environment[name] : undefined,
      override: owns(override, name) ? override[name] : undefined,
      temporary: owns(temporary, name) ? temporary[name] : undefined,
      effective, source,
    }
  })
}

/** 不因 false、0、空串误判为缺省；无效上层值也不能偷偷回退到资产默认值。 */
export function validParameterDefault(item: ParamInfo, row: ParameterValue): boolean {
  if (row.source === 'unset') return false
  const value = row.effective
  return item.type === 'number' ? typeof value === 'number' && Number.isFinite(value) : typeof value === item.type
}

const sensitiveName = /password|passwd|pwd|secret|token|cookie|authorization|master.?key|api[-_]?key/i

/** 预览只展示普通业务值；敏感键不渲染其值。实际请求仍使用原值。 */
export function formatParameterValue(name: string, value: unknown): string {
  if (value === undefined) return '—'
  if (sensitiveName.test(name)) return '••••••'
  return JSON.stringify(value, (key, item: unknown) => sensitiveName.test(key) ? '••••••' : item) ?? '—'
}
