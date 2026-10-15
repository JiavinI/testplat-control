import { describe, expect, it } from 'vitest'
import { shortSha, syncResultLabel } from './display'

describe('shortSha / syncResultLabel', () => {
  it('shortSha 截断为 7 位', () => {
    expect(shortSha('abcdef0123456789')).toBe('abcdef0')
    expect(shortSha(null)).toBe('—')
    expect(shortSha('abc')).toBe('abc')
  })

  it('同步类别中文文案', () => {
    expect(syncResultLabel('ok')).toBe('成功')
    expect(syncResultLabel('network')).toBe('网络错误')
    expect(syncResultLabel('auth')).toBe('认证失败')
    expect(syncResultLabel('invalid_manifest')).toBe('清单非法')
    expect(syncResultLabel('timeout')).toBe('超时')
    expect(syncResultLabel(null)).toBe('尚未同步')
  })
})
