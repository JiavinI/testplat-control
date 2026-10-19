import { describe, expect, it } from 'vitest'
import { serializeRunParams, validateRequiredParams } from './serializeParams'
import type { ParamInfo } from './types'

const form: ParamInfo[] = [
  { name: 'username', type: 'string', required: true, description: null },
  { name: 'nickname', type: 'string', required: false, description: null },
  { name: 'age', type: 'number', required: false, description: null },
  { name: 'count', type: 'number', required: true, description: null },
  { name: 'active', type: 'boolean', required: false, description: null },
  { name: 'agree', type: 'boolean', required: true, description: null },
]

describe('serializeRunParams', () => {
  it('对象数组在运行时解析，编辑预览容忍未完成 JSON', () => {
    const form: ParamInfo[] = [
      { name: 'product', type: 'object', required: true, description: null },
      { name: 'items', type: 'array', required: true, description: null },
    ]
    expect(serializeRunParams(form, { product: '{' })).toEqual({ product: '{' })
    expect(() => serializeRunParams(form, { product: '{' }, true)).toThrow('合法 JSON')
    expect(() => serializeRunParams(form, { product: '[]' }, true)).toThrow('对象')
    expect(() => serializeRunParams(form, { items: '{}' }, true)).toThrow('数组')
    expect(serializeRunParams(form, { product: '{"id":0}', items: '[false]' }, true)).toEqual({
      product: { id: 0 }, items: [false],
    })
  })
  it('转换 string / number / boolean 类型', () => {
    const params = serializeRunParams(form, {
      username: 'alice',
      age: '18',
      count: 3,
      agree: true,
      active: 'false',
    })
    expect(params).toEqual({
      username: 'alice',
      age: 18,
      count: 3,
      agree: true,
      active: false,
    })
  })

  it('空的非必填 string/number 省略', () => {
    const params = serializeRunParams(form, {
      username: 'alice',
      nickname: '',
      age: '',
      count: 1,
      agree: false,
      active: undefined,
    })
    expect(params).toEqual({
      username: 'alice',
      count: 1,
      agree: false,
    })
    expect(params).not.toHaveProperty('nickname')
    expect(params).not.toHaveProperty('age')
    expect(params).not.toHaveProperty('active')
  })

  it('保留 boolean false，不因 falsy 遗漏', () => {
    const params = serializeRunParams(form, {
      username: 'bob',
      count: 0,
      agree: false,
      active: false,
    })
    expect(params.agree).toBe(false)
    expect(params.active).toBe(false)
    expect(params.count).toBe(0)
  })
})

describe('validateRequiredParams', () => {
  it('缺必填时返回字段错误', () => {
    const errors = validateRequiredParams(form, {
      nickname: 'x',
    })
    expect(errors.username).toBeTruthy()
    expect(errors.count).toBeTruthy()
    expect(errors.agree).toBeTruthy()
  })
})
