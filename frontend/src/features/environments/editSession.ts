/**
 * 一次编辑会话。异步回写前比对代次、项目、环境和账号，
 * 关闭、切换账号或切换项目后旧响应必须丢弃。
 */
export interface EditTarget {
  generation: number
  projectId: string
  env: string
  accountName: string | null
}

export function nextEditTarget(
  previous: EditTarget | null,
  next: Omit<EditTarget, 'generation'>,
): EditTarget {
  return {
    ...next,
    generation: (previous?.generation ?? 0) + 1,
  }
}

export function isCurrentEditTarget(current: EditTarget | null, captured: EditTarget): boolean {
  if (!current) {
    return false
  }
  return (
    current.generation === captured.generation &&
    current.projectId === captured.projectId &&
    current.env === captured.env &&
    current.accountName === captured.accountName
  )
}
