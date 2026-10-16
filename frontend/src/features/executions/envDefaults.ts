/**
 * 环境 case_params 里是否已经有可用默认值。
 * 空白字符串不算；false 和 0 算。请求仍省略空白项，不把默认值抄进运行参数。
 */
export function hasEnvCaseDefault(
  caseParams: Record<string, unknown> | undefined,
  name: string,
): boolean {
  if (!caseParams || !Object.prototype.hasOwnProperty.call(caseParams, name)) {
    return false
  }
  const value = caseParams[name]
  if (value === null || value === undefined) {
    return false
  }
  if (typeof value === 'string' && value.trim() === '') {
    return false
  }
  return true
}
