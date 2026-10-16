import { ApiHttpError } from '@/shared/api/errors'

export const REVISION_CONFLICT_MESSAGE = '配置版本冲突，请刷新后再保存'

export function isRevisionConflict(error: unknown): boolean {
  return error instanceof ApiHttpError && error.status === 409
}
