import { ApiParseError } from './errors'

/** 运行时结构校验：失败时抛 ApiParseError，避免畸形响应导致白屏。 */
export function assertObject(
  value: unknown,
  label: string,
  bodyText = '',
): asserts value is Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new ApiParseError(`${label} 应为对象`, bodyText || summarize(value))
  }
}

export function assertArray(
  value: unknown,
  label: string,
  bodyText = '',
): asserts value is unknown[] {
  if (!Array.isArray(value)) {
    throw new ApiParseError(`${label} 应为数组`, bodyText || summarize(value))
  }
}

export function requireString(
  obj: Record<string, unknown>,
  key: string,
  label: string,
  bodyText = '',
): string {
  const value = obj[key]
  if (typeof value !== 'string') {
    throw new ApiParseError(`${label}.${key} 应为字符串`, bodyText || summarize(obj))
  }
  return value
}

export function requireNullableString(
  obj: Record<string, unknown>,
  key: string,
  label: string,
  bodyText = '',
): string | null {
  const value = obj[key]
  if (value === null) {
    return null
  }
  if (typeof value !== 'string') {
    throw new ApiParseError(`${label}.${key} 应为字符串或 null`, bodyText || summarize(obj))
  }
  return value
}

export function requireNullableNumber(
  obj: Record<string, unknown>,
  key: string,
  label: string,
  bodyText = '',
): number | null {
  const value = obj[key]
  if (value === null) {
    return null
  }
  if (typeof value !== 'number' || Number.isNaN(value)) {
    throw new ApiParseError(`${label}.${key} 应为数字或 null`, bodyText || summarize(obj))
  }
  return value
}

export function requireNumber(
  obj: Record<string, unknown>,
  key: string,
  label: string,
  bodyText = '',
): number {
  const value = obj[key]
  if (typeof value !== 'number' || Number.isNaN(value)) {
    throw new ApiParseError(`${label}.${key} 应为数字`, bodyText || summarize(obj))
  }
  return value
}

export function requireInteger(
  obj: Record<string, unknown>,
  key: string,
  label: string,
  bodyText = '',
): number {
  const value = requireNumber(obj, key, label, bodyText)
  if (!Number.isInteger(value)) {
    throw new ApiParseError(`${label}.${key} 应为整数`, bodyText || summarize(obj))
  }
  return value
}

/** 缺省或 null 视为没有该版本号。错误文案不附带原对象，避免把凭据带进异常。 */
export function readOptionalNullableInteger(
  obj: Record<string, unknown>,
  key: string,
  label: string,
): number | null {
  if (!(key in obj) || obj[key] === undefined || obj[key] === null) {
    return null
  }
  const value = obj[key]
  if (typeof value !== 'number' || !Number.isInteger(value)) {
    throw new ApiParseError(`${label}.${key} 应为整数或 null`, '[已省略]')
  }
  return value
}

function summarize(value: unknown): string {
  try {
    return JSON.stringify(value)?.slice(0, 200) ?? String(value)
  } catch {
    return String(value)
  }
}
