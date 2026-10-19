import { useState } from 'react'
import { Alert, Descriptions, Typography } from 'antd'
import { useSearchParams } from 'react-router-dom'
import { AssetBrowser } from '@/features/assets'
import { ProjectConfigPanel } from '@/features/environments/ProjectConfigPanel'
import type { ProjectResponse } from '@/shared/types/project'
import { shortSha } from '@/shared/project/display'

export function ProjectConfigurationPage({ project }: { project: ProjectResponse }) {
  const [params, setParams] = useSearchParams()
  const [selectedAssetId, setSelectedAssetId] = useState<string>()
  const tab = params.get('tab')
  const activeKey = tab === 'environments' || tab === 'accounts' ? tab : 'project'

  return (
    <ProjectConfigPanel
      projectId={project.id}
      activeTab={activeKey}
      onTabChange={(key) => setParams(key === 'project' ? {} : { tab: key })}
      projectSettings={
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Descriptions size="small" column={{ xs: 1, sm: 2 }} bordered>
            <Descriptions.Item label="项目">{project.name}</Descriptions.Item>
            <Descriptions.Item label="项目 ID"><Typography.Text code>{project.id}</Typography.Text></Descriptions.Item>
            <Descriptions.Item label="仓库">{project.repo}</Descriptions.Item>
            <Descriptions.Item label="Commit"><Typography.Text code>{shortSha(project.commit_sha)}</Typography.Text></Descriptions.Item>
            <Descriptions.Item label="默认环境">{project.default_env ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="状态">{project.archived ? '已归档' : '使用中'}</Descriptions.Item>
          </Descriptions>
          <Alert type="info" showIcon message="项目配置文件来自 Git；运行使用本项目在「环境管理」「测试账号」中维护的配置。" />
          <AssetBrowser projectId={project.id} section="configuration" selectedAssetId={selectedAssetId} onSelectAsset={(asset) => setSelectedAssetId(asset.id)} />
        </div>
      }
    />
  )
}
