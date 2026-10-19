import { Form, Input, InputNumber, Radio, Typography } from 'antd'
import type { FormInstance } from 'antd/es/form'
import { resolveParameterValues, validParameterDefault } from './parameterValues'
import type { ParameterContext, ParamInfo } from './types'

interface ParamFormProps {
  context?: ParameterContext
  form: FormInstance<Record<string, unknown>>
  params: ParamInfo[]
  disabled?: boolean
  /** 当前环境 case_params。有默认值的必填项允许留空，且不把默认值填进表单。 */
  caseParams?: Record<string, unknown>
  assetDefaults?: Record<string, unknown>
}

const BOOL_OPTIONS = [
  { label: 'true', value: true },
  { label: 'false', value: false },
]

export function ParamForm({ form, params, disabled, caseParams, assetDefaults, context }: ParamFormProps) {
  const defaults = resolveParameterValues(context?.git_defaults ?? assetDefaults, context?.shared_environment ?? caseParams, {}, params.map((item) => item.name), context?.asset_default.values, context?.environment_override.values)
  return (
    <Form
      form={form}
      layout="vertical"
      requiredMark="optional"
      disabled={disabled}
      style={{ maxWidth: 480 }}
    >
      {params.length === 0 ? (
        <Typography.Text type="secondary" data-testid="params-empty">
          该 API 无需参数
        </Typography.Text>
      ) : (
        params.map((item) => {
          const row = defaults.find((row) => row.name === item.name)!
          const covered = validParameterDefault(item, row)
          const source = row.source === 'environment' ? '环境默认值' : row.source === 'override' ? '当前资产环境覆盖' : row.source === 'saved' ? '页面默认值' : '资产默认值'
          return (
            <Form.Item
              key={item.name}
              name={item.name}
              label={item.name}
              extra={fieldExtra(item, covered, source)}
              rules={
                item.required && !covered
                  ? [
                      {
                        required: true,
                        message: item.type === 'boolean' ? '请选择该参数' : '请填写该参数',
                      },
                    ]
                  : undefined
              }
            >
              {renderControl(item, covered, source)}
            </Form.Item>
          )
        })
      )}
    </Form>
  )
}

function fieldExtra(item: ParamInfo, covered: boolean, source: string): string | undefined {
  const hint = covered ? `留空使用${source}，本次请求不提交该参数` : null
  const parts = [item.description, hint].filter((part): part is string => Boolean(part))
  return parts.length > 0 ? parts.join('。') : undefined
}

function renderControl(item: ParamInfo, covered: boolean, source: string) {
  if (item.type === 'object' || item.type === 'array') {
    return <Input.TextArea
      aria-label={item.name} data-testid={`param-${item.name}`}
      placeholder={covered ? `留空使用${source}` : item.type === 'array' ? 'JSON 数组，例如 []' : 'JSON 对象，例如 {}'}
      autoSize={{ minRows: 3, maxRows: 12 }}
    />
  }
  if (item.type === 'boolean') {
    return (
      <Radio.Group
        options={BOOL_OPTIONS}
        optionType="button"
        buttonStyle="solid"
        aria-label={item.name}
        data-testid={`param-${item.name}`}
      />
    )
  }
  const placeholder = covered ? `留空使用${source}` : item.required
      ? item.type === 'number'
        ? '必填数字'
        : '必填'
    : item.type === 'number'
      ? '可选数字'
      : '可选'
  if (item.type === 'number') {
    return (
      <InputNumber
        style={{ width: '100%' }}
        placeholder={placeholder}
        aria-label={item.name}
        data-testid={`param-${item.name}`}
      />
    )
  }
  if (/password|passwd|pwd|secret|token/i.test(item.name)) {
    return <Input.Password placeholder={placeholder} aria-label={item.name} data-testid={`param-${item.name}`} />
  }
  return (
    <Input
      placeholder={placeholder}
      aria-label={item.name}
      data-testid={`param-${item.name}`}
      allowClear
    />
  )
}
