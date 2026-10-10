import { Alert, Button, Empty, Spin } from 'antd'
import type { ReactNode } from 'react'
import { formatErrorMessage } from './errorMessage'

interface LoadingStateProps {
  tip?: string
}

export function LoadingState({ tip = '加载中…' }: LoadingStateProps) {
  return (
    <div role="status" aria-live="polite" aria-busy="true">
      <Spin tip={tip}>
        <div style={{ padding: 48, minHeight: 96 }} />
      </Spin>
    </div>
  )
}

interface EmptyStateProps {
  description?: ReactNode
  action?: ReactNode
}

export function EmptyState({
  description = '暂无数据',
  action,
}: EmptyStateProps) {
  return (
    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={description}>
      {action}
    </Empty>
  )
}

interface ErrorStateProps {
  error: unknown
  onRetry?: () => void
  title?: string
}

export function ErrorState({
  error,
  onRetry,
  title = '加载失败',
}: ErrorStateProps) {
  return (
    <Alert
      type="error"
      showIcon
      role="alert"
      message={title}
      description={formatErrorMessage(error)}
      action={
        onRetry ? (
          <Button size="small" onClick={onRetry} aria-label="重试">
            重试
          </Button>
        ) : undefined
      }
    />
  )
}
