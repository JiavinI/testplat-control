import { Alert, Button, Form, Input, Tabs, Typography } from 'antd'
import { useState } from 'react'
import { ApiHttpError } from '@/shared/api/errors'
import { formatErrorMessage } from '@/shared/ui/errorMessage'
import { useLogin, useRegister } from './hooks'

const USERNAME_RE = /^[A-Za-z][A-Za-z0-9_]{2,31}$/

type Mode = 'login' | 'register'

interface AuthFormValues {
  username: string
  password: string
}

/**
 * 平台登录只识别操作人。密码提交后不回显、不写入本地存储。
 * 没有单独的「测试登录」；这里的登录是平台会话，不是被测系统账号。
 */
export function LoginPage() {
  const [mode, setMode] = useState<Mode>('login')
  const [formError, setFormError] = useState<string | null>(null)
  const loginMutation = useLogin()
  const registerMutation = useRegister()
  const pending = loginMutation.isPending || registerMutation.isPending

  const submit = async (values: AuthFormValues) => {
    setFormError(null)
    const username = values.username.trim()
    const password = values.password
    if (!USERNAME_RE.test(username)) {
      setFormError('用户名需为 3–32 位字母、数字或下划线，且以字母开头')
      return
    }
    if (password.length < 8 || password.length > 128 || /[\r\n\0]/.test(password)) {
      setFormError('密码长度需在 8–128 之间，且不能含换行或空字符')
      return
    }
    try {
      if (mode === 'register') {
        await registerMutation.mutateAsync({ username, password })
      } else {
        await loginMutation.mutateAsync({ username, password })
      }
    } catch (error) {
      if (error instanceof ApiHttpError && error.status === 401) {
        setFormError('用户名或密码错误')
        return
      }
      setFormError(formatErrorMessage(error))
    }
  }

  return (
    <div data-testid="login-page" style={{ maxWidth: 420, margin: '24px auto' }}>
      <Typography.Title level={3} className="tp-page-title" style={{ marginTop: 0 }}>
        {mode === 'login' ? '登录' : '注册'}
      </Typography.Title>
      <Typography.Paragraph type="secondary" data-testid="login-guidance">
        请先登录。未登录时配置与执行会返回 401。注册后即可维护项目环境并运行。
      </Typography.Paragraph>
      <Tabs
        activeKey={mode}
        onChange={(key) => {
          setMode(key === 'register' ? 'register' : 'login')
          setFormError(null)
        }}
        items={[
          { key: 'login', label: '登录' },
          { key: 'register', label: '注册' },
        ]}
      />
      {formError ? (
        <Alert
          type="error"
          showIcon
          role="alert"
          style={{ marginBottom: 12 }}
          message={formError}
          data-testid="login-error"
        />
      ) : null}
      <Form<AuthFormValues>
        layout="vertical"
        requiredMark={false}
        onFinish={(values) => {
          void submit(values)
        }}
        disabled={pending}
      >
        <Form.Item
          label="用户名"
          name="username"
          rules={[{ required: true, message: '请填写用户名' }]}
        >
          <Input autoComplete="username" aria-label="用户名" data-testid="auth-username" />
        </Form.Item>
        <Form.Item
          label="密码"
          name="password"
          rules={[{ required: true, message: '请填写密码' }]}
        >
          <Input.Password
            autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
            aria-label="密码"
            data-testid="auth-password"
          />
        </Form.Item>
        <Button
          type="primary"
          htmlType="submit"
          loading={pending}
          data-testid="auth-submit"
        >
          {mode === 'register' ? '注册并登录' : '登录'}
        </Button>
      </Form>
    </div>
  )
}
