import { Outlet } from 'react-router-dom'
import { ErrorState, LoadingState } from '@/shared/ui/AsyncState'
import { LoginPage } from './LoginPage'
import { useMe } from './hooks'

/** 没有会话时就地显示登录，而不是把 401 原文留在业务页。 */
export function RequireAuth() {
  const me = useMe()

  if (me.isLoading) {
    return <LoadingState tip="正在确认登录状态…" />
  }

  if (me.isError) {
    return (
      <ErrorState
        error={me.error}
        title="无法确认登录状态"
        onRetry={() => {
          void me.refetch()
        }}
      />
    )
  }

  if (!me.data) {
    return <LoginPage />
  }

  return <Outlet />
}
