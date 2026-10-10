import { Form, Input, InputNumber, Radio, Typography } from 'antd'
import type { FormInstance } from 'antd/es/form'
import type { ParamInfo } from './types'

interface ParamFormProps {
  form: FormInstance<Record<string, unknown>>
  params: ParamInfo[]
  disabled?: boolean
}

const BOOL_OPTIONS = [
  { label: 'true', value: true },
  { label: 'false', value: false },
]

export function ParamForm({ form, params, disabled }: ParamFormProps) {
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
        params.map((item) => (
          <Form.Item
            key={item.name}
            name={item.name}
            label={item.name}
            extra={item.description ?? undefined}
            rules={
              item.required
                ? [
                    {
                      required: true,
                      message:
                        item.type === 'boolean'
                          ? '请选择该参数'
                          : '请填写该参数',
                    },
                  ]
                : undefined
            }
          >
            {renderControl(item)}
          </Form.Item>
        ))
      )}
    </Form>
  )
}

function renderControl(item: ParamInfo) {
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
  if (item.type === 'number') {
    return (
      <InputNumber
        style={{ width: '100%' }}
        placeholder={item.required ? '必填数字' : '可选数字'}
        aria-label={item.name}
        data-testid={`param-${item.name}`}
      />
    )
  }
  return (
    <Input
      placeholder={item.required ? '必填' : '可选'}
      aria-label={item.name}
      data-testid={`param-${item.name}`}
      allowClear
    />
  )
}
