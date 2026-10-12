import type { CaseStepStatus, RunStatus } from './types'

/** 状态文案：颜色与文字同时表达，不单靠色盲不友好的色差 */
export function runStatusLabel(status: RunStatus | string): string {
  if (status === 'success') return '成功'
  if (status === 'failed') return '失败'
  return status
}

export function stepStatusLabel(status: CaseStepStatus): string {
  if (status === 'success') return '成功'
  if (status === 'failed') return '失败'
  if (status === 'skipped') return '已跳过'
  return status
}

export function runStatusColor(
  status: RunStatus | string,
): 'success' | 'error' | 'default' {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'error'
  return 'default'
}

export function stepStatusColor(
  status: CaseStepStatus,
): 'success' | 'error' | 'warning' | 'default' {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'error'
  // skipped 用 warning，与 failed 的 error 明确区分
  if (status === 'skipped') return 'warning'
  return 'default'
}

export function formatDurationSeconds(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) {
    return '—'
  }
  if (seconds < 1) {
    return `${Math.round(seconds * 1000)}ms`
  }
  return `${seconds.toFixed(2)}s`
}
