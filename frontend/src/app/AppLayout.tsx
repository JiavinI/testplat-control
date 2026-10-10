import { Layout, Typography } from 'antd'
import { Outlet } from 'react-router-dom'

const { Header, Content } = Layout

/** C3 暖沙工作室壳：深暖石色顶栏 + 沙色内容区，柔圆角与轻阴影 */
export function AppLayout() {
  return (
    <Layout className="tp-shell" style={{ minHeight: '100vh' }}>
      <Header
        className="tp-shell__header"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 14,
          paddingInline: 20,
          height: 56,
          lineHeight: '56px',
          background: '#44403c',
          borderBottom: '1px solid rgba(255, 253, 248, 0.08)',
        }}
      >
        <Typography.Text
          strong
          className="tp-shell__brand"
          style={{
            color: '#fffdf8',
            fontSize: 18,
            letterSpacing: 0.6,
            lineHeight: 1.2,
          }}
        >
          TestPlat Control
        </Typography.Text>
        <Typography.Text
          style={{
            color: 'rgba(255, 253, 248, 0.55)',
            fontSize: 13,
            letterSpacing: 0.2,
          }}
        >
          暖沙工作室 · 控制台
        </Typography.Text>
      </Header>
      <Content
        className="tp-shell__content"
        style={{
          padding: 16,
          background: '#f5efe6',
          overflowX: 'hidden',
          maxWidth: '100vw',
        }}
      >
        <div
          className="tp-shell__panel"
          style={{
            background: '#fffdf8',
            padding: 16,
            borderRadius: 14,
            border: '1px solid #e7e0d5',
            boxShadow:
              '0 1px 2px rgba(41, 37, 36, 0.04), 0 4px 12px rgba(41, 37, 36, 0.06)',
            minHeight: 'calc(100vh - 88px)',
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
