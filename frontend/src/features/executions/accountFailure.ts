import { formatErrorMessage } from '@/shared/ui/errorMessage'

/** 只认「账号缺失 / 停用 / 流程缺失」。普通「身份不可用」（例如环境变量）保持原文。 */
const ACCOUNT_PATTERNS = [
  /身份不存在:\s*([a-z][a-z0-9_]*)/,
  /账号\s+([a-z][a-z0-9_]*)\s+在环境/,
  /账号\s+([a-z][a-z0-9_]*)\s+的登录流程/,
]

/** 从预检文案里取出账号名。匹配不到就返回 null，调用方保留原文。 */
export function extractAccountName(message: string): string | null {
  for (const pattern of ACCOUNT_PATTERNS) {
    const match = message.match(pattern)
    const name = match?.[1]
    if (name && name !== 'none') {
      return name
    }
  }
  return null
}

/**
 * 账号缺失或不可用时，把当前所选环境写进提示。
 * 只使用接口已经返回的公开文案，不附加异常栈。
 */
export function formatRunFailure(error: unknown, env: string): string {
  const raw = formatErrorMessage(error)
  const name = extractAccountName(raw)
  if (!name || !env) {
    return raw
  }
  return `账号 ${name} 在环境 ${env} 缺失或不可用。${raw}`
}
