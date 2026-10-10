import { ConfigProvider, App as AntApp } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from 'react-router-dom'
import { createAppQueryClient } from './queryClient'
import { router } from './router'

const queryClient = createAppQueryClient()

export function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      // 克制紧凑：偏测试工具密度，避免过大留白
      componentSize="middle"
      theme={{
        token: {
          borderRadius: 4,
          fontSize: 13,
          controlHeight: 32,
        },
      }}
    >
      <AntApp>
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  )
}
