export const ENV_NAME_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/
export const ACCOUNT_NAME_RE = /^[a-z][a-z0-9_]{0,63}$/
const HOST_NAME_RE = /^[A-Za-z_][A-Za-z0-9_-]{0,63}$/

export function validateEnvName(env: string): string | null {
  if (!ENV_NAME_RE.test(env) || env.startsWith('_')) {
    return '环境名需匹配 ^[a-z0-9][a-z0-9_-]{0,63}$，且不能以 _ 开头'
  }
  return null
}

export function validateAccountName(name: string): string | null {
  if (!ACCOUNT_NAME_RE.test(name)) {
    return '账号名需匹配 ^[a-z][a-z0-9_]*$'
  }
  if (name === 'none') {
    return 'none 是保留账号名'
  }
  return null
}

export interface HostRow {
  name: string
  url: string
}

export function hostsToRows(hosts: Record<string, string>): HostRow[] {
  const rows = Object.entries(hosts).map(([name, url]) => ({ name, url }))
  return rows.length > 0 ? rows : [{ name: '', url: '' }]
}

export function collectHosts(
  rows: HostRow[],
): { hosts: Record<string, string> } | { error: string } {
  const hosts: Record<string, string> = {}
  for (const row of rows) {
    const name = row.name.trim()
    const url = row.url.trim()
    if (!name && !url) {
      continue
    }
    if (!name || !url) {
      return { error: '服务名和地址需要成对填写' }
    }
    if (!HOST_NAME_RE.test(name)) {
      return { error: '服务名需以字母或下划线开头' }
    }
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      return { error: '地址必须是 http(s) URL' }
    }
    const hostport = url.split('://', 2)[1]?.split('/', 1)[0] ?? ''
    if (hostport.includes('@')) {
      return { error: '地址不得包含用户信息' }
    }
    if (name in hosts) {
      return { error: `服务名 ${name} 重复` }
    }
    hosts[name] = url
  }
  return { hosts }
}

export function parseCaseParamsText(
  text: string,
): { value: Record<string, unknown> } | { error: string } {
  const trimmed = text.trim()
  if (!trimmed) {
    return { value: {} }
  }
  try {
    const parsed = JSON.parse(trimmed) as unknown
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { error: '参数默认值必须是 JSON 对象' }
    }
    return { value: parsed as Record<string, unknown> }
  } catch {
    return { error: '参数默认值不是合法 JSON' }
  }
}

export function formatCaseParams(value: Record<string, unknown>): string {
  if (Object.keys(value).length === 0) {
    return ''
  }
  return JSON.stringify(value, null, 2)
}

export function parseTimeoutText(
  text: string,
): { value: number | null } | { error: string } {
  const trimmed = text.trim()
  if (!trimmed) {
    return { value: null }
  }
  const value = Number(trimmed)
  if (!Number.isFinite(value) || value <= 0 || value > 300) {
    return { error: '超时需在 (0, 300] 秒内；留空表示使用默认 30 秒' }
  }
  return { value }
}

export function validateCredentialValue(value: string): string | null {
  if (value.length < 8) {
    return '凭据字段长度不足 8'
  }
  if (/[\r\n\0]/.test(value)) {
    return '凭据字段含非法控制字符'
  }
  return null
}

export function sameCredentials(
  left: Record<string, string>,
  right: Record<string, string>,
): boolean {
  const leftKeys = Object.keys(left).sort()
  const rightKeys = Object.keys(right).sort()
  if (leftKeys.length !== rightKeys.length) {
    return false
  }
  return leftKeys.every((key, index) => key === rightKeys[index] && left[key] === right[key])
}
