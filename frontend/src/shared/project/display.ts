import type { SyncResultCategory } from '@/shared/types/project'

/** 短 SHA：展示用前 7 位；空则 — */
export function shortSha(sha: string | null | undefined): string {
  if (!sha) {
    return '—'
  }
  return sha.length > 7 ? sha.slice(0, 7) : sha
}

const SYNC_RESULT_LABELS: Record<string, string> = {
  ok: '成功',
  network: '网络错误',
  auth: '认证失败',
  invalid_manifest: '清单非法',
  timeout: '超时',
}

/** 同步结果类别 → 中文文案；未知类别原样回退（仍不含 URL） */
export function syncResultLabel(category: SyncResultCategory | string | null | undefined): string {
  if (!category) {
    return '尚未同步'
  }
  return SYNC_RESULT_LABELS[category] ?? category
}
