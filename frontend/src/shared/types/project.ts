/**
 * 与后端 schemas.ProjectCreate / ProjectUpdate / ProjectResponse 对齐的 DTO。
 * 字段名与校验语义保持一致，避免前端另行发明契约。
 */

export interface ProjectCreate {
  name: string
  env?: string
  assets_root: string
  config_root: string
}

export interface ProjectUpdate {
  name?: string
  env?: string
  assets_root?: string
  config_root?: string
}

export interface ProjectResponse {
  id: string
  name: string
  env: string
  assets_root: string
  config_root: string
  created_at: string
  updated_at: string
}
