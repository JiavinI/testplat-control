import { Layout, Typography } from 'antd'
import { Outlet } from 'react-router-dom'

const { Header, Content } = Layout

/** P2 品牌编辑感壳：浅色产品顶栏 + 石色内容区，鼠尾草绿品牌色 */
export function AppLayout() {
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
          接口测试平台
        </Typography.Text>
      </Header>
      <Content
        className="tp-shell__content"
        style={{
          padding: 20,
          background: '#fafaf9',
          overflowX: 'hidden',
          maxWidth: '100vw',
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
    </Layout>
  )
}
