import { ConfigProvider, App as AntApp } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from 'react-router-dom'
import { createAppQueryClient } from './queryClient'
import { router } from './router'
import { ErrorBoundary } from '@/shared/ui/ErrorBoundary'

const queryClient = createAppQueryClient()

/** C3 暖沙工作室：暖灰沙底 + 赤陶强调，浅色长时操作友好 */
const warmSandTheme = {
  token: {
    colorPrimary: '#c2410c',
    colorInfo: '#c2410c',
    colorSuccess: '#3f6212',
    colorWarning: '#a16207',
    colorError: '#b91c1c',
    colorBgLayout: '#f5efe6',
    colorBgContainer: '#fffdf8',
    colorBgElevated: '#fffdf8',
    colorBorder: '#e7e0d5',
    colorBorderSecondary: '#efe8dc',
    colorText: '#292524',
    colorTextSecondary: '#78716c',
    colorTextTertiary: '#a8a29e',
    colorLink: '#c2410c',
    colorLinkHover: '#9a3412',
    borderRadius: 10,
    borderRadiusLG: 14,
    borderRadiusSM: 8,
    fontSize: 14,
    fontSizeHeading1: 36,
    fontSizeHeading2: 28,
    fontSizeHeading3: 22,
    fontSizeHeading4: 20,
    fontSizeHeading5: 16,
    lineHeight: 1.55,
    controlHeight: 34,
    controlHeightSM: 28,
    controlHeightLG: 40,
    padding: 14,
    paddingSM: 10,
    paddingLG: 20,
    margin: 14,
    boxShadow:
      '0 1px 2px rgba(41, 37, 36, 0.04), 0 4px 12px rgba(41, 37, 36, 0.06)',
    boxShadowSecondary:
      '0 1px 2px rgba(41, 37, 36, 0.05), 0 6px 16px rgba(41, 37, 36, 0.08)',
    fontFamily:
      "'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Noto Sans SC', -apple-system, BlinkMacSystemFont, Roboto, 'Helvetica Neue', Arial, sans-serif",
  },
  components: {
    Layout: {
      headerHeight: 56,
      headerBg: '#44403c',
      bodyBg: '#f5efe6',
      siderBg: '#44403c',
    },
    Card: {
      paddingLG: 16,
      borderRadiusLG: 14,
    },
    Table: {
      cellPaddingBlockSM: 8,
      cellPaddingInlineSM: 10,
      headerBg: '#faf6f0',
      rowHoverBg: '#faf6f0',
    },
    Button: {
      borderRadius: 10,
      primaryShadow: '0 2px 6px rgba(194, 65, 12, 0.28)',
    },
    Menu: {
      darkItemBg: '#44403c',
      darkSubMenuItemBg: '#3f3a36',
      darkItemSelectedBg: '#c2410c',
    },
    Typography: {
      titleMarginBottom: '0.35em',
      titleMarginTop: '0.6em',
    },
  },
} as const

export function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      componentSize="middle"
      theme={warmSandTheme}
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
