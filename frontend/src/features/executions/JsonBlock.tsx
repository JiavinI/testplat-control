import { Button, Space, Typography } from 'antd'
import { CopyOutlined } from '@ant-design/icons'
import { useMemo, useState } from 'react'

interface JsonBlockProps {
  value: unknown
  maxHeight?: number
  emptyText?: string
  'aria-label'?: string
}

function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

/** 可滚动、可复制的 JSON 视图；未知结构容错，不崩溃 */
export function JsonBlock({
  value,
  maxHeight = 240,
  emptyText = '（空）',
  'aria-label': ariaLabel,
}: JsonBlockProps) {
  const [copied, setCopied] = useState(false)
  const text = useMemo(() => {
    if (value === undefined) {
      return emptyText
    }
    if (value === null) {
      return 'null'
    }
    if (typeof value === 'string') {
      return value
    }
    return safeStringify(value)
  }, [value, emptyText])

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // 剪贴板不可用时静默失败，仍展示文本
    }
  }

  return (
    <div aria-label={ariaLabel}>
      <Space style={{ marginBottom: 4, width: '100%', justifyContent: 'flex-end' }}>
        <Button
          size="small"
          type="link"
          icon={<CopyOutlined />}
          onClick={() => {
            void handleCopy()
          }}
          aria-label="复制 JSON"
        >
          {copied ? '已复制' : '复制'}
        </Button>
      </Space>
      <pre
        style={{
          margin: 0,
          maxHeight,
          overflow: 'auto',
          padding: 12,
          background: '#faf6f0',
          border: '1px solid #e7e0d5',
          borderRadius: 10,
          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
          fontSize: 12,
          lineHeight: 1.5,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
        }}
      >
        <Typography.Text style={{ fontFamily: 'inherit', fontSize: 'inherit' }}>
          {text}
        </Typography.Text>
      </pre>
    </div>
  )
}
