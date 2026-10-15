/**
 * 记住用户在某项目上次选择的运行环境（localStorage）。
 * 键含 repo/project，跨浏览器会话保留；解析失败时忽略。
 */
const PREFIX = 'testplat.control.projectEnv:'

export function readPreferredEnv(projectId: string): string | null {
  try {
    const raw = window.localStorage.getItem(`${PREFIX}${projectId}`)
    return raw && raw.trim() ? raw : null
  } catch {
    return null
  }
}

export function writePreferredEnv(projectId: string, env: string): void {
  try {
    window.localStorage.setItem(`${PREFIX}${projectId}`, env)
  } catch {
    // 隐私模式等写失败时静默；运行仍用内存中的选择
  }
}

/**
 * 解析当前应选环境：优先 localStorage 且仍在 envs 内，否则 default_env，再否则 envs[0]。
 */
export function resolveInitialEnv(
  projectId: string,
  envs: string[],
  defaultEnv: string | null,
): string | null {
  if (envs.length === 0) {
    return null
  }
  const preferred = readPreferredEnv(projectId)
  if (preferred && envs.includes(preferred)) {
    return preferred
  }
  if (defaultEnv && envs.includes(defaultEnv)) {
    return defaultEnv
  }
  return envs[0] ?? null
}
