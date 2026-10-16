import { Collapse, Tabs } from 'antd'
import { AccountSection } from './AccountSection'
import { EnvironmentSection } from './EnvironmentSection'

/** 项目详情里的环境与测试账号入口。运行页通过「去配置」打开这一块。 */
export function ProjectConfigPanel({
  projectId,
  open,
  onOpenChange,
}: {
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Collapse
      style={{ marginBottom: 12 }}
      activeKey={open ? ['config'] : []}
      onChange={(keys) => {
        const list = Array.isArray(keys) ? keys : [keys]
        onOpenChange(list.includes('config'))
      }}
      items={[
        {
          key: 'config',
          label: '环境与账号',
          children: (
            <Tabs
              items={[
                {
                  key: 'environments',
                  label: '环境管理',
                  children: <EnvironmentSection key={projectId} projectId={projectId} />,
                },
                {
                  key: 'accounts',
                  label: '测试账号',
                  children: <AccountSection key={projectId} projectId={projectId} />,
                },
              ]}
            />
          ),
        },
      ]}
    />
  )
}
