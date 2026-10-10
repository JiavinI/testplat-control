/**
 * 与后端 AssetNodeResponse / AssetDetailsResponse 对齐的 DTO。
 * 字段名保持 snake-free 业务字段一致：id/name/type/path/children/metadata。
 */

export type AssetNodeType = 'directory' | 'file'

export interface AssetNode {
  id: string
  name: string
  type: AssetNodeType
  path: string
  children?: AssetNode[] | null
  metadata?: Record<string, unknown> | null
}

export interface AssetDetails {
  id: string
  name: string
  type: AssetNodeType
  path: string
  metadata?: Record<string, unknown> | null
}
