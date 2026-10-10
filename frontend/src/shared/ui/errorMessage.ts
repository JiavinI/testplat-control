import { ApiHttpError, ApiNetworkError, ApiParseError } from '@/shared/api/errors'

export function formatErrorMessage(error: unknown): string {
  if (error instanceof ApiHttpError) {
    return error.message
  }
  if (error instanceof ApiNetworkError) {
    return `网络错误：${error.message}`
  }
  if (error instanceof ApiParseError) {
    return `响应解析失败：${error.message}`
  }
  if (error instanceof Error) {
    return error.message
  }
  return '未知错误'
}
