import type { PropsWithChildren } from 'react'
import { act, renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { projectKeys } from '@/features/projects/hooks'
import { environmentKeys, useUpdateEnvironment } from './hooks'

vi.mock('./api', () => ({ updateEnvironment: vi.fn().mockResolvedValue({ revision: 2 }) }))

describe('共享配置缓存', () => {
  it('网站入口保存环境后，GSB 和平台项目列表的缓存也失效', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } })
    const keys = [environmentKeys.list('main/gsb'), environmentKeys.accounts('main/gsb', 'test'), projectKeys.detail('main/gsb'), projectKeys.lists()]
    for (const key of keys) client.setQueryData(key, [])
    function Wrapper({ children }: PropsWithChildren) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>
    }
    const { result } = renderHook(() => useUpdateEnvironment('main/go2'), { wrapper: Wrapper })
    await act(async () => { await result.current.mutateAsync({ env: 'test', body: { revision: 1, api_hosts: { sso: 'http://localhost' } } }) })
    for (const key of keys) expect(client.getQueryState(key)?.isInvalidated).toBe(true)
    client.clear()
  })
})
