import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { unstableSetRender } from 'antd'
import { App } from './app/App'
import './styles.css'

// React 19 + antd 5：用 createRoot 替换静态方法的旧 render，消除兼容警告
unstableSetRender((node, container) => {
  const host = container as HTMLElement & {
    _reactRoot?: ReturnType<typeof createRoot>
  }
  host._reactRoot ??= createRoot(host)
  const root = host._reactRoot
  root.render(node)
  return () =>
    new Promise<void>((resolve) => {
      setTimeout(() => {
        root.unmount()
        resolve()
      }, 0)
    })
})

const rootEl = document.getElementById('root')
if (!rootEl) {
  throw new Error('根节点 #root 不存在')
}

createRoot(rootEl).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
