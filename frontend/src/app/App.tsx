import { ConfigProvider, App as AntApp } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from 'react-router-dom'
import { createAppQueryClient } from './queryClient'
import { router } from './router'
import { ErrorBoundary } from '@/shared/ui/ErrorBoundary'

const queryClient = createAppQueryClient()

export function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      componentSize="middle"
      theme={{
        token: {
          // 工具台：冷灰蓝主色、小圆角、略紧字阶与控件高度
          colorPrimary: '#1f5fbf',
          colorInfo: '#1f5fbf',
          colorSuccess: '#2f7d4a',
          colorWarning: '#b7791f',
          colorError: '#c53d3d',
          colorBgLayout: '#f0f2f5',
          colorBgContainer: '#ffffff',
          colorBorder: '#d9dde3',
          colorText: 'rgba(0, 0, 0, 0.88)',
          colorTextSecondary: 'rgba(0, 0, 0, 0.55)',
          borderRadius: 4,
          borderRadiusLG: 6,
          fontSize: 13,
          fontSizeHeading4: 16,
          fontSizeHeading5: 14,
          controlHeight: 32,
          controlHeightSM: 24,
          padding: 12,
          paddingSM: 8,
          paddingLG: 16,
          margin: 12,
          fontFamily:
            "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif",
        },
        components: {
          Layout: {
            headerHeight: 48,
            headerBg: '#111827',
            bodyBg: '#f0f2f5',
          },
          Card: {
            paddingLG: 12,
          },
          Table: {
            cellPaddingBlockSM: 6,
            cellPaddingInlineSM: 8,
          },
        },
      }}
    >
      <AntApp>
        <QueryClientProvider client={queryClient}>
          <ErrorBoundary>
            <RouterProvider router={router} />
          </ErrorBoundary>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  )
}
