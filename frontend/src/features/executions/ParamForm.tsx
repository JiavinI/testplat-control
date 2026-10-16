import { Form, Input, InputNumber, Radio, Typography } from 'antd'
import type { FormInstance } from 'antd/es/form'
import { hasEnvCaseDefault } from './envDefaults'
import type { ParamInfo } from './types'

interface ParamFormProps {
  form: FormInstance<Record<string, unknown>>
  params: ParamInfo[]
  disabled?: boolean
  /** 当前环境 case_params。有默认值的必填项允许留空，且不把默认值填进表单。 */
  caseParams?: Record<string, unknown>
}

const BOOL_OPTIONS = [
  { label: 'true', value: true },
  { label: 'false', value: false },
]

export function ParamForm({ form, params, disabled, caseParams }: ParamFormProps) {
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
          const covered = item.required && hasEnvCaseDefault(caseParams, item.name)
          return (
            <Form.Item
              key={item.name}
              name={item.name}
              label={item.name}
              extra={fieldExtra(item, covered)}
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
              {renderControl(item, covered)}
            </Form.Item>
          )
        })
      )}
    </Form>
  )
}

function fieldExtra(item: ParamInfo, covered: boolean): string | undefined {
  const hint = covered ? '留空使用环境默认值，本次请求不提交该参数' : null
  const parts = [item.description, hint].filter((part): part is string => Boolean(part))
  return parts.length > 0 ? parts.join('。') : undefined
}

function renderControl(item: ParamInfo, covered: boolean) {
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
  const placeholder = item.required
    ? covered
      ? '留空使用环境默认值'
      : item.type === 'number'
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
  return (
    <Input
      placeholder={placeholder}
      aria-label={item.name}
      data-testid={`param-${item.name}`}
      allowClear
    />
  )
}
