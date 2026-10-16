import type { ReactNode } from 'react'
import { Tabs } from 'antd'
import { AccountSection } from './AccountSection'
import { EnvironmentSection } from './EnvironmentSection'

/** 配置菜单中的项目级配置；离开页签时销毁凭据和编辑草稿。 */
export function ProjectConfigPanel({ projectId, projectSettings, activeTab, onTabChange }: {
  projectId: string
  projectSettings?: ReactNode
  activeTab?: string
  onTabChange?: (tab: string) => void
}) {
  return (
    <Tabs
      activeKey={activeTab}
      onChange={onTabChange}
      destroyOnHidden
      items={[
        ...(projectSettings ? [{ key: 'project', label: '项目配置', children: projectSettings }] : []),
        { key: 'environments', label: '环境管理', children: <EnvironmentSection key={projectId} projectId={projectId} /> },
        { key: 'accounts', label: '测试账号', children: <AccountSection key={projectId} projectId={projectId} /> },
      ]}
    />
  )
}
