import { Layout, Typography } from 'antd'
import { Outlet } from 'react-router-dom'

const { Header, Content } = Layout

export function AppLayout() {
  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 16,
          paddingInline: 20,
          height: 48,
          lineHeight: '48px',
          background: '#001529',
        }}
      >
        <Typography.Text strong style={{ color: '#fff', fontSize: 15 }}>
          TestPlat Control
        </Typography.Text>
        <Typography.Text style={{ color: 'rgba(255,255,255,0.65)', fontSize: 12 }}>
          通用接口自动化测试平台
        </Typography.Text>
      </Header>
      <Content style={{ padding: 16, background: '#f5f5f5', overflowX: 'hidden' }}>
        <div
          style={{
            background: '#fff',
            padding: 16,
            borderRadius: 6,
            minHeight: 'calc(100vh - 80px)',
            maxWidth: '100%',
            overflowX: 'hidden',
          }}
        >
          <Outlet />
        </div>
      </Content>
    </Layout>
  )
}
