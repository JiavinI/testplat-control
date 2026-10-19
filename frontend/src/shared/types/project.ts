/**
 * 与后端 schemas.ProjectResponse / RepoResponse / SyncResponse 对齐的 DTO。
 * Phase 4.0：项目只读，来自 Git 清单；已移除 assets_root / config_root / 单 env 字段。
 */

export interface WorkspaceContext {
  platform: string
  platform_name: string
  project: string
  project_name: string
  configuration_project_id: string
}

export interface ProjectResponse {
  workspace?: WorkspaceContext | null
  id: string
  repo: string
  project: string
  name: string
  envs: string[]
  default_env: string | null
  archived: boolean
  commit_sha: string | null
  created_at: string
  updated_at: string
}

/** 同步失败/成功类别；API 永不回显 git 原文或仓库 URL */
export type SyncResultCategory =
  | 'ok'
  | 'network'
  | 'auth'
  | 'invalid_manifest'
  | 'timeout'

export interface RepoResponse {
  key: string
  branch: string
  current_sha: string | null
  last_sync_at: string | null
  last_sync_result: SyncResultCategory | string | null
}

export interface SyncResponse {
  repo: string
  ok: boolean
  category: SyncResultCategory | string
  commit_sha: string | null
}
