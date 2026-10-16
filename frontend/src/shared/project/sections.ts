export const SECTIONS = {
  apis: { label: '接口管理', description: '按模块浏览接口定义，选择环境调试运行。' },
  pages: { label: 'Page 管理', description: '独立维护页面对象与元素定义。' },
  scenarios: { label: '场景测试', description: '浏览测试场景与公共流程，选择环境执行场景。' },
  configuration: { label: '配置', description: '按项目维护配置、环境和测试账号，供接口、Page 与场景使用。' },
} as const

export type WorkspaceSection = keyof typeof SECTIONS
export type AssetSection = WorkspaceSection

export function sectionPath(section: WorkspaceSection, projectId?: string): string {
  return `/${section}${projectId ? `/${projectId.split('/').map(encodeURIComponent).join('/')}` : ''}`
}

const PROJECT_KEY = 'testplat.control.selectedProject'

export function readPreferredProject(): string | null {
  try {
    return localStorage.getItem(PROJECT_KEY)
  } catch {
    return null
  }
}

export function writePreferredProject(projectId: string): void {
  try {
    localStorage.setItem(PROJECT_KEY, projectId)
  } catch {
    // 项目仍由 URL 定位；存储不可用不阻止导航。
  }
}
