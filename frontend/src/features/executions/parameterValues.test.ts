import { describe, expect, it } from 'vitest'
import { formatParameterValue, resolveParameterValues, validParameterDefault } from './parameterValues'

describe('参数预览与运行的覆盖语义', () => {
  it('按键存在性覆盖，保留 false、0、空串和 null，对象整体替换', () => {
    const rows = resolveParameterValues(
      { active: true, count: 8, keyword: 'asset', filter: { a: 1, b: 2 }, empty: 'asset' },
      { active: false, count: 0, keyword: '', filter: { a: 3 } },
      { empty: null },
    )
    expect(Object.fromEntries(rows.map((row) => [row.name, row.effective]))).toEqual({
      active: false, count: 0, keyword: '', filter: { a: 3 }, empty: null,
    })
    expect(rows.find((row) => row.name === 'empty')?.source).toBe('temporary')
  })

  it('接口只展示声明字段；无效环境值不回退成看似可用的资产值', () => {
    const [row] = resolveParameterValues({ count: 8 }, { count: null, unrelated: 'other-api' }, {}, ['count'])
    expect(row.source).toBe('environment')
    expect(row.effective).toBeNull()
    expect(validParameterDefault({ name: 'count', type: 'number', required: true, description: null }, row)).toBe(false)
    expect(resolveParameterValues({}, {}, {}, ['missing'])[0].source).toBe('unset')
  })

  it('隐藏敏感顶层和嵌套字段，保留普通业务值', () => {
    expect(formatParameterValue('password', 'fake-secret')).toBe('••••••')
    expect(formatParameterValue('filter', { count: 0, nested: { 'X-API-Key': 'fake-key', Cookie: 'fake-cookie' } })).toBe('{"count":0,"nested":{"X-API-Key":"••••••","Cookie":"••••••"}}')
  })
})
