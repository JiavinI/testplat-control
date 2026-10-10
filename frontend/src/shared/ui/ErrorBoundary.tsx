import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Alert, Button } from 'antd'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

/** 捕获渲染期异常，避免畸形数据导致整页白屏。 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('UI render error', error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <Alert
          type="error"
          showIcon
          role="alert"
          message="页面渲染失败"
          description={this.state.error.message || '发生未知错误'}
          action={
            <Button
              size="small"
              onClick={() => {
                this.setState({ error: null })
                window.location.assign('/projects')
              }}
            >
              返回项目列表
            </Button>
          }
        />
      )
    }
    return this.props.children
  }
}
