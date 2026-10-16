import { describe, expect, it } from 'vitest'
import { ApiHttpError } from '@/shared/api/errors'
import { extractAccountName, formatRunFailure } from './accountFailure'

describe('formatRunFailure', () => {
  it('从身份不存在文案补上账号名和当前环境', () => {
    const error = new ApiHttpError(422, '身份不存在: gsb', '')
    expect(formatRunFailure(error, 'pre')).toBe(
      '账号 gsb 在环境 pre 缺失或不可用。身份不存在: gsb',
    )
    expect(extractAccountName('身份 gsb 不可用: 账号 gsb 在环境 test 已停用')).toBe('gsb')
  })

  it('无关错误保持原文', () => {
    const error = new ApiHttpError(422, '参数缺失', '')
    expect(formatRunFailure(error, 'test')).toBe('参数缺失')
  })
})
