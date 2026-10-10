import { Form, Input, Modal, Select } from 'antd'
import { useEffect } from 'react'
import {
  ApiHttpError,
  fieldErrorsFromDetail,
} from '@/shared/api/errors'
import type { ProjectCreate, ProjectResponse } from '@/shared/types/project'

const ENV_OPTIONS = [
  { value: 'test', label: 'test' },
  { value: 'staging', label: 'staging' },
  { value: 'prod', label: 'prod' },
]

export type ProjectFormValues = {
  name: string
  env: string
  assets_root: string
  config_root: string
}

interface ProjectFormModalProps {
  open: boolean
  mode: 'create' | 'edit'
  initial?: ProjectResponse | null
  submitting?: boolean
  onCancel: () => void
  onSubmit: (values: ProjectCreate) => Promise<void>
}

export function ProjectFormModal({
  open,
  mode,
  initial,
  submitting = false,
  onCancel,
  onSubmit,
}: ProjectFormModalProps) {
  const [form] = Form.useForm<ProjectFormValues>()

  useEffect(() => {
    if (!open) {
      return
    }
    if (mode === 'edit' && initial) {
      form.setFieldsValue({
        name: initial.name,
        env: initial.env,
        assets_root: initial.assets_root,
        config_root: initial.config_root,
      })
    } else {
      form.setFieldsValue({
        name: '',
        env: 'test',
        assets_root: '',
        config_root: '',
      })
    }
  }, [open, mode, initial, form])

  const handleOk = async () => {
    try {
      const values = await form.validateFields()
      await onSubmit({
        name: values.name.trim(),
        env: values.env,
        assets_root: values.assets_root.trim(),
        config_root: values.config_root.trim(),
      })
      form.resetFields()
    } catch (error) {
      if (error instanceof ApiHttpError) {
        const fieldErrors = fieldErrorsFromDetail(error.detail)
        const entries = Object.entries(fieldErrors)
        if (entries.length > 0) {
          form.setFields(
            entries.map(([name, errors]) => ({
              name: name as keyof ProjectFormValues,
              errors: [errors],
            })),
          )
          return
        }
        form.setFields([
          {
            name: 'name',
            errors: [error.message],
          },
        ])
        return
      }
      // Form.validateFields 的校验失败不向外抛；其余错误交给上层
      if (error && typeof error === 'object' && 'errorFields' in error) {
        return
      }
      throw error
    }
  }

  return (
    <Modal
      title={mode === 'create' ? '新建项目' : '编辑项目'}
      open={open}
      onCancel={() => {
        if (!submitting) {
          onCancel()
        }
      }}
      onOk={() => {
        void handleOk()
      }}
      confirmLoading={submitting}
      okButtonProps={{ disabled: submitting }}
      cancelButtonProps={{ disabled: submitting }}
      destroyOnHidden
      maskClosable={!submitting}
      width={520}
    >
      <Form
        form={form}
        layout="vertical"
        requiredMark="optional"
        style={{ marginTop: 12 }}
        disabled={submitting}
      >
        <Form.Item
          label="项目名称"
          name="name"
          rules={[
            { required: true, message: '请输入项目名称' },
            { whitespace: true, message: '项目名称不能为空' },
          ]}
        >
          <Input placeholder="例如 my-api-tests" autoFocus maxLength={128} />
        </Form.Item>
        <Form.Item
          label="环境"
          name="env"
          rules={[{ required: true, message: '请选择环境' }]}
        >
          <Select options={ENV_OPTIONS} />
        </Form.Item>
        <Form.Item
          label="资产目录"
          name="assets_root"
          rules={[
            { required: true, message: '请输入资产目录' },
            { whitespace: true, message: '资产目录不能为空' },
          ]}
        >
          <Input placeholder="/path/to/assets" />
        </Form.Item>
        <Form.Item
          label="配置目录"
          name="config_root"
          rules={[
            { required: true, message: '请输入配置目录' },
            { whitespace: true, message: '配置目录不能为空' },
          ]}
        >
          <Input placeholder="/path/to/config" />
        </Form.Item>
      </Form>
    </Modal>
  )
}
