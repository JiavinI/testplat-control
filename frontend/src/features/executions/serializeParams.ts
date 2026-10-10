import type { ParamInfo } from './types'

/**
 * 把表单原始值序列化为后端 RunRequest.params。
 * - 空的非必填 string/number 省略，不发送 null/undefined/''
 * - boolean 的 false 是合法值，不能因 falsy 被丢掉
 * - 类型按 ParamInfo 转换；非法 number 仍原样交由后端 422
 */
export function serializeRunParams(
  form: ParamInfo[],
  values: Record<string, unknown>,
): Record<string, string | number | boolean> {
  const params: Record<string, string | number | boolean> = {}

  for (const item of form) {
    const raw = values[item.name]

    if (item.type === 'boolean') {
      if (raw === undefined || raw === null || raw === '') {
        continue
      }
      if (typeof raw === 'boolean') {
        params[item.name] = raw
        continue
      }
      if (raw === 'true' || raw === 'false') {
        params[item.name] = raw === 'true'
        continue
      }
      params[item.name] = Boolean(raw)
      continue
    }

    if (item.type === 'number') {
      if (raw === undefined || raw === null || raw === '') {
        continue
      }
      if (typeof raw === 'number') {
        params[item.name] = raw
        continue
      }
      const parsed = Number(raw)
      params[item.name] = Number.isFinite(parsed) ? parsed : (raw as never)
      continue
    }

    // 字符串：空串视为未填，省略
    if (raw === undefined || raw === null) {
      continue
    }
    const text = typeof raw === 'string' ? raw : String(raw)
    if (text === '') {
      continue
    }
    params[item.name] = text
  }

  return params
}

/** 前端必填即时校验：缺值返回字段错误；最终仍以后端 422 为准 */
export function validateRequiredParams(
  form: ParamInfo[],
  values: Record<string, unknown>,
): Record<string, string> {
  const errors: Record<string, string> = {}
  for (const item of form) {
    if (!item.required) {
      continue
    }
    const raw = values[item.name]
    if (item.type === 'boolean') {
      if (raw === undefined || raw === null || raw === '') {
        errors[item.name] = '请选择该参数'
      }
      continue
    }
    if (raw === undefined || raw === null || raw === '') {
      errors[item.name] = '请填写该参数'
    }
  }
  return errors
}
