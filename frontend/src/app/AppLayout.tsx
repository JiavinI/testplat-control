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
          gap: 12,
          paddingInline: 16,
          height: 48,
          lineHeight: '48px',
          background: '#111827',
        }}
      >
        <Typography.Text strong style={{ color: '#fff', fontSize: 14, letterSpacing: 0.2 }}>
          TestPlat Control
        </Typography.Text>
        <Typography.Text style={{ color: 'rgba(255,255,255,0.55)', fontSize: 12 }}>
          控制台
        </Typography.Text>
      </Header>
      <Content
        style={{
          padding: 12,
          background: '#f0f2f5',
          overflowX: 'hidden',
          maxWidth: '100vw',
        }}
      >
        <div
          style={{
            background: '#fff',
            padding: 12,
            borderRadius: 4,
            border: '1px solid #e5e7eb',
            minHeight: 'calc(100vh - 72px)',
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
