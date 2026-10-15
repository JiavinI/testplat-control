import { encodePath } from '@/shared/api/client'
import { ApiParseError } from '@/shared/api/errors'

/**
 * 项目主键为 "{repo}/{project}"；API 两段式路由禁止把整段 id 当成单段 %2F 编码。
 */
export function splitProjectId(projectId: string): { repo: string; project: string } {
  const slash = projectId.indexOf('/')
  if (slash <= 0 || slash === projectId.length - 1 || projectId.indexOf('/', slash + 1) !== -1) {
    throw new ApiParseError('projectId 须为 {repo}/{project}', projectId)
  }
  return {
    repo: projectId.slice(0, slash),
    project: projectId.slice(slash + 1),
  }
}

/** 拼出 /repos/{repo}/projects/{project}/... 路径 */
export function projectResourcePath(projectId: string, ...rest: Array<string | number>): string {
  const { repo, project } = splitProjectId(projectId)
  return encodePath(['repos', repo, 'projects', project, ...rest])
}

export function joinProjectId(repo: string, project: string): string {
  return `${repo}/${project}`
}
