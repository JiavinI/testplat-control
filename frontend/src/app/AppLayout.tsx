import { App, Button, Layout, Space, Typography } from 'antd'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { ApiOutlined, DesktopOutlined, ExperimentOutlined, SettingOutlined } from '@ant-design/icons'
import { SECTIONS, sectionPath, type WorkspaceSection } from '@/shared/project/sections'
import { useLogout, useMe } from '@/features/auth/hooks'
import { formatErrorMessage } from '@/shared/ui/errorMessage'

const { Header, Content } = Layout

/** P2 品牌编辑感壳：浅色产品顶栏 + 石色内容区，鼠尾草绿品牌色 */
export function AppLayout() {
  const { message } = App.useApp()
  const me = useMe()
  const logout = useLogout()
  const operator = me.data?.username
  const location = useLocation()
  const segments = location.pathname.split('/').filter(Boolean)
  const projectSuffix = segments.length === 3 ? `/${segments[1]}/${segments[2]}` : ''
  const navigation: { section: WorkspaceSection; icon: React.ReactNode }[] = [
    { section: 'apis', icon: <ApiOutlined /> },
    { section: 'pages', icon: <DesktopOutlined /> },
    { section: 'scenarios', icon: <ExperimentOutlined /> },
    { section: 'configuration', icon: <SettingOutlined /> },
  ]

  return (
    <Layout className="tp-shell" style={{ minHeight: '100vh' }}>
      <Header
        className="tp-shell__header"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 14,
          paddingInline: 24,
          height: 56,
          lineHeight: '56px',
          background: '#ffffff',
          borderBottom: '1px solid #e7e5e4',
        }}
      >
        <Typography.Text
          strong
          className="tp-shell__brand"
          style={{
            color: '#6b7f6a',
            fontSize: 18,
            letterSpacing: 0.4,
            lineHeight: 1.2,
          }}
        >
          TestPlat Control
        </Typography.Text>
        <Typography.Text
          style={{
            color: '#78716c',
            fontSize: 13,
            letterSpacing: 0.2,
          }}
        >
          自动化测试平台
        </Typography.Text>
        <div style={{ marginLeft: 'auto' }}>
          {operator ? (
            <Space size={12}>
              <Typography.Text data-testid="current-operator">
                当前操作人 {operator}
              </Typography.Text>
              <Button
                size="small"
                data-testid="logout-button"
                loading={logout.isPending}
                onClick={() => {
                  void logout.mutateAsync().catch((error: unknown) => {
                    message.error(formatErrorMessage(error))
                  })
                }}
              >
                注销
              </Button>
            </Space>
          ) : null}
        </div>
      </Header>
      <div className="tp-shell__body">
        {operator ? (
          <nav className="tp-primary-nav" aria-label="功能菜单">
            {navigation.map(({ section, icon }) => (
              <NavLink
                aria-label={SECTIONS[section].label}
                key={section}
                to={`${sectionPath(section)}${projectSuffix}`}
                className={({ isActive }) => `tp-primary-nav__item${isActive ? ' is-active' : ''}`}
              >
                {icon}
                <span>{SECTIONS[section].label}</span>
              </NavLink>
            ))}
          </nav>
        ) : null}
        <Content
          className="tp-shell__content"
          style={{
            padding: 20,
            background: '#fafaf9',
            overflowX: 'hidden',
            minWidth: 0,
          }}
        >
          <div
            className="tp-shell__panel"
            style={{
              background: '#ffffff',
              padding: 20,
              borderRadius: 16,
              border: '1px solid #e7e5e4',
              boxShadow:
                '0 1px 2px rgba(28, 25, 23, 0.03), 0 4px 12px rgba(28, 25, 23, 0.04)',
              minHeight: 'calc(100vh - 96px)',
              maxWidth: '100%',
              overflowX: 'hidden',
            }}
          >
            <Outlet />
          </div>
        </Content>
      </div>
    </Layout>
  )
}
