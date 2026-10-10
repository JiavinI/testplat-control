import { ConfigProvider, App as AntApp } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from 'react-router-dom'
import { createAppQueryClient } from './queryClient'
import { router } from './router'
import { ErrorBoundary } from '@/shared/ui/ErrorBoundary'

const queryClient = createAppQueryClient()

/** P2 品牌编辑感：石色画布 + 白卡片 + 鼠尾草绿强调，产品平台而非工具 HUD。ConfigProvider 保持 antd 默认 motion；额外克制动效见 styles.css。 */
const editorialBrandTheme = {
  token: {
    colorPrimary: '#6b7f6a',
    colorInfo: '#6b7f6a',
    colorSuccess: '#4d7c57',
    colorWarning: '#b45309',
    colorError: '#b91c1c',
    colorBgLayout: '#fafaf9',
    colorBgContainer: '#ffffff',
    colorBgElevated: '#ffffff',
    colorBorder: '#e7e5e4',
    colorBorderSecondary: '#f5f5f4',
    colorText: '#1c1917',
    colorTextSecondary: '#78716c',
    colorTextTertiary: '#a8a29e',
    colorLink: '#6b7f6a',
    colorLinkHover: '#5a6b59',
    borderRadius: 12,
    borderRadiusLG: 16,
    borderRadiusSM: 10,
    fontSize: 14,
    fontSizeHeading1: 38,
    fontSizeHeading2: 28,
    fontSizeHeading3: 22,
    fontSizeHeading4: 20,
    fontSizeHeading5: 16,
    lineHeight: 1.55,
    controlHeight: 34,
    controlHeightSM: 28,
    controlHeightLG: 40,
    padding: 16,
    paddingSM: 12,
    paddingLG: 24,
    margin: 16,
    boxShadow:
      '0 1px 2px rgba(28, 25, 23, 0.03), 0 4px 12px rgba(28, 25, 23, 0.04)',
    boxShadowSecondary:
      '0 1px 2px rgba(28, 25, 23, 0.04), 0 6px 16px rgba(28, 25, 23, 0.06)',
    fontFamily:
      "'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Noto Sans SC', -apple-system, BlinkMacSystemFont, Roboto, 'Helvetica Neue', Arial, sans-serif",
  },
  components: {
    Layout: {
      headerHeight: 56,
      headerBg: '#ffffff',
      bodyBg: '#fafaf9',
      siderBg: '#ffffff',
    },
    Card: {
      paddingLG: 20,
      borderRadiusLG: 16,
    },
    Table: {
      cellPaddingBlockSM: 8,
      cellPaddingInlineSM: 10,
      headerBg: '#fafaf9',
      rowHoverBg: '#f5f5f4',
    },
    Button: {
      borderRadius: 12,
      primaryShadow: '0 2px 6px rgba(107, 127, 106, 0.22)',
      colorPrimaryHover: '#5a6b59',
      colorPrimaryActive: '#4f5f4e',
    },
    Menu: {
      itemBg: '#ffffff',
      subMenuItemBg: '#fafaf9',
      itemSelectedBg: 'rgba(107, 127, 106, 0.12)',
      itemSelectedColor: '#5a6b59',
      itemHoverBg: '#f5f5f4',
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
      theme={editorialBrandTheme}
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
